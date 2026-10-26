"""Measurement-only runner for the sequential 2026-10-24 skill exercise."""
import hashlib, io, json, shutil, subprocess, sys, time, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUITE = Path(__file__).resolve().parents[1] / 'experiments/fullflow-20261024'
PY = REPO / 'benchmarks/cache/venv/Scripts/python.exe'
SKILL = Path('C:/Users/72449/.codex/skills')

def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def timed(case, phase, argv, cwd=None):
    exp = SUITE / case
    logs = exp / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    label = f'{len(list(logs.glob("*.json"))):03d}-{phase}'
    onboard_dir=exp/'project/.opc/local/onboard'
    if phase=='onboard' and onboard_dir.exists():
        shutil.copytree(onboard_dir,logs/(label+'-previous-onboard'))
    t = time.time()
    write(logs / (label+'.started.json'), dict(phase=phase, argv=list(map(str,argv)), start=t))
    with (logs/(label+'.stdout.txt')).open('w',encoding='utf-8') as out, (logs/(label+'.stderr.txt')).open('w',encoding='utf-8') as err:
        p = subprocess.run(list(map(str,argv)), cwd=cwd or REPO, stdout=out, stderr=err)
    write(logs/(label+'.json'), dict(phase=phase,argv=list(map(str,argv)),start=t,end=time.time(),wall_seconds=time.time()-t,returncode=p.returncode))
    print(label, 'exit', p.returncode, flush=True)
    print((logs/(label+'.stdout.txt')).read_text(encoding='utf-8')[-12000:], flush=True)
    if p.returncode:
        print((logs/(label+'.stderr.txt')).read_text(encoding='utf-8')[-5000:], flush=True)
    return p.returncode

def prepare(case):
    exp=SUITE/case
    exp.mkdir(parents=True,exist_ok=True)
    template=REPO/'benchmarks/projects'/case
    t=time.time()
    raw=subprocess.check_output(['git','-C',str(template),'archive','--format=zip','HEAD'])
    root=exp/'project'
    root.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for member in z.infolist():
            if not member.filename.startswith('.opc/') and member.filename not in ('BENCHMARK.md','BENCHMARK-PROVENANCE.json'):
                z.extract(member,root)
    shutil.copytree(template/'.opc/eval',exp/'frozen-eval')
    shutil.copytree(exp/'frozen-eval',root/'benchmark-inputs/eval')
    spec=json.loads((REPO/'benchmarks/cases'/case/'case.json').read_text(encoding='utf-8'))
    provenance=json.loads((template/'BENCHMARK-PROVENANCE.json').read_text(encoding='utf-8'))
    write(exp/'manifest.json',dict(case=case,spec=spec,source=provenance['source'],start=t,template_commit=subprocess.check_output(['git','-C',str(template),'rev-parse','HEAD']).decode().strip(),frozen_source=str(template/'.opc/eval'),default_budget=dict(max_attempts=20,max_wall_seconds=7200,max_tokens=2000000,max_stagnation=6,max_consecutive_infra=3)))
    for args in (['init','-q'],['config','core.autocrlf','false'],['config','core.longpaths','true'],['add','--all'],['-c','user.name=ArcHa Benchmark','-c','user.email=benchmark@localhost','commit','-qm','Original independent baseline without ArcHa contracts']):
        subprocess.run(['git','-C',str(root),*args],check=True)
    return timed(case,'map-initialize',[PY,REPO/'skills/archa-map/scripts/initialize.py','--project',root])

