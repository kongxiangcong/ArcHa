"""Bounded selection preflight; run against an unmodified fixed checkout."""
import argparse
import cProfile
import dataclasses
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import platform
import pstats
import signal
import statistics
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(args.source/'src/deepstack'), str(args.source/'src/tilesight')]
logging.disable(logging.CRITICAL)
started = time.perf_counter()
import numpy as np
import torch
torch.set_num_threads(1)
from mosaic.op_dtype.gemm_wrapper import get_modeling_time, get_default_tiling, get_auto_tune_tiling
from mosaic.utils import OpBytes, Tensor_Loc
from tilesight.arch import H100
from bank_oracle import DramBankSpec, service_sectors
from bank_oracle.gemm import (GemmProblem, GemmTiling, GemmBankOptions,
    make_layout_set, model_gemm_bank, search_gemm_layouts)
import_seconds = time.perf_counter()-started

# Reuse the upstream caller-owned synthetic profile, not sealed calibration.
sys.path.insert(0, str(args.source/'tests'))
from test_custom_arch_profile import _synthetic_config
from mosaic.arch.custom_profile import make_custom_stacked_gpu
chips = {'h100': H100(), 'synthetic_3d': make_custom_stacked_gpu(_synthetic_config())}
meta = dict(python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count(),
    source=str(args.source), commit='17e21bf54115e11b9e7c6edc0b2d1723d25d022b',
    dependency_versions={x:importlib.metadata.version(x) for x in ['numpy','torch','scipy','pandas']},
    import_seconds=import_seconds, thread_env={x:os.environ.get(x) for x in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']},
    method='first call then 7 warm batches; adaptive calls/batch capped at 100; 45s per case; serial execution; no profiler in timing',
    dram_spec=dataclasses.asdict(DramBankSpec()))
(args.output/'environment.json').write_text(json.dumps(meta, indent=2))
results=[]

def timeout(signum,frame):
    raise TimeoutError('45-second case limit')
signal.signal(signal.SIGALRM,timeout)

def measure(name, fn, summarize, config, profile=False):
    row=dict(name=name,config=config)
    signal.alarm(45)
    try:
        t=time.perf_counter(); value=fn(); first=time.perf_counter()-t
        count=max(1,min(100,int(0.03/max(first,1e-9))))
        samples=[]
        for _ in range(7):
            t=time.perf_counter()
            for _ in range(count): value=fn()
            samples.append((time.perf_counter()-t)/count)
        row.update(status='ok',first_s=first,calls_per_batch=count,warm_s=samples,
                   median_s=statistics.median(samples),min_s=min(samples),max_s=max(samples),output=summarize(value))
        if profile:
            pr=cProfile.Profile();pr.runcall(fn)
            out=io.StringIO();pstats.Stats(pr,stream=out).strip_dirs().sort_stats('cumulative').print_stats(22)
            (args.output/(name+'.profile.txt')).write_text(out.getvalue())
    except Exception as exc:
        row.update(status='error',error=repr(exc))
    finally:
        signal.alarm(0)
    results.append(row)
    (args.output/'timings.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(row),flush=True)

op=OpBytes(Tensor_Loc(torch.float16,'ddr'),Tensor_Loc(torch.float16,'ddr'),Tensor_Loc(torch.float16,'ddr'))
shapes=[(1,4096,4096),(128,4096,4096),(1024,4096,4096),(4096,4096,4096)]
for arch,chip in chips.items():
    for shape in shapes:
        tile=get_default_tiling(*shape,op,chip)
        fn=lambda shape=shape,tile=tile,chip=chip:get_modeling_time(*shape,op,chip,tile)
        measure('gemm_'+arch+'_'+str(shape[0]),fn,lambda r:{'predicted_latency_s':float(r[1][0])},
                dict(shape=shape,tiling=tile),profile=shape[0]==1024)
    shape=(1024,4096,4096)
    configs=tuple(get_auto_tune_tiling(*shape,op,chip))
    def scan(chip=chip,configs=configs,shape=shape):
        return [get_modeling_time(*shape,op,chip,c)[1][0] for c in configs]
    measure('gemm_candidate_scan_'+arch,scan,lambda r:{'min_predicted_latency_s':float(min(r)), 'candidates':len(r)},dict(shape=shape,candidates=len(configs)))

spec=DramBankSpec()
tile=GemmTiling(32,32,32,stage=2,ctas_per_wave=8)
for size in [64,256,1024,4096]:
    problem=GemmProblem(size,size,size)
    layout=make_layout_set(problem,tile,spec)
    for mode in ['sampled','exact']:
        if mode=='exact' and size>256:continue
        options=GemmBankOptions() if mode=='sampled' else GemmBankOptions(max_spatial_samples=None,max_k_samples=None)
        fn=lambda problem=problem,layout=layout,options=options:model_gemm_bank(problem,tile,layout,spec,options)
        measure('bank_'+mode+'_'+str(size),fn,lambda r:dict(predicted_memory_cycles=r.total_memory_cycles,profiles=len(r.sampled_profiles)),dict(shape=[size]*3,tiling=dataclasses.asdict(tile),options=dataclasses.asdict(options)),profile=size==1024)
problem=GemmProblem(1024,1024,1024)
measure('bank_layout_search_1024',lambda:search_gemm_layouts(problem,tile,spec,workers=0,backend='serial'),
        lambda r:dict(candidates=len(r.results),best_memory_cycles=r.best.total_memory_cycles),dict(shape=[1024]*3,tiling=dataclasses.asdict(tile),options=dataclasses.asdict(GemmBankOptions()),backend='serial'),profile=True)
for count in [4096,65536,1048576]:
    sectors=np.arange(count,dtype=np.int64)
    measure('bank_sectors_'+str(count),lambda sectors=sectors:service_sectors(sectors,spec),
            lambda r:dict(sectors=r.sector_count,predicted_cycles=r.cycles),dict(sectors=count,pattern='contiguous'),profile=count==1048576)
