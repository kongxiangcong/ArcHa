"""Export usage/timestamps only; never export session messages or reasoning."""
import datetime as dt
import json
from pathlib import Path

SUITE=Path(__file__).resolve().parents[1]/'experiments/fullflow-20261024'
PARENT='01a16d12-e1a7-7ff1-8d2f-a9fb581eeddd'
def epoch(s):return dt.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
rows=[]; main=None
for f in Path('C:/Users/72449/.codex/sessions/2026/10/24').glob('*.jsonl'):
    with f.open(encoding='utf-8',errors='replace') as stream:
        first=stream.readline()
        try:meta=json.loads(first).get('payload',{})
        except ValueError:continue
        source=meta.get('source',{})
        spawn=(source.get('subagent',{}).get('thread_spawn',{}) if isinstance(source,dict) else {})
        is_main=meta.get('id')==PARENT
        if not is_main and spawn.get('parent_thread_id')!=PARENT:continue
        usage={}; last_usage_at=None; model=None; effort=None; start=None; before=0; turns=[]; task_start=None
        for line in stream:
            try:e=json.loads(line)
            except ValueError:continue
            payload=e.get('payload',{}); typ=e.get('type'); when=e.get('timestamp')
            if typ=='turn_context':model=payload.get('model'); effort=payload.get('effort')
            if typ!='event_msg':continue
            event=payload.get('type')
            total=(usage.get('input_tokens',0)+usage.get('output_tokens',0))
            if event=='task_started':
                start=when; before=total
                if task_start is None:task_start=when
            elif event=='token_count' and payload.get('info'):
                usage=payload['info'].get('total_token_usage') or usage; last_usage_at=when
            elif event=='task_complete' and start:
                current=usage.get('input_tokens',0)+usage.get('output_tokens',0)
                turns.append(dict(start=start,end=when,wall_seconds=epoch(when)-epoch(start),tokens=current-before,status='completed',model=model,effort=effort))
                start=None
        item=dict(id=meta['id'],agent_path=spawn.get('agent_path','/root'),model=model,effort=effort,usage=usage,tokens=usage.get('input_tokens',0)+usage.get('output_tokens',0) if usage else None,usage_at=last_usage_at,task_start=task_start,turns=turns,completed_wall_seconds=sum(t['wall_seconds'] for t in turns) if turns else None,pending=start is not None,pending_start=start)
        if is_main:main=item
        else:rows.append(item)
out=dict(parent=PARENT,main_observer=main,subagents=rows,semantics='input+output; cached input and reasoning are subsets, not added again. Session cumulative totals are used once per agent; turns are differences, not added a second time. Main observer is an in-progress snapshot, not a final receipt.')
(SUITE/'auxiliary-costs.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({r['agent_path']:dict(tokens=r['tokens'],seconds=r['completed_wall_seconds'],turns=len(r['turns'])) for r in rows},ensure_ascii=False))