def map_stage(case):
    exp=SUITE/case; root=exp/'project'; r=root/'.opc/research'; task=r/'tasks/R01'
    task.mkdir(parents=True,exist_ok=True)
    spec=json.loads((exp/'manifest.json').read_text(encoding='utf-8'))['spec']
    (r/'research-map.md').write_text(f'''# {spec['title']}：独立基线流程实测

用途：检验从原始基线接入、自动迭代到最终验收的实际效果。
方向链路：独立基线 → {spec['title']} → 冻结正确性评价 → {spec['metric']} <= {spec['target']}。
本 case 只研究上述方向，不扩展到其他 case 或改变冻结工作负载。

## 研究任务 to-do
- [ ] R01 | [目标范围调查](tasks/R01/task.md) | status=active | depends=none

## 下一步
$archa-task {r/'research-map.md'}
''',encoding='utf-8')
    (task/'task.md').write_text(f"R01: {spec['title']}\n[地图](../../research-map.md)\n问题与用途：在冻结评价下完成目标，实测流程。\n包含：{spec['direction']}\n排除：其他 case、评价器/目标/预算变更、旧冠军。\n依赖：无。缺口：task 阶段核实评价接口及源码范围。\n",encoding='utf-8')
    (r/'discussion.md').write_text(f'''# 模拟用户讨论 2026-10-24
用户明确授权 Codex 模拟 map、task 常规讨论、选择与确认。
map 建议：以单链路组织，聚焦 {spec['title']}，保持 case.json 目标和范围。
模拟用户确认此用途、方向和组织方式，明确不扩展任务。
当前焦点 R01；先派 subagent 调查任务边界，再确认整体 brief。
配置选择：当前框架默认（不用 benchmark profile）；预算采用 task_template 的 20 attempts / 7200s / 2000000 tokens / stagnation 6 / consecutive infra 3。用户已授权默认配置。
''',encoding='utf-8')
    write(exp/'map-stage.json',dict(phase='map',start=json.loads((exp/'manifest.json').read_text(encoding='utf-8'))['start'],end=time.time(),status='completed'))

def brief_stage(case):
    exp=SUITE/case; root=exp/'project'; r=root/'.opc/research'; task=r/'tasks/R01'
    spec=json.loads((exp/'manifest.json').read_text(encoding='utf-8'))['spec']
    assert list((task/'evidence').glob('*.md')), 'research evidence required'
    outline=f'''\n## task 整体大纲与确认\n任务 R01；问题：{spec['title']} 能否在冻结评价下达标？\nGoal: {spec['title']}\nDone when: correct=1 且 {spec['metric']}<={spec['target']}\nDirection: {spec['direction']}\n证据：evidence 中本次 subagent 的源码/评价器调查，主 agent 核对 case.json 与冻结评价器。\n包含：{spec['editable']}；排除冻结输入和其他实现。交付物 D1 为候选补丁和引擎结果，R1 正确性/R2 目标均由已有冻结评价器自动验证。\nObjective: {spec['metric']} minimize\nAdjust if: 环境/接入缺口先修复；不改目标、评价器或预算。\n留给 onboard：从源码与 frozen evaluator 确定具体合同，使用框架默认 budget/worker。未知仅为本次性能与消耗，须实测。\n模拟用户已依据本轮授权明确选择并确认以上整体大纲，无额外范围修改。\n'''
    with (r/'discussion.md').open('a',encoding='utf-8') as f: f.write(outline)
    brief=f'''# {spec['title']}

## Source
Map: .opc/research/research-map.md
Status: ready-for-onboard
R01，无依赖。2026-10-24 用户授权模拟用户进行常规讨论与确认；完整大纲和确认见 discussion.md。

## Question and use
本次从独立原始基线测试 ArcHa map/task/onboard/loop/验收的流程与任务效果。不复用旧冠军或账本。

## Goal
Goal: {spec['title']}
Done when: correct == 1 且 {spec['metric']} <= {spec['target']}
Direction: {spec['direction']}

## Evidence
见 .opc/research/tasks/R01/evidence/ 中的本次 subagent 调查。主 agent 核对 case 定义、evaluate.py 对应入口和默认模板。
准备好的冻结评价器原件：benchmark-inputs/eval/。必须原字节复制到 .opc/eval/（包括 case.json 和如有的 riscv-outside.sha256）；不得改写或替换评价逻辑。不需要新建评价器。该脚本硬编码 ROOT/.opc/eval 输入路径。
源码来自已准备的原始基线；本次指标未知，等待 preflight；历史准备测量不算本次结果。

## Scope and deliverables
In: {', '.join(spec['editable'])}；{spec['direction']}
Out: 评价器、测试、参考实现、冻结工作负载、其他文件；不得读旧实验冠军/源码缓存/上游答案。
- D1: 仅在上述范围形成的可重放候选补丁 | Git 提交与引擎账本 | 本冻结测试集
- R1: 冻结语义与合法性全部通过，correct == 1 | verification=automated | evaluator=已有
- R2: {spec['metric']} <= {spec['target']} | verification=automated | evaluator=已有
Objective: {spec['metric']} minimize
Adjust if: 出现环境/框架故障时先安全停止并最小修复；不得改变评价器、降低目标或增加预算。

## Open decisions
用户已明确使用当前默认配置：保留 task_template 默认预算 max_attempts=20, max_wall_seconds=7200, max_tokens=2000000, max_stagnation=6, max_consecutive_infra=3；expert timeout=900、designer timeout=1800；workers 均为 Codex，沿用自动生成的 workers.json，不切换 scripted 或 profile。
默认 acceptance min_rel_gain=0.01、repeats=1 保留；目标作为 acceptance.target，正确性作为 constraint。请为 R1/R2 写对应机器 check。
onboard 负责实际合同文件/基线/门；基线用本项目 HEAD，保持 execution_enabled=false。冻结评价器及其依赖需要纳入 evaluator_files；benchmark-inputs/eval/** 同样冻结。只调查/接入，不实施候选优化。
验收用框架 promote --confirm 3 --review codex，不 apply 分支。本次仅测一次，不声称普遍可靠。
'''
    (task/'task-brief.md').write_text(brief,encoding='utf-8')
    return timed(case,'brief-check',[PY,root/'.opc/archa.py','brief-check','-p',root,'--brief','.opc/research/tasks/R01/task-brief.md'])

