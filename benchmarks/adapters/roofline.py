"""Frozen openTPU roofline oracle; no RTL execution and no board accuracy claim."""
from __future__ import annotations
import argparse, importlib.util, json, math, random, sys, time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True

def evaluate(seed=4271):
 from model import predict
 from opentpu import isa as I
 spec=importlib.util.spec_from_file_location('roofline_oracle',ROOT/'.opc/eval/oracle.py')
 oracle=importlib.util.module_from_spec(spec);sys.modules[spec.name]=oracle;spec.loader.exec_module(oracle)
 rng=random.Random(seed); errors=[]; mismatches=0; start=time.perf_counter()
 for k in range(100):
  slices=(0,1,2,4,8)[k%5]; cycles=0 if k%13==0 else rng.randrange(1,10000)
  recs=[]
  for s in range(slices):
   for j in range(rng.randrange(0,20)):
    recs.append(dict(slice=s,idx=j,pc=j,op=rng.choice([I.MM,I.LD,I.QST]),unit=0,dispatch=0,
       detail=rng.choice(['',' pair',' pair +acc',' +acc']),work=rng.randrange(200),portb=rng.randrange(100),porta=2*rng.randrange(100)))
  expected=oracle.Profile('test',SimpleNamespace(S=slices),cycles,[oracle.Rec(**r) for r in recs],[],[]).roofline()
  actual=predict(recs,slices,cycles)
  assert isinstance(actual,dict)
  assert all(isinstance(actual[x],(int,float)) and math.isfinite(actual[x]) and actual[x]>=0 for x in ('bound','efficiency'))
  err=max(abs(actual[x]-expected[x])/max(1,abs(expected[x])) for x in ('bound','efficiency'))
  errors.append(err);mismatches+=err>1e-12
 return dict(correct=1,mean_relative_error=sum(errors)/len(errors),mismatched_cases=mismatches,cases=len(errors),evaluation_wall_seconds=time.perf_counter()-start)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,default=4271);a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=True);dest=a.out/'metrics.json';dest.unlink(missing_ok=True)
 metrics=evaluate(a.seed);dest.write_text(json.dumps(dict(metrics=metrics),indent=2),encoding='utf-8');print(json.dumps(metrics))
