"""Reproducible paired pilot; orchestration never proposes candidate improvements."""
from __future__ import annotations
import ast, hashlib, io, json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / 'benchmarks/experiments/paired-20261025'
PY = REPO / 'benchmarks/cache/venv/Scripts/python.exe'
BUDGET = dict(max_attempts=4, max_wall_seconds=600, max_tokens=600000,
              max_stagnation=3, max_consecutive_infra=2)
SPECS = {
 'jobshop-hard': dict(title='多实例 JobShop 求解算法优化',editable=['solver.py'],metric='mean_gap',target=0.08,
  direction='开发 solve(jobs, seed, evaluate, budget) 调度算法。返回工序 job-ID 序列。冻结 LA16/LA21/LA26、每例3000次调度评价、两个种子；平均相对已知最优 makespan 差距<=8%。禁止额外求解器、绕过回调预算、按实例硬编码答案。保留独立种子复验。'),
 'opentpu-sim': dict(title='openTPU 位精确 ISA 仿真器提速',editable=['opentpu/isasim.py'],metric='runtime_ratio',target=0.65,
  direction='优化真实 isasim.py，保留位精确语义和错误检查。冻结上游 ISA 测试及多种形状 VOP/归约工作负载；候选对冻结原版的同机中位时间比<=0.65。不能通过识别测试、导入oracle、缓存输入答案或删除正确性检查提速。这测仿真软件性能，不是板卡周期预测。'),
 'opentpu-roofline': dict(title='openTPU 多切片 roofline 兼容模型', editable=['model.py'],
   metric='mean_relative_error', target=0,
   direction='实现 model.predict(records, slices, cycles)，返回 bound 和 efficiency；匹配冻结 openTPU Profile.roofline 的下界语义，包括多切片、PAIR、端口 A/B 与 MXU。只做静态模型，不预测硬件实测周期。'),
 'ft06-search': json.loads((REPO/'benchmarks/cases/ft06-search/case.json').read_text(encoding='utf-8'))}

def write(path, data):
 path.parent.mkdir(parents=True, exist_ok=True)
 path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def git(root,*args):
 return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
def archive(src,dst):
 dst.mkdir(parents=True)
 raw=subprocess.check_output(['git','-C',str(src),'archive','--format=zip','HEAD'])
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  for m in z.infolist():
   if not m.filename.startswith('.opc/') and m.filename not in ('BENCHMARK.md','BENCHMARK-PROVENANCE.json'):
    z.extract(m,dst)
def init(root):
 for args in [('init','-q'),('config','core.autocrlf','false'),('config','core.longpaths','true'),('add','--all'),('-c','user.name=ArcHa Benchmark','-c','user.email=benchmark@localhost','commit','-qm','Frozen paired pilot baseline')]: git(root,*args)
def timed(case,phase,argv,cwd=None,timeout=None):
 logs=SUITE/case/'logs'; logs.mkdir(parents=True,exist_ok=True)
 label=f'{len(list(logs.glob("*.started.json"))):03d}-{phase}'
 meta=dict(phase=phase,argv=list(map(str,argv)),start=time.time())
 write(logs/(label+'.started.json'),meta)
 with (logs/(label+'.stdout.txt')).open('w',encoding='utf-8') as out,(logs/(label+'.stderr.txt')).open('w',encoding='utf-8') as err:
  p=subprocess.run(list(map(str,argv)),cwd=cwd or REPO,stdout=out,stderr=err,timeout=timeout)
 meta.update(returncode=p.returncode,wall_seconds=time.time()-meta['start'])
 write(logs/(label+'.json'),meta)
 print(json.dumps(meta),flush=True)
 print((logs/(label+'.stdout.txt')).read_text(encoding='utf-8')[-6000:],flush=True)
 if p.returncode: print((logs/(label+'.stderr.txt')).read_text(encoding='utf-8')[-3000:],flush=True)
 return p.returncode

