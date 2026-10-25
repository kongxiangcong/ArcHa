"""Frozen callback-budget JobShop benchmark with independent schedule reconstruction."""
from __future__ import annotations
import argparse, json, sys, time
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True

def makespan(jobs,order):
 assert len(order)==sum(map(len,jobs))
 assert Counter(order)==Counter({j:len(job) for j,job in enumerate(jobs)})
 pos=[0]*len(jobs);ends=[0]*len(jobs);machines=[0]*(1+max(m for job in jobs for m,d in job))
 for j in order:
  m,d=jobs[j][pos[j]];finish=max(ends[j],machines[m])+d
  ends[j]=machines[m]=finish;pos[j]+=1
 return max(ends)

def evaluate(seed_offset=0):
 from solver import solve
 raw=json.loads((ROOT/'job_shop_lib/benchmarking/benchmark_instances.json').read_text())
 scores=[];gaps=[];counts=[];start=time.perf_counter()
 for name in ('la16','la21','la26'):
  data=raw[name]; jobs=[list(zip(m,d)) for m,d in zip(data['machines_matrix'],data['duration_matrix'])]
  optimum=data['metadata']['optimum'];assert optimum
  for seed in (42+seed_offset,43+seed_offset):
   count=[0]
   def score(order):
    count[0]+=1
    assert count[0]<=3000,'evaluation budget exceeded'
    return makespan(jobs,order)
   # Separate solver input prevents accidental candidate mutation of the oracle's jobs.
   result=solve([[tuple(op) for op in job] for job in jobs],seed,score,3000)
   value=makespan(jobs,result);assert value>=optimum
   gaps.append(value/optimum-1);scores.append(dict(instance=name,seed=seed,makespan=value,optimum=optimum));counts.append(count[0])
 return dict(correct=1,mean_gap=sum(gaps)/len(gaps),worst_gap=max(gaps),evaluations=sum(counts),evaluation_wall_seconds=time.perf_counter()-start),scores

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--seed-offset',type=int,default=0);a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=True);dest=a.out/'metrics.json';dest.unlink(missing_ok=True)
 metrics,scores=evaluate(a.seed_offset);dest.write_text(json.dumps(dict(metrics=metrics,scores=scores),indent=2),encoding='utf-8');print(json.dumps(dict(metrics=metrics,scores=scores)))
