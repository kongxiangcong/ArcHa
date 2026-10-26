"""Render this exercise's existing receipts and ledger as a local HTML report."""
import datetime as dt
import html
import json
import sqlite3
from pathlib import Path

SUITE=Path(__file__).resolve().parents[1]/'experiments/fullflow-20261024'
CASES=['vliw-pack','kernel-opt','ft06-search','riscv-restore']
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def h(x): return html.escape(str(x))
def num(x): return '未知' if x is None else f'{x:,.0f}'
def secs(x): return '未知' if x is None else f'{x/60:.1f} 分'
def table(headers,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+h(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def link(p,label):
    return f'<a href="{h(p.relative_to(SUITE).as_posix())}">{h(label)}</a>'
def parsed(s):
    try: return json.loads(s) if isinstance(s,str) else s
    except (ValueError,TypeError): return None
def agent_case(path):
    return 'ft06-search' if 'ft06' in path else 'riscv-restore' if 'riscv' in path else 'kernel-opt' if 'kernel' in path else 'vliw-pack' if 'vliw' in path or 'diagnose_onboard_access' in path else '跨 case'
def ledger(root):
    p=root/'.opc/local/ledger.sqlite3'
    if not p.exists(): return {}
    with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        return {t:[{k:parsed(v) if k in ('body','metrics','plan','gates','cost','files') else v for k,v in dict(r).items()} for r in db.execute('SELECT * FROM '+t)] for t in ('runs','attempts','champions','charges','events')}
def receipts(exp):
    return [(p,read(p)) for p in sorted((exp/'logs').glob('*.json')) if not p.name.endswith('.started.json')]
def calls(exp,data):
    rows=[]; used=set()
    events=[e for e in data.get('events',[]) if e['kind']=='worker_call']
    charges=list(data.get('charges',[]))
    for request in sorted((exp/'project/.opc/local').rglob('*-request.json')):
        if any(x in request.parts for x in ('worktrees','onboard')) and 'onboard' not in request.parts: continue
        role=request.name.removesuffix('-request.json'); argv=read(request)['argv']
        if role not in ('onboard','expert','designer','reviewer'): continue
        evfile=request.with_name(role+'-events.jsonl')
        evs=[]
        if evfile.exists():
            for line in evfile.read_text(encoding='utf-8',errors='replace').splitlines():
                obj=parsed(line)
                if isinstance(obj,dict): evs.append(obj)
        cid=next((e.get('thread_id') for e in evs if e.get('type')=='thread.started'),None)
        usages=[e['usage'] for e in evs if isinstance(e.get('usage'),dict)]
        tokens=sum((u.get('input_tokens') or 0)+(u.get('output_tokens') or 0) for u in usages) if usages else None
        event=next((e for e in events if e['body'].get('call_id')==cid and cid),None)
        duration=event['body'].get('seconds') if event else None
        charge=next((c for c in charges if c['role']==role and c['attempt_no']==(event or {}).get('attempt_no') and c['id'] not in used),None) if event else None
        if charge: duration=charge['wall_seconds']; used.add(charge['id'])
        ok=event['body'].get('ok') if event else any(e.get('type')=='turn.completed' for e in evs)
        model=argv[argv.index('-m')+1] if '-m' in argv else '未知'
        effort=next((a.split('=',1)[1].strip('"') for a in argv if a.startswith('model_reasoning_effort=')),'未知')
        actual_model=None; actual_effort=None
        if cid:
            sessions=Path('C:/Users/72449/.codex/sessions/2026/10/24')
            for session in sessions.glob('*'+cid+'*.jsonl'):
                for line in session.open(encoding='utf-8',errors='replace'):
                    obj=parsed(line)
                    if isinstance(obj,dict) and obj.get('type')=='turn_context':
                        actual_model=obj.get('payload',{}).get('model'); actual_effort=obj.get('payload',{}).get('effort')
                        if actual_model: break
        rows.append(dict(role=role,attempt_no=(event or {}).get('attempt_no'),call_id=cid,tokens=tokens,seconds=duration,ok=ok,model=actual_model or model,effort=actual_effort or effort,model_source='session turn_context' if actual_model else '启动 argv（后端实际值未报告）',request=str(request.relative_to(SUITE)),stage='接入' if role=='onboard' else '验收' if role=='reviewer' else '迭代'))
    # Failed/retried onboard raw calls are also represented by command receipts.
    onboard_receipts=[(p,r) for p,r in receipts(exp) if r['phase']=='onboard']
    for p,r in onboard_receipts[:-1]:
        out=parsed(p.with_suffix('.stdout.txt').read_text(encoding='utf-8')) or {}
        rows.append(dict(role='onboard',call_id=out.get('call_id') or None,tokens=out.get('tokens') if out.get('call_id') else None,seconds=None,ok=out.get('ok',False),model='未知',effort='未知',model_source='历史启动失败；未生成会话',request=str(p.relative_to(SUITE)),stage='接入重试'))
    return rows

aux_source=read(SUITE/'auxiliary-costs.json') if (SUITE/'auxiliary-costs.json').exists() else {}
overview=[]; stages=[]; callrows=[]; details=[]; allcalls=[]; export=[]; chart=[]; coststages=[]; casecosts=[]
for case in CASES:
    exp=SUITE/case
    if not (exp/'manifest.json').exists():
        overview.append([h(case),'未开始','未知','未执行','未知','未知','未知','未知','未知','未执行']); continue
    manifest=read(exp/'manifest.json'); spec=manifest['spec']; root=exp/'project'; data=ledger(root)
    rs=receipts(exp); runs=data.get('runs',[]); run=runs[-1] if runs else {}; champs=data.get('champions',[])
    baseline=champs[0]['metrics']['values'].get(spec['metric']) if champs else None
    best=champs[-1]['metrics']['values'].get(spec['metric']) if champs else None
    promotion_paths=list((root/'.opc/local').rglob('promotion/*/report.json'))
    promotion=read(promotion_paths[-1]) if promotion_paths else None
    cs=calls(exp,data)
    archived=[]
    for old in sorted(SUITE.glob(case+'-*-failed-*')):
        if (old/'manifest.json').exists(): archived.append(old)
    for old in archived:
        cs.extend(calls(old,ledger(old/'project')))
    allcalls.extend(cs)
    for stage,roleset in [('接入',{'onboard'}),('迭代',{'expert','designer'}),('验收',{'reviewer'})]:
        selected=[c for c in cs if c['role'] in roleset]
        total=sum(c['tokens'] for c in selected if c['tokens'] is not None)
        coststages.append([h(case),stage,num(total) if selected else '未执行',('含未知失败/重试成本' if any(c['tokens'] is None for c in selected) else '有使用回执') if selected else '无调用记录'])
    end=max((r.get('end',0) for _,r in rs),default=manifest['start'])
    complete=run.get('state')=='closed' and promotion is not None
    met=best is not None and best<=spec['target']
    tokens=sum(c['tokens'] for c in cs if c['tokens'] is not None)
    unknown=any(c['tokens'] is None for c in cs)
    gain=(baseline-best)/baseline if baseline and best is not None else None
    if gain is not None:
        chart.append(f'<div class="barrow"><b>{h(case)}</b><div class="track"><i style="width:{max(0,min(100,100*gain)):.2f}%"></i></div><span>{gain:.2%} · {h(spec["metric"])}</span></div>')
    earliest=min([manifest['start']]+[read(old/'manifest.json')['start'] for old in archived])
    case_aux=sum(a['tokens'] for a in aux_source.get('subagents',[]) if agent_case(a['agent_path'])==case and a['tokens'] is not None)
    valid_tries=sum(bool(a.get('outcome')) and a['outcome'] not in ('abandoned','infra') for a in data.get('attempts',[]))
    overview.append([h(case),'完成' if complete else h(run.get('state','接入中/阻塞')),'是' if met else '否' if best is not None else '未知',h(run.get('stop_reason') or '未进入迭代'),num(baseline)+' → '+num(best),f'{gain:.2%}' if gain is not None else '未知',str(len(data.get('attempts',[])))+' / '+str(valid_tries),secs(end-earliest),num(tokens)+(' + 未知' if unknown else ''),('通过' if promotion.get('promotable') else '未通过') if promotion else '未完成'])
    casecosts.append([h(case),num(tokens)+(' + 未知启动成本' if unknown else ''),num(case_aux),num(tokens+case_aux)+' + 未知观察者份额'+(' / 启动成本' if unknown else '')])
    for label,phases in [('map',['map-initialize']),('task/onboard',['brief-check','onboard']),('loop 准备',['check']),('preflight',['preflight']),('自动迭代',['run']),('最终验收',['promote'])]:
        selected=[r for _,r in rs if r['phase'] in phases]
        stagefile=exp/'map-stage.json'
        seconds=(read(stagefile)['end']-read(stagefile)['start']) if label=='map' and stagefile.exists() else sum(r['wall_seconds'] for r in selected) if selected else None
        timing='阶段墙钟' if label=='map' else '命令墙钟之和；不含阶段间人工/调度间隔'
        if label=='task/onboard' and (exp/'handoff.json').exists() and stagefile.exists():
            seconds=read(exp/'handoff.json')['at']-read(stagefile)['end']; timing='阶段墙钟，包含本轮调查/确认/接入及其间等待'
        state='完成' if selected and selected[-1]['returncode']==0 else '失败/阻塞' if selected else '未执行'
        if state=='完成' and any(r['returncode'] for r in selected):state+='（含先前未通过记录）'
        stages.append([h(case),h(label),state,secs(seconds),timing])
    for c in cs:
        callrows.append([h(case),h(c['stage']),h(c['role']),c.get('attempt_no') or '—',h(c['call_id'] or '无会话'),h(c['model']),h(c['effort']),secs(c['seconds']),num(c['tokens']),'成功' if c['ok'] else '失败',link(SUITE/c['request'],'记录')])
    attempts=[]
    for a in data.get('attempts',[]):
        values=(a.get('metrics') or {}).get('values',{})
        attempts.append([a['attempt_no'],h(a.get('outcome') or a['state']),num(values.get(spec['metric'])),h(a.get('reason') or ''),h((a.get('plan') or {}).get('title',''))])
    summary=f'<h2>{h(case)}</h2><p>{h(spec["title"])} · 目标 {h(spec["metric"])} ≤ {spec["target"]}</p>'
    runtimepath=root/'.opc/runtime/manifest.json'
    if runtimepath.exists():
        runtime=read(runtimepath)
        summary+=f'<small>Runtime base {h(runtime.get("source_commit"))} · snapshot {h(runtime.get("snapshot_sha256"))} · 源码与HEAD不同路径 {h(runtime.get("differs_from_head"))}</small>'
    summary+=table(['轮次','结果/接纳','指标','原因','实验标题'],attempts) if attempts else '<p>尚无自动迭代记录。</p>'
    if promotion:
        summary+=f'<p>最终验收 promotable={h(promotion.get("promotable"))}；reviewer={h((promotion.get("reviewer") or {}).get("verdict"))}。</p>'
        summary+='<details><summary>验收细节</summary><pre>'+h(json.dumps({k:promotion.get(k) for k in ('confirm','findings','requirements')},ensure_ascii=False,indent=2))+'</pre></details>'
    summary+='<details><summary>阶段记录与复查入口</summary><ul>'+''.join('<li>'+link(p,r['phase'])+' · '+secs(r['wall_seconds'])+' · exit '+str(r['returncode'])+'</li>' for p,r in rs)+'</ul></details>'
    if archived:
        summary+='<details><summary>保留的失败启动/重开记录</summary>'+table(['目录','阶段','墙钟','退出'],[[h(old.name),h(r['phase']),secs(r['wall_seconds']),r['returncode']] for old in archived for p,r in receipts(old)])+'</details>'
    details.append(summary)
    export.append(dict(case=case,manifest=manifest,ledger=data,calls=cs,commands=[r for _,r in rs],promotion=promotion,end=end))

roles=[]
for role in ('onboard','expert','designer','reviewer'):
    selected=[c for c in allcalls if c['role']==role]
    roles.append([role,len(selected),sum(c['ok'] for c in selected),num(sum(c['tokens'] for c in selected if c['tokens'] is not None))+(' + 未知' if any(c['tokens'] is None for c in selected) else ''),secs(sum(c['seconds'] for c in selected if c['seconds'] is not None))+(' + 未知' if any(c['seconds'] is None for c in selected) else '')])
faults=''.join('<details><summary>'+h(p.stem)+'</summary><pre>'+h(p.read_text(encoding='utf-8'))+'</pre></details>' for p in sorted((SUITE/'faults').glob('*.md')))
aux=aux_source
auxrows=[]; auxcalls=[]
for agent in aux.get('subagents',[]):
    path=agent['agent_path']; kind='故障诊断/修复' if 'diagnose' in path else 'task 调查'
    case=agent_case(path)
    auxrows.append([h(case),h(kind),h(path),h(agent['model']),h(agent['effort']),num(agent['tokens']),secs(agent['completed_wall_seconds'])])
    for i,t in enumerate(agent['turns'],1):
        auxcalls.append([h(case),h(path),i,h(t['model']),h(t['effort']),secs(t['wall_seconds']),num(t['tokens']),h(t['status'])])
main=aux.get('main_observer') or {}
worker_total=sum(c['tokens'] for c in allcalls if c['tokens'] is not None)
aux_total=sum(a['tokens'] for a in aux.get('subagents',[]) if a['tokens'] is not None)
observer_total=main.get('tokens')
generated=dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
full_wall=(generated-dt.datetime.fromisoformat(main['task_start'].replace('Z','+00:00'))).total_seconds() if main.get('task_start') else None
active_outer_wall=main.get('completed_wall_seconds') or 0
if main.get('pending_start'):
    active_outer_wall+=(generated-dt.datetime.fromisoformat(main['pending_start'].replace('Z','+00:00'))).total_seconds()
interaction_gap=full_wall-active_outer_wall if full_wall is not None else None
stops=[c['ledger']['runs'][-1].get('stop_reason') or '' for c in export if c['ledger'].get('runs')]
outcomes=[a.get('outcome') for c in export for a in c['ledger'].get('attempts',[])]
target_count=sum(s=='target_met' for s in stops)
budget_count=sum(s.startswith('budget_exhausted') for s in stops)
capability_count=sum(s.startswith(('expert_exhausted','stagnation')) for s in stops)
body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ArcHa 四案例完整流程实测</title><style>
body{font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif;background:#f4f6fa;color:#182637;margin:0}main{max-width:1500px;margin:auto;padding:36px}h1{font-size:30px}h2{margin-top:40px}p{max-width:1100px}.note,details{background:white;border:1px solid #dce3ed;padding:14px 18px;border-radius:8px;margin:14px 0}.scroll{overflow:auto}table{border-collapse:collapse;background:white;min-width:800px;width:100%;margin:16px 0}th,td{text-align:left;padding:11px;border-bottom:1px solid #e1e6ed;vertical-align:top}th{background:#e6edf7;white-space:nowrap}a{color:#155cbc}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}summary{cursor:pointer;font-weight:600}small{color:#53657c}.barrow{display:grid;grid-template-columns:150px 1fr 230px;gap:15px;align-items:center;margin:12px 0}.track{height:16px;background:#dce5f1;border-radius:4px}.track i{display:block;height:100%;background:#2876b9;border-radius:4px}</style><main>
<h1>ArcHa 四案例完整流程实测</h1>'''
body+='<p>2026-10-24 · Asia/Shanghai · 仅依据本次独立基线实测。流程完成、任务达标和最终可晋升分开判定。</p>'
body+='<div class="note">顺序执行；默认 gpt-6.1-sol / medium，20 attempts / 7200s / 2000000 tokens。自动迭代由 ArcHa 决策，观察者不改候选或评价器。总 token 是接入、搜索及验收的累计使用量，不是金额；未知不得视作零。</div>'
body+='<h2>总览</h2>'+table(['Case','流程','目标完成','停止原因','基线 → 最佳','改善','记录/有效搜索','端到端墙钟','ArcHa worker token','最终验收'],overview)
body+=f'<p>从本轮主观察者开始到报告生成的墙钟：<b>{secs(full_wall)}</b>。已知 ArcHa worker token：<b>{num(worker_total)}</b>；调查/修复 subagent：<b>{num(aux_total)}</b>；主观察者截至用量快照：<b>{num(observer_total)}</b>。所有已知口径合计 <b>{num(worker_total+aux_total+(observer_total or 0))}</b> + 未知项。主观察者尚未结束，最后报告动作与回复不在该快照内；失败启动没有用量回执，完整最终总量未知。</p>'
body+=f'<p>其中主观察者交互活动区间合计 <b>{secs(active_outer_wall)}</b>，两次交互之间的等待空档 <b>{secs(interaction_gap)}</b>。17:22:58 至 21:55:51 的等待“继续”发生在 FT06 preflight 完成之后、run 开始之前；没有自动迭代 worker 在该空档运行。Calendar 墙钟保留这段空档，不把它当成框架执行时间或预算消耗。</p>'
body+='<p>每项相对自身基线的下降幅度（各任务指标不同，不作横向能力排名）：</p>'+''.join(chart)
body+=f'<div class="note">本次停止分类：目标达成 {target_count}；正常预算结束 {budget_count}；搜索枯竭/停滞且未达标 {capability_count}。有效接纳 {outcomes.count("improvement")}，中断无判决记录 {outcomes.count("abandoned")}。环境/部署/流程故障单列在修复表，不当作候选能力不足。尚未触发的类别不等于已经验证可靠；本次也未提供多轮候选失败后反馈有效性的证据。</div>'
body+='<h2>流程表现</h2>'+table(['Case','阶段','状态','耗时','口径'],stages)
body+='<p>Case 端到端从首个留存基线创建到本 case 最后命令结束，含失败重开、调查、等待和调度；各 worker 耗时不能相加冒充端到端。onboard 未返回独立 worker wall 的调用标未知，命令墙钟保留在阶段表。调查/修复 token 后续从会话元数据恢复；主观察者无法准确分配到每个 case 或阶段，单列跨 case 的快照总量。首次未计时准备异常另保留，不能将 case 合计冒充完整全程。</p>'
body+='<h2>Worker 开销</h2>'+table(['角色','调用','成功','Token','已知 worker 耗时'],roles)
onboard_known=sum(c['tokens'] for c in allcalls if c['role']=='onboard' and c['tokens'] is not None)
search_known=sum(c['tokens'] for c in allcalls if c['role'] in ('expert','designer') and c['tokens'] is not None)
review_known=sum(c['tokens'] for c in allcalls if c['role']=='reviewer' and c['tokens'] is not None)
body+=f'<p>本次 ArcHa 已知 token 中：接入 {num(onboard_known)}，自动迭代 {num(search_known)}，最终审核 {num(review_known)}。接入占已知小计 {onboard_known/worker_total:.1%}（不含未知启动成本）。这是本次四个小任务的组织开销观察，不能推断其他任务也有相同比例。合同预算保持原值；接入和外层代理不在搜索 run 账本内，reviewer 在结束后追加到原账本，已按验收拆出。</p>'
body+=table(['Case','ArcHa worker Token','外层调查/修复 Token','Case 已知总量及缺口'],casecosts)
body+=table(['Case','阶段','已知 Token','完整性'],coststages)
body+='<p>上述表仅为 ArcHa 内部 worker；外层调查、修复与主观察者分开计算，避免混淆框架搜索成本与本次测试组织开销。失败和重试调用均保留。</p>'
body+='<p>计量缺口：onboard 没有持久化其 WorkerCall 的独立 wall_seconds，因此该字段未知，不能用命令墙钟冒充。账本 charged_seconds 是 worker/评价器累计量，也不能当作端到端墙钟。无模型启动回执的失败成本未知；不是零。</p>'
body+='<details><summary>按 case、角色、调用展开</summary>'+table(['Case','阶段','角色','尝试','Call ID','模型','推理强度','Worker 耗时','Token','状态','原件'],callrows)+'</details>'
body+='<p>模型优先取本次会话 turn_context，无法读取时以实际 argv 标识请求配置；backend 未报告的实际值未知。缓存 input 是 input 子集，不再次相加。失败但没有 usage receipt 的调用保留“未知”。</p>'
body+='<h2>外层调查、修复与观察开销</h2>'+table(['归属','用途','Agent','实际模型','推理强度','Token','完成调用墙钟之和'],auxrows)
body+='<details><summary>Subagent 各次调用</summary>'+table(['归属','Agent','调用','模型','推理强度','墙钟','Token','状态'],auxcalls)+'</details>'
body+=f'<p>主观察者：{h(main.get("model","未知"))} / {h(main.get("effort","未知"))}；用量快照 {h(main.get("usage_at","未知"))}；input={num((main.get("usage") or {}).get("input_tokens"))}，其中 cached input={num((main.get("usage") or {}).get("cached_input_tokens"))}；output={num((main.get("usage") or {}).get("output_tokens"))}。不把 cached input 或 reasoning output 再次加到总数。子代理按每个会话的累计 input+output 只计一次；逐次表是差分，不能再次加到会话总数。<a href="auxiliary-costs.json">脱敏用量元数据</a>。</p>'
body+=''.join(details)+'<h2>故障、修复与重开</h2>'
body+=table(['问题','最小修复','恢复方式','额外成本'],[
 ['Python 子进程权限下降；onboard 启动失败','subagent 将 venv python.exe 的 Low 标签改为 Medium，恢复原 DACL；字节哈希不变','无运行中控制器时修复；同一新基线重试 onboard','诊断约 16:46–16:55；标签修复与验证命令约 2.10s；完整修复/补记调用 token 见辅助开销表。区间与内部命令不重复累加'],
 ['全局技能部署旧 runtime，缺默认 worker 配置','使用仓库当前 archa-map initializer 部署','保留旧失败目录，新独立原始基线重开','全部启动 receipt 保留，未生成模型会话的 token 未知'],
 ['观察者准备脚本 archive 格式与初始化顺序错误','显式 zip、工作区 TMP、初始化成功后推进 map','保留初始化失败目录；新目录完成初始化','首次异常外层 1.956s；partial-layout 重试外层 6.014s；其余见 receipt。不可得项未知']])
body+=table(['问题','最小环境修复','恢复/预算','成本'],[['FT06 onboard 子 worker 解析到系统 Python，缺 simanneal；pip/TEMP 重试失败','诊断 subagent 验证 PATH 前缀既有 venv 即可；清除 PYTHONPATH，不安装新依赖','onboard 已结束后修正启动环境；原基线首次 run，不重开或重置预算','onboard 内重试含在 957,212 tokens / 299.69s；无模型差分 8.579s，外层 9.916s；诊断 agent token 另列']])
body+=table(['问题','最小修复','恢复/状态','额外成本'],[['FT06 expert 完成后，designer checkout 遇 Windows 路径过长','subagent 设置该项目 local Git core.longpaths=true；同深度 checkout red→green，字节与 HEAD 一致','控制器已退出 blocked 后修复；普通 run 恢复 run-d875c1157f3d。a1 abandoned、无候选判决，原成本保留；未重开预算','中断前 expert 80,616 tokens 已包含迭代成本；诊断探针 4.074s（外层嵌套不重复加）；诊断模型 token 另列']])
body+=faults
body+='<p>早期诊断文档中的 token 未知是当时的可观测状态；本报告辅助表以之后恢复的会话使用回执为准，未修改原始历史记录。</p>'
body+='<p>本报告只支持当前四个任务、本次工作负载与本机环境的观察，不据此推断框架普遍可靠。完整原件留在各实验目录、SQLite 账本与日志；HTML 为只读汇总。</p><small>生成时间 '+h(dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat())+'</small></main></html>'
(SUITE/'report.html').write_text(body,encoding='utf-8')
(SUITE/'results.json').write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding='utf-8')
print(SUITE/'report.html')