def prepare(case):
 exp=SUITE/case; root=exp/'archa'; direct=exp/'direct'; spec=SPECS[case]
 assert not exp.exists(), 'refuse overwrite'
 source=REPO/('benchmarks/cache/opentpu' if case.startswith('opentpu-') else 'benchmarks/projects/ft06-search')
 archive(source,root)
 if case in ('opentpu-sim','jobshop-hard'):
  ev=root/'benchmark-inputs/eval';ev.mkdir(parents=True)
  shutil.copy2(REPO/('benchmarks/adapters/simulator.py' if case=='opentpu-sim' else 'benchmarks/adapters/jobshop_hard.py'),ev/'evaluate.py')
  if case=='opentpu-sim':
   shutil.copy2(root/'opentpu/isasim.py',ev/'original_isasim.py')
   shutil.copy2(root/'tests/test_isa.py',ev/'test_isa_frozen.py')
  else:
   shutil.copy2(REPO/'benchmarks/adapters/jobshop_starter.py',root/'solver.py')
 elif case=='opentpu-roofline':
  (root/'model.py').write_text('''"""Initial port-B-only lower bound; improve within this file."""
def predict(records, slices, cycles):
    bound = max((sum(r['portb'] for r in records if r['slice'] == s) for s in range(slices)), default=0)
    return {'bound': bound, 'efficiency': bound / cycles if cycles else 0.0}
''',encoding='utf-8')
  ev=root/'.opc/eval'; ev.mkdir(parents=True)
  shutil.copy2(REPO/'benchmarks/adapters/roofline.py',ev/'evaluate.py')
  # Extract exact upstream pure definitions, removing only imports of unavailable RTL tooling.
  tree=ast.parse((root/'opentpu/profile.py').read_text(encoding='utf-8'))
  nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in ('Rec','Profile')]
  oracle='from __future__ import annotations\nfrom dataclasses import dataclass, field\nfrom opentpu import isa as I\n'+ '\n\n'.join(ast.unparse(n) for n in nodes)
  (ev/'oracle.py').write_text(oracle,encoding='utf-8')
 else:
  shutil.copytree(source/'.opc/eval',root/'.opc/eval')
 if (root/'.opc/eval').exists():
  shutil.copytree(root/'.opc/eval',root/'benchmark-inputs/eval')
  # Evaluator integration belongs to onboard. Keep raw inputs outside .opc.
  shutil.rmtree(root/'.opc')
 shutil.copytree(root,direct)
 shutil.copytree(direct/'benchmark-inputs/eval',direct/'.opc/eval')
 for p in (root,direct): init(p)
 write(exp/'manifest.json',dict(case=case,spec=spec,upstream_commit=git(source,'rev-parse','HEAD'),
   upstream_url='https://github.com/FeSens/openTPU' if case.startswith('opentpu-') else 'https://github.com/Pabloo22/job_shop_lib',
   initial_commit=git(root,'rev-parse','HEAD'),budget=BUDGET,model='gpt-6.1-sol',reasoning_effort='medium',
   evaluator_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'benchmark-inputs/eval').iterdir()},
   start=time.time(),limitations=['single paired pilot','outer conversation tokens unavailable','token caps checked at worker boundaries, not hard intra-call limits']))
 return timed(case,'map-initialize',[PY,REPO/'skills/archa-map/scripts/initialize.py','--project',root])

def map_stage(case):
 root=SUITE/case/'archa'; r=root/'.opc/research'; t=r/'tasks/R01'; t.mkdir(parents=True)
 spec=SPECS[case]
 (r/'research-map.md').write_text(f'''# {spec['title']}
用途：检验 ArcHa 从研究讨论到自动执行的质量与开销，与直接 Codex 作同输入比较。
组织方式：原始模型/参数 → 冻结评价 → 自动改进 → 外部复验。
范围：{spec['direction']}
不研究：板卡实测或金融收益；不复用历史冠军。
## 研究任务 to-do
- [ ] R01 | [源码与评价调查](tasks/R01/task.md) | status=active | depends=none
## 下一步
$archa-task {r/'research-map.md'}
''',encoding='utf-8')
 (t/'task.md').write_text(f"R01: {spec['title']}\n[地图](../../research-map.md)\n范围：{spec['direction']}\n依赖：无。缺口：调查评价接口和边界。",encoding='utf-8')
 (r/'discussion.md').write_text(f'''# 模拟用户讨论 2026-10-25
真实授权：用户要求 Codex 模拟用户，按 archa-map → archa-task → archa-loop 推进并实际修复问题。
map 提议：单链路，聚焦 {spec['title']}。
模拟用户决定：接受上述用途和地图；不把静态建模当板卡精度，也不把单次搜索当普遍优越性。
本轮预算选择：{json.dumps(BUDGET)}；所有角色 gpt-6.1-sol / medium；直接 Codex 同样 600 秒与 600000 token 目标上限。
token 实际在调用结束时可见，两臂均披露超额，不能声称严格相同实耗。onboard 单独计成本。
''',encoding='utf-8')

