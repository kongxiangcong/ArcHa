"""Bounded qualification of coupled bank/FIFO paths; not an optimization judge."""
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

CASES = {
 'full_no_l2':dict(size=256,connected=8,capacity=0,pressure=True),
 'shared_no_l2':dict(size=256,connected=2,capacity=0,pressure=True),
 'shared_fifo_small':dict(size=256,connected=2,capacity=8192,pressure=True),
 'shared_fifo_large':dict(size=256,connected=2,capacity=131072,pressure=True),
 'shared_fifo_no_pressure':dict(size=256,connected=2,capacity=131072,pressure=False),
 'shared_fifo_512':dict(size=512,connected=2,capacity=131072,pressure=True),
 'shared_layout_search':dict(size=128,connected=2,capacity=32768,pressure=True,search=True),
}
parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--case',choices=CASES)
args=parser.parse_args()
if args.case:
    sys.path[:0]=[str(args.source/'src/deepstack'),str(args.source/'src/tilesight')]
    import numpy as np
    from bank_oracle import DramBankSpec,L2CacheSpec
    from bank_oracle.gemm import (GemmProblem,GemmTiling,GemmBankOptions,
        make_layout_set,model_gemm_bank,search_gemm_layouts,_cached_gemm_l2_trace)
    cfg=CASES[args.case]
    problem=GemmProblem(*([cfg['size']]*3))
    tile=GemmTiling(32,32,32,stage=2,ctas_per_wave=8)
    spec=DramBankSpec(connected_layers=cfg['connected'])
    options=GemmBankOptions(l2_cache=L2CacheSpec(cfg['capacity'],output_pressure=cfg['pressure']) if cfg['capacity'] else None)
    layout=make_layout_set(problem,tile,spec)
    def run():
        if cfg.get('search'):
            return search_gemm_layouts(problem,tile,spec,options,workers=0,backend='serial')
        return model_gemm_bank(problem,tile,layout,spec,options)
    def canonical(x):
        if dataclasses.is_dataclass(x):
            return {f.name:canonical(getattr(x,f.name)) for f in dataclasses.fields(x) if f.name!='runtime_seconds'}
        if isinstance(x,np.ndarray):return {'dtype':str(x.dtype),'shape':list(x.shape),'values':x.tolist()}
        if isinstance(x,np.generic):return x.item()
        if isinstance(x,(tuple,list)):return [canonical(y) for y in x]
        if isinstance(x,dict):return {str(k):canonical(v) for k,v in x.items()}
        return x
    def digest(x):
        return hashlib.sha256(json.dumps(canonical(x),sort_keys=True,allow_nan=False).encode()).hexdigest()
    _cached_gemm_l2_trace.cache_clear()
    t=time.perf_counter();cold=run();cold_s=time.perf_counter()-t
    cold_cache=_cached_gemm_l2_trace.cache_info()._asdict()
    t=time.perf_counter();warm=run();warm_s=time.perf_counter()-t
    warm_cache=_cached_gemm_l2_trace.cache_info()._asdict()
    result=cold.best if cfg.get('search') else cold
    normalized=canonical(result)
    # State lifecycle check: change the physical problem, then revisit original.
    alt_spec=DramBankSpec(connected_layers=1)
    model_gemm_bank(problem,tile,layout,alt_spec,options)
    revisit=run()
    d=digest(cold)
    summary=dict(cycles=result.total_memory_cycles,read_bytes=result.actual_read_bytes,write_bytes=result.actual_write_bytes,
        profiles=len(result.sampled_profiles),l2=normalized['l2_result'],
        candidates=len(cold.results) if cfg.get('search') else 1,
        best_layout=result.layouts.name)
    print(json.dumps(dict(case=args.case,config=cfg,cold_s=cold_s,warm_s=warm_s,
        cold_cache=cold_cache,warm_cache=warm_cache,digest=d,
        cold_warm_equal=d==digest(warm),after_config_change_equal=d==digest(revisit),
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        output=summary)))
else:
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for name in CASES:
        samples=[]
        for repeat in range(3):
            cmd=[sys.executable,__file__,'--source',str(args.source),'--output',str(args.output),'--case',name]
            try:
                p=subprocess.run(cmd,text=True,capture_output=True,timeout=45,env=os.environ.copy())
                if p.returncode: raise RuntimeError(p.stderr[-2500:])
                samples.append(json.loads(p.stdout))
            except Exception as exc:
                samples.append({'error':repr(exc)})
                break
        row={'case':name,'samples':samples}
        if all('cold_s' in x for x in samples):
            row.update(cold_median_s=statistics.median(x['cold_s'] for x in samples),
                warm_median_s=statistics.median(x['warm_s'] for x in samples),
                peak_rss_kib=max(x['max_rss_kib'] for x in samples),
                stable_across_processes=len(set(x['digest'] for x in samples))==1,
                stable_within_process=all(x['cold_warm_equal'] and x['after_config_change_equal'] for x in samples))
        rows.append(row)
        (args.output/'results.json').write_text(json.dumps(rows,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k!='samples'}),flush=True)