def handoff(case):
    exp=SUITE/case; root=exp/'project'
    taskpath=root/'.opc/tasks/t-main/revisions/r0001/task.json'
    task=json.loads(taskpath.read_text(encoding='utf-8'))
    manifest=json.loads((exp/'manifest.json').read_text(encoding='utf-8'))
    assert task['budget']==manifest['default_budget'], task['budget']
    assert task['acceptance']['target']==dict(metric=manifest['spec']['metric'],op='<=',value=manifest['spec']['target'])
    for p in (exp/'frozen-eval').rglob('*'):
        if p.is_file():
            assert (root/'.opc/eval'/p.relative_to(exp/'frozen-eval')).read_bytes()==p.read_bytes(), p
    brief=root/'.opc/research/tasks/R01/task-brief.md'
    sha=hashlib.sha256(brief.read_bytes()).hexdigest()
    with (root/'.opc/context/DECISIONS.md').open('a',encoding='utf-8') as f:
        f.write(f'\n## 本次 task → loop 交接\nBrief: .opc/research/tasks/R01/task-brief.md\nSHA-256: {sha}\nTask: t-main\nRevision: r0001\nContract: .opc/tasks/t-main/revisions/r0001/task.json\nBudget: {json.dumps(task["budget"])}\n合同已核对：case 范围/目标/默认预算/冻结评价器原字节一致。执行准备项：启用、提交、check/preflight。其他 blocking items 无。\n')
    mapfile=root/'.opc/research/research-map.md'
    mapfile.write_text(mapfile.read_text(encoding='utf-8').replace('- [ ] R01','- [x] R01').replace('status=active','status=ready-for-onboard')+'\n[已确认简报](tasks/R01/task-brief.md)\n',encoding='utf-8')
    write(exp/'handoff.json',dict(at=time.time(),brief_sha256=sha,task='t-main',revision='r0001',budget=task['budget']))

def enable(case):
    exp=SUITE/case; root=exp/'project'
    p=root/'.opc/project.json'; data=json.loads(p.read_text(encoding='utf-8')); data['execution_enabled']=True; write(p,data)

def commit_integration(case):
    root=SUITE/case/'project'
    subprocess.run(['git','-C',str(root),'add','.opc','benchmark-inputs'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=ArcHa Benchmark','-c','user.email=benchmark@localhost','commit','-qm','ArcHa confirmed skill handoff and frozen evaluation integration'],check=True)

if __name__=='__main__':
    case,phase=sys.argv[1:3]
    root=SUITE/case/'project'
    if phase=='prepare':
        sys.exit(prepare(case))
    if phase=='map':
        map_stage(case); sys.exit(0)
    if phase=='brief':
        sys.exit(brief_stage(case))
    if phase=='handoff':
        handoff(case); sys.exit(0)
    if phase=='enable':
        enable(case); sys.exit(0)
    if phase=='commit':
        commit_integration(case); sys.exit(0)
    if phase=='onboard':
        args=['onboard','-p',root,'--brief','.opc/research/tasks/R01/task-brief.md']
    else:
        args=[phase,'-p',root,'--task','t-main','--revision','r0001']
        if phase=='promote':
            args += ['--confirm','3','--review','codex']
    sys.exit(timed(case,phase,[PY,root/'.opc/archa.py',*args],root))
