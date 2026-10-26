"""Frozen same-process ISA reference comparison; elapsed ratios exclude setup and tests."""
from __future__ import annotations
import argparse,importlib.util,json,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True

def evaluate(out,seed):
 import numpy as np
 from opentpu import isa as I
 from opentpu import isasim as candidate
 spec=importlib.util.spec_from_file_location('opentpu._benchmark_original',ROOT/'.opc/eval/original_isasim.py')
 original=importlib.util.module_from_spec(spec);sys.modules[spec.name]=original;spec.loader.exec_module(original)
 # No upstream conftest: it imports Linux RTL tools. This copied file has no custom fixtures.
 p=subprocess.run([sys.executable,'-m','pytest','-q','--confcutdir='+str(ROOT/'.opc/eval'),str(ROOT/'.opc/eval/test_isa_frozen.py')],cwd=ROOT,capture_output=True,text=True)
 (out/'isa-tests.txt').write_text(p.stdout+p.stderr,encoding='utf-8');assert p.returncode==0,p.stdout+p.stderr
 rng=np.random.default_rng(seed);ratios=[];raw=[]
 for rows,cols in ((1,128),(8,128),(32,128),(16,63)):
  n=rows*cols;dram=np.zeros(1<<18,np.uint8);dram[:n*4]=rng.standard_normal(n).astype(np.float32).view(np.uint8)
  prog=[I.ld(0,0,n)]
  for _ in range(12):
   prog += [I.vop(I.V_ADD,n,0,0,rows,cols,cols,cols,0,I.B_SCALAR,0.125),
            I.vop(I.V_MUL,0,n,0,rows,cols,cols,cols,0,I.B_SCALAR,0.875),
            I.vop(I.V_RSUM,2*n,0,0,rows,cols,1,cols,0)]
  prog += [I.st(0,0,n),I.halt()]
  cfg=original.Config(S=1,DRAM_BYTES=1<<18)
  def run(module):return module.Machine(cfg,[prog],[dram.copy()]).run().slices[0]
  ref=run(original);got=run(candidate)
  for attr in ('tmem','dram','act','ascale','adoff','R'):
   assert np.array_equal(np.asarray(getattr(ref,attr)).view(np.uint8),np.asarray(getattr(got,attr)).view(np.uint8)),attr
  times={'candidate':[],'original':[]}
  for rep in range(5):
   for name,module in ([('candidate',candidate),('original',original)] if rep%2 else [('original',original),('candidate',candidate)]):
    t=time.perf_counter()
    for _ in range(3):run(module)
    times[name].append(time.perf_counter()-t)
  ratio=statistics.median(times['candidate'])/statistics.median(times['original']);ratios.append(ratio)
  raw.append(dict(rows=rows,cols=cols,ratio=ratio,times=times))
 (out/'timings.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
 return dict(correct=1,runtime_ratio=statistics.mean(ratios),worst_runtime_ratio=max(ratios),workloads=len(ratios))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,default=4271);a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=True);dest=a.out/'metrics.json';dest.unlink(missing_ok=True)
 metrics=evaluate(a.out,a.seed);dest.write_text(json.dumps(dict(metrics=metrics),indent=2),encoding='utf-8');print(json.dumps(metrics))