def brief(case):
 root=SUITE/case/'archa'; r=root/'.opc/research'; t=r/'tasks/R01'; spec=SPECS[case]
 assert list((t/'evidence').glob('*.md'))
 outline=f"\n## task 建议整体大纲及模拟确认\nGoal：{spec['title']}；Done：correct=1 且 {spec['metric']}<={spec['target']}。Direction：{spec['direction']}\n范围仅 {spec['editable']}；交付候选文件和评价结果；R1 结果合法，R2 达标，均已有评价器。环境、合同映射交 onboard，预算和模型已确定。模拟用户确认整体大纲，无新增范围。\n"
 with (r/'discussion.md').open('a',encoding='utf-8') as f:f.write(outline)
 (t/'task-brief.md').write_text(f'''# {spec['title']}
## Source
Map: .opc/research/research-map.md
Status: ready-for-onboard
R01，2026-10-25 用户授权模拟用户；整体大纲确认见 discussion.md。
## Question and use
同输入比较 ArcHa 自动推进与直接 Codex，判断质量、时间、token 开销。单次探索性试验。
## Goal
Goal: {spec['title']}
Done when: correct == 1 and {spec['metric']} <= {spec['target']}
Direction: {spec['direction']}
## Evidence
本任务 evidence/ 包含本轮 sub-agent 源码与冻结评价器调查。
已有评价器原件 benchmark-inputs/eval/evaluate.py --out <输出目录>，成功生成 metrics.json，格式 {{"metrics": {{...}}}}。使用 Python {PY}。
onboard 必须将 benchmark-inputs/eval/ 全部文件原字节复制到 .opc/eval/，评价器硬编码运行路径。不要另建评价器或改写它。
## Scope and deliverables
In: {', '.join(spec['editable'])}
Out: 评价器、上游源码、测试、其他文件；不读其他实验目录或历史冠军；不联网找答案。
- D1: 可重放候选源码/参数 | Git 补丁和评价记录 | 本冻结输入域
- R1: 输出合法且 correct == 1 | verification=automated | evaluator=已有
- R2: {spec['metric']} <= {spec['target']} | verification=automated | evaluator=已有
Objective: {spec['metric']} minimize
Adjust if: 环境或框架缺陷可修复并另记干预，不能修改目标、扩大预算或给优化建议。
## Open decisions
已确定预算 {json.dumps(BUDGET)}。expert/designer timeout_s=600。所有角色模型 gpt-6.1-sol、reasoning_effort=medium。
acceptance min_rel_gain=0, repeats=1。onboard 负责具体合同与 evaluator_files；整个 .opc/eval/**、benchmark-inputs/** 和上游引用依赖均冻结。
本地 HEAD 为基线。保持 execution_enabled=false，不实施候选，不运行正式 preflight/run。
''',encoding='utf-8')
 return timed(case,'brief-check',[PY,root/'.opc/archa.py','brief-check','-p',root,'--brief','.opc/research/tasks/R01/task-brief.md'])

def direct(case):
 sys.path.insert(0,str(REPO))
 from opc.adapters.codex import CodexWorker
 root=SUITE/case/'direct'; spec=SPECS[case]; logs=SUITE/case/'direct-worker'
 prompt=f'''Complete this benchmark autonomously. Only edit {spec['editable']}. Task: {spec['direction']}
Target correct=1 and {spec['metric']} <= {spec['target']}. Existing frozen evaluator: {PY} .opc/eval/evaluate.py --out .pilot-results
Read local source as needed, iterate and test; keep your best valid result. Do not edit evaluator, tests or dependencies, do not read other projects/history, no network, no subagents. Do not use ArcHa.
Budget: 600 seconds and 600000 total input+output tokens; stop when target reached or budget exhausted. Same gpt-6.1-sol/medium as ArcHa. Report result and remaining limitations. Only {spec['editable']} may be changed; .pilot-results is disposable evaluation output.
'''
 call,text=CodexWorker(dict(model='gpt-6.1-sol',reasoning_effort='medium',timeout_s=600))._run('direct',prompt,root,logs,'workspace-write',None)
 write(SUITE/case/'direct-result.json',dict(ok=call.ok,error=call.error,seconds=call.cost.wall_seconds,tokens=call.cost.tokens,summary=text))
 print(text,flush=True)

if __name__=='__main__':
 case,phase=sys.argv[1:3]; root=SUITE/case/'archa'
 os.environ['PYTHONUTF8']='1'; os.environ['PYTHONDONTWRITEBYTECODE']='1'
 if phase=='prepare':sys.exit(prepare(case))
 if phase=='map':map_stage(case)
 elif phase=='brief':sys.exit(brief(case))
 elif phase=='direct':direct(case)
 else:
  args=([phase,'-p',root,'--brief','.opc/research/tasks/R01/task-brief.md'] if phase=='onboard' else [phase,'-p',root,'--task','t-main','--revision','r0001'])
  sys.exit(timed(case,phase,[PY,root/'.opc/archa.py',*args],root))
