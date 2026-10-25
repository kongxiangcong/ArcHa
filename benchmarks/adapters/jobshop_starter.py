"""Baseline: random-swap descent of a longest-remaining-work dispatch order."""
import random

def solve(jobs, seed, evaluate, budget):
 rng=random.Random(seed)
 remaining=[sum(d for m,d in job) for job in jobs]
 positions=[0]*len(jobs); order=[]
 while len(order)<sum(map(len,jobs)):
  j=max((j for j in range(len(jobs)) if positions[j]<len(jobs[j])),key=lambda j:remaining[j])
  order.append(j);remaining[j]-=jobs[j][positions[j]][1];positions[j]+=1
 best=evaluate(order)
 for _ in range(budget-1):
  trial=order.copy();a,b=rng.sample(range(len(order)),2);trial[a],trial[b]=trial[b],trial[a]
  value=evaluate(trial)
  if value<best:order,best=trial,value
 return order
