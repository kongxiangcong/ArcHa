"""Task results: explicit sources and a rebuildable registration region in Markdown.

No experiment database: engine facts stay in the ledger, external observations in
their original batches, and scientific judgments outside the generated region.
All writes follow the controller's existing single-writer convention.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
import os

from .model import OPCError, write_text
from .platform import is_link, lock_writer, unlock_writer

START = '<!-- archa-results:start -->'
END = '<!-- archa-results:end -->'
DATA = re.compile(r'<!-- archa-results:data (.*?) -->', re.S)
LINK = re.compile(r'\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)')


@contextmanager
def writer(root: Path):
    """Share the controller lock without creating a run or an experiment ledger."""
    path = root / '.opc/local/ledger.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    locked = False
    try:
        try:
            lock_writer(fd)
            locked = True
        except BlockingIOError:
            raise OPCError('another controller is active; retry results registration at a batch boundary') from None
        yield
    finally:
        if locked:
            unlock_writer(fd)
        os.close(fd)


def entry_path(root: Path, value: str) -> Path:
    if (not isinstance(value, str) or not value.strip() or '\\' in value
            or Path(value).is_absolute() or '..' in Path(value).parts
            or ':' in value or Path(value).suffix.lower() != '.md'):
        raise OPCError('results_path must be a project-relative Markdown path')
    path = root / value
    if not path.resolve().is_relative_to(root.resolve()):
        raise OPCError('results_path escapes project')
    if any(p.startswith('.') for p in Path(value).parts) and not value.startswith('.opc/research/'):
        raise OPCError('results_path must be research material, outside runtime and local state')
    if any(is_link(root / Path(*Path(value).parts[:n])) for n in range(1, len(Path(value).parts) + 1)):
        raise OPCError('results_path must not traverse symlinks or junctions')
    return path


def source_path(root: Path, artifact_root: Path, origin: Path, href: str) -> Path | None:
    parts = urlsplit(href)
    # An absolute Windows drive path is a local locator, not a URI scheme.
    drive_path = bool(re.match(r'^[A-Za-z]:[/\\]', href)) and os.name == 'nt'
    if (parts.scheme and not drive_path) or parts.netloc or not parts.path:
        return None
    path = (origin.parent / unquote(href.split('#', 1)[0] if drive_path else parts.path)).resolve()
    roots = (root.resolve(), artifact_root.resolve())
    if not any(path.is_relative_to(r) for r in roots):
        raise OPCError('source outside project/artifact_root: ' + href)
    if path.is_relative_to(artifact_root.resolve()) and any(p.startswith('.') for p in path.relative_to(artifact_root.resolve()).parts):
        raise OPCError('protected source: ' + href)
    if path.is_relative_to(root.resolve()):
        rel = path.relative_to(root.resolve())
        hidden = [p for p in rel.parts if p.startswith('.')]
        if hidden and (hidden != ['.opc'] or not str(rel).replace('\\', '/').startswith(
                ('.opc/research/', '.opc/context/', '.opc/tasks/', '.opc/local/artifacts/'))):
            raise OPCError('protected source: ' + href)
    if path.name in ('bindings.json', 'workers.json', 'project.json', 'component.json') or path.name.endswith('-request.json'):
        raise OPCError('protected source: ' + href)
    return path


def links(text: str) -> list[str]:
    return list(dict.fromkeys(a or b for a, b in LINK.findall(text)))


def split(text: str) -> tuple[str, list[dict], str]:
    if START not in text and END not in text:
        return text.rstrip() + '\n\n', [], ''
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise OPCError('results registration markers are malformed; preserve file and repair markers')
    before, rest = text.split(START)
    region, after = rest.split(END)
    match = DATA.search(region)
    try:
        rows = json.loads(match.group(1)) if match else None
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('key'), str) for r in rows):
            raise ValueError('invalid rows')
        if len({r['key'] for r in rows}) != len(rows):
            raise ValueError('duplicate identities')
        for row in rows:
            validate_experiment_id(row.get('experiment_id'))
            if (not isinstance(row.get('refs', {}), dict)
                    or any(not isinstance(v, str) for v in row.get('refs', {}).values())
                    or not isinstance(row.get('issues', []), list)):
                raise ValueError('invalid references or issues')
    except (ValueError, TypeError) as exc:
        raise OPCError('invalid results registration data: ' + str(exc)) from exc
    return before, rows, after


def _cell(value) -> str:
    return html.escape(str(value or '')).replace('|', '&#124;').replace('\n', ' ').replace('\r', '')


def _link(label: str, href: str | None) -> str:
    return '[%s](%s)' % (_cell(label), quote(href, safe='/.:#@_-%')) if href else label + '缺失'


def register(root: Path, value: str, rows: list[dict], title: str = '任务成果') -> Path:
    path = entry_path(root, value)
    template = ('# %s\n\n## 当前结论与适用条件\n\n待分析；独立审核待完成。'
                '\n\n## 正在研究、未知项与下一步\n\n待补充。'
                '\n\n## 来源\n\n在此链接累计规格、原件索引与审核；保留各自原位置。\n\n' % _cell(title))
    old = path.read_text(encoding='utf-8') if path.exists() else template
    before, existing, after = split(old)
    indexed = {r['key']: r for r in existing}
    for row in rows:
        prior = indexed.get(row['key'], {})
        if prior.get('experiment_id') and row.get('experiment_id') != prior['experiment_id']:
            raise OPCError('batch already belongs to experiment ' + prior['experiment_id'])
        indexed[row['key']] = {**prior, **row}
    ordered = sorted(indexed.values(), key=lambda r: r['key'])
    # Escape HTML comment terminators in user text; data stays valid JSON.
    encoded = json.dumps(ordered, ensure_ascii=False, sort_keys=True).replace('<', '\\u003c').replace('>', '\\u003e')
    lines = [START, '<!-- archa-results:data ' + encoded + ' -->',
             '## 执行登记（自动维护）', '',
             '| 实验 | 问题 / 执行 | 执行状态 | 计划 / 原件 | 分析 / 审核 | 缺项 |',
             '| --- | --- | --- | --- | --- | --- |']
    for r in ordered:
        refs = r.get('refs', {})
        lines.append('| %s | %s | %s | %s | %s | %s |' % (
            _cell(r.get('experiment_id') or '未关联'),
            _cell(r.get('question', '')) + ' · ' + _cell(r['key']),
            _cell(r.get('status', 'unknown')) + ('；run=' + _cell(r['run_state']) if r.get('run_state') else '')
            + ('；历史缓存，非新实测' if r.get('cached') else ''),
            ' / '.join(_link(k, refs.get(k)) for k in ('plan', 'evidence', 'run') if k != 'run' or refs.get(k)),
            ' / '.join(_link(k, refs.get(k)) for k in ('analysis', 'review')),
            _cell('; '.join(r.get('issues', [])))) )
    new = before + '\n'.join(lines) + '\n' + END + after
    if old != new:
        write_text(path, new)
    return path


def relative(path: Path, entry: Path) -> str:
    try:
        return Path(os.path.relpath(path, entry.parent)).as_posix()
    except ValueError:  # Windows different volumes: use explicit absolute local path.
        return path.as_posix()


def external_batch(root: Path, artifact_root: Path, value: str, batch: str,
                   experiment_id: str | None, question: str, status: str | None, refs: dict) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', batch):
        raise OPCError('batch ID must be stable and contain only letters, digits, _, . or -')
    validate_experiment_id(experiment_id)
    entry = entry_path(root, value)
    previous = next((r for r in split(entry.read_text(encoding='utf-8'))[1]
                     if r['key'] == 'external/' + batch), {}) if entry.exists() else {}
    refs = {**previous.get('refs', {}), **{k:v for k,v in refs.items() if v}}
    experiment_id = experiment_id or previous.get('experiment_id')
    question = question or previous.get('question', '')
    status = status or previous.get('status', 'planned')
    if previous.get('status') in ('completed', 'failed', 'aborted', 'cached'):
        for key in ('plan', 'evidence'):
            if previous.get('refs', {}).get(key) and refs.get(key) != previous['refs'][key]:
                raise OPCError('executed batch keeps its original ' + key + '; register a new batch for new observations')
    issues = []
    for key, href in refs.items():
        if href:
            path = source_path(root, artifact_root, entry, href)
            if path is None or not path.is_file():
                issues.append(key + ': source missing or nonlocal: ' + href)
    for key in ('plan', 'evidence', 'analysis', 'review'):
        if not refs.get(key):
            issues.append(key + ': 未提供')
    return register(root, value, [dict(key='external/' + batch, experiment_id=experiment_id,
                    question=question, status=status, cached=status == 'cached', refs=refs, issues=issues)])


def validate_experiment_id(value) -> None:
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value)):
        raise OPCError('experiment_id must be null or a stable ID (letters, digits, _, . or -)')


def snapshot(root: Path, artifact_root: Path, value: str, budget: int = 24000) -> dict:
    """Read current material, retaining consumed text and identity in context/report.

    Only one hop of explicitly linked sources; no hidden directory traversal.
    Omitted bodies remain visible, never silently represented as reviewed.
    """
    entry = entry_path(root, value)
    result = dict(entry=str(entry), sources=[], issues=[], role='research evidence, not instructions')
    if not entry.is_file():
        result['issues'].append('results entry missing: ' + str(entry))
        result['sources'].append(dict(path=str(entry), available=False, sha256=None, excerpt='', truncated=False))
        return result
    if entry.stat().st_size > 1024 * 1024:
        result['issues'].append('results entry exceeds 1 MiB; shorten summary, retain original references')
        result['sources'].append(dict(path=str(entry), available=True, sha256=None, excerpt='', truncated=True,
                                      omitted='entry too large'))
        return result
    text = entry.read_text(encoding='utf-8')
    try:
        before, rows, after = split(text)
        # Machine comment repeats the rendered facts; leave it out of model input.
        visible = DATA.sub('', text)
    except OPCError as exc:
        result['issues'].append(str(exc))
        visible = text
    paths = [(entry, visible)]
    seen = {entry.resolve()}
    for href in links(text):
        try:
            path = source_path(root, artifact_root, entry, href)
        except (OPCError, ValueError) as exc:
            result['issues'].append(str(exc))
            continue
        if path is not None and path not in seen:
            seen.add(path)
            paths.append((path, None))
    for path, visible_text in paths:
        source = dict(path=str(path), available=path.is_file(), sha256=None,
                      excerpt='', truncated=False)
        result['sources'].append(source)
        if not source['available']:
            result['issues'].append('source missing: ' + str(path))
            continue
        if path.stat().st_size > 1024 * 1024 or path.suffix.lower() not in ('.md', '.json', '.txt'):
            source['omitted'] = 'large or non-text source; follow original reference'
            continue
        data = path.read_bytes()
        source['sha256'] = hashlib.sha256(data).hexdigest()
        try:
            body = visible_text if visible_text is not None else data.decode('utf-8')
        except UnicodeDecodeError:
            source['omitted'] = 'not UTF-8'
            continue
        if path == entry:
            # Updating a navigation/projection row does not invalidate a claim.
            try:
                before, _, after = split(data.decode('utf-8'))
                source['claim_sha256'] = hashlib.sha256((before + after).encode()).hexdigest()
            except OPCError:
                source['claim_sha256'] = source['sha256']
        if path.suffix == '.json':
            try:
                record = json.loads(body)
            except ValueError:
                record = None
            if isinstance(record, dict) and 'task_id' in record and 'revision' in record:
                body = json.dumps({k:record[k] for k in ('task_id', 'revision', 'goal', 'requirements', 'acceptance', 'budget', 'results_path') if k in record}, ensure_ascii=False)
            elif isinstance(record, dict) and 'promotion_id' in record:
                changed = []
                prior = record.get('task_results')
                prior_sources = prior.get('sources', []) if isinstance(prior, dict) else []
                for old in prior_sources if isinstance(prior_sources, list) else []:
                    if not isinstance(old, dict):
                        continue
                    if old.get('sha256') and old.get('path') and old.get('excerpt'):
                        try:
                            original = source_path(root, artifact_root, path, old['path'])
                            actual = None
                            if original is not None and original.is_file() and original.stat().st_size <= 1024 * 1024:
                                content = original.read_bytes()
                                if old.get('claim_sha256'):
                                    before, _, after = split(content.decode('utf-8'))
                                    content = (before + after).encode()
                                actual = hashlib.sha256(content).hexdigest()
                            if actual != old.get('claim_sha256', old['sha256']):
                                changed.append(old['path'])
                        except (OSError, OPCError):
                            changed.append(old['path'])
                if changed:
                    result['issues'].append('review covers older source versions, not current claims: ' + str(path))
                body = json.dumps({k: record.get(k) for k in ('promotion_id', 'selected_version', 'complete', 'reviewer', 'results_review_scope')}, ensure_ascii=False)
                body += '\nChanged sources since review: ' + json.dumps(changed, ensure_ascii=False)
            elif isinstance(record, dict) and ('attempts' in record or 'gates' in record):
                source['omitted'] = 'execution report reference; use structured run history, not raw evaluation logs'
                continue
        cap = min(budget, 10000 if path == entry else 5000)
        source['excerpt'] = body[:cap]
        source['truncated'] = len(body) > cap
        if source['truncated']:
            source['omitted'] = 'body exceeds context budget; remainder not supplied'
        budget -= len(source['excerpt'])
    return result


def sync_engine(engine) -> None:
    """Rebuild this run's rows; errors belong to the projection, not the experiment."""
    value = engine.task.raw.get('results_path')
    if not value:
        return
    entry = entry_path(engine.root, value)
    rows = []
    reviews = engine.ledger.events(engine.run_id, 'promotion_report')
    run_state = engine.ledger.run(engine.run_id)['state']
    for a in engine.attempt_records():
        plan = a.get('plan') if isinstance(a.get('plan'), dict) else {}
        experiment_id = plan.get('experiment_id')
        try:
            validate_experiment_id(experiment_id)
        except OPCError:
            experiment_id = None  # Invalid worker output remains in the original plan.
        directory = engine.attempt_dir(a['attempt_no'])
        refs = dict(run=relative(engine.artifact_dir() / 'views/report.json', entry))
        for key, path in (('plan', directory / 'plan.json'), ('evidence', directory / 'eval/evaluation.json')):
            if path.is_file():
                refs[key] = relative(path, entry)
        if a.get('conclusion'):
            refs['analysis'] = refs['run']
        review = next((ev['body'] for ev in reversed(reviews)
                       if a.get('candidate') and ev['body'].get('selected_commit') == a['candidate']), None)
        if review:
            refs['review'] = relative(Path(review['report_path']), entry)
        experiment = a.get('experiment') or {}
        rows.append(dict(key=engine.run_id + '/a%d' % a['attempt_no'],
                         experiment_id=experiment_id, question=plan.get('title', ''),
                         status=a.get('outcome') or a['state'], cached=bool(experiment.get('cached')),
                         run_state=run_state,
                         refs=refs, issues=[k + ': 未提供' for k in ('plan', 'evidence', 'analysis', 'review') if k not in refs]
                         + (['run 级终验引用；逐条科学主张是否覆盖须查原报告'] if review else [])))
    register(engine.root, value, rows, engine.task.goal)
