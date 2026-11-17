"""Read-only projection of authoritative topic documents and runtime logs."""
import codecs
import json
import os
import re
from pathlib import Path

from ..core.workspace import TopicWorkspace


def excerpt(text, title=""):
    body = " ".join(re.sub(r"^\s*#{1,6}\s+", "", line).strip()
                    for line in text.splitlines()
                    if line.strip() and not re.match(r"^(STATUS|MAX_ROUNDS):", line))
    body = " ".join(body.split())
    return dict(title=title[:120] + ("…" if len(title) > 120 else ""),
                title_truncated=len(title) > 120,
                text=body[:240] + ("…" if len(body) > 240 else ""),
                truncated=len(body) > 240, empty=not body)


def reading(path):
    text = path.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^#{1,6} +(.+)$", text, re.M))
    title = headings[0][1] if headings else path.name
    body = text[headings[0].end():] if headings else text
    sections = []
    for index, heading in enumerate(headings):
        if heading[0].startswith("# "):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections.append(excerpt(text[heading.end():end], heading[1]))
    if path.name == "GOAL.md":
        objective = next((part for part in sections if part['title'].lower() == 'objective'), None)
        if objective is not None:
            return dict(excerpt=objective)
    return dict(excerpt=excerpt(body, title), **(dict(sections=sections) if path.name == 'STATE.md' else {}))


class ObserverError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class ObserverAdapter:
    def __init__(self, root, demo=False, *, topics=None):
        self.root = Path(root).resolve()
        self.demo = demo
        self.topics = Path(topics).resolve() if topics else self.root / '.archa/topics'
        base = self.root / '.archa/topics'
        if self.topics != base and self.topics.parent != base:
            raise ValueError('topics must be .archa/topics or one topic within it')

    def workspace(self, topic):
        workspace = TopicWorkspace(self.root, topic)
        if self.topics != self.root / '.archa/topics' and workspace.path != self.topics:
            raise ObserverError(404, 'not_found', 'Topic outside selected directory')
        if not workspace.path.is_dir():
            raise ObserverError(404, 'not_found', 'Topic not found')
        return workspace

    def overview(self):
        paths = sorted(self.topics.iterdir()) if self.topics == self.root / '.archa/topics' and self.topics.exists() else [self.topics]
        topics = []
        for path in paths:
            if not path.is_dir():
                continue
            try:
                topics.append(self.workspace(path.name).status())
            except (ValueError, OSError) as exc:
                topics.append({'topic': path.name, 'error': str(exc)})
        return dict(project=self.root.name, demo=self.demo, topics=topics)

    def detail(self, topic):
        workspace = self.workspace(topic)
        value = workspace.status()
        rounds = []
        for directory in sorted((workspace.path / 'steps').iterdir()):
            number = int(directory.name[5:])
            materials = [self.material(path) for path in sorted(directory.iterdir())
                         if path.is_file() and not path.name.startswith('.')]
            logs = [{'role': role, **self.material(directory / f'.{role}.log')}
                    for role in ('expert', 'executor', 'expert_finalize', 'expert_revise')
                    if (directory / f'.{role}.log').is_file()]
            rounds.append(dict(number=number, completed=(directory / 'result.md').exists(),
                               materials=materials, logs=logs))
        pending = next((item for item in rounds if item['number'] == value['current_round'] and not item['completed']), None)
        current_probe = next((item for item in pending['materials'] if item['name'] == 'probe.md'), None) if pending else None
        return dict(**value, current_probe=current_probe, rounds=sorted(rounds, key=lambda item: item['number']),
                    materials=[self.material(workspace.path / name) for name in ('GOAL.md', 'STATE.md', 'PROGRESS_LOG.md')
                               if (workspace.path / name).is_file()])

    def material(self, path):
        return dict(name=path.name, path=path.relative_to(self.root).as_posix(),
                    **(reading(self.readable_path(path.relative_to(self.root))) if path.suffix.lower() == '.md' else {}))

    def readable_path(self, path, *, events=False):
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ObserverError(403, 'outside_material_roots', 'Material must stay within the project')
        relative = candidate.relative_to(self.root)
        if relative.parts[0] == '.git' or (relative.parts[0] == '.archa' and not candidate.is_relative_to(self.topics)):
            raise ObserverError(403, 'outside_material_roots', 'Private runtime files are not materials')
        if relative.parts[0] == '.archa':
            hidden = [part for part in relative.parts[1:] if part.startswith('.')]
            allowed = {f'.{role}.events.jsonl' for role in ('expert', 'executor', 'expert_revise', 'expert_finalize')} if events else set()
            if hidden and (len(hidden) != 1 or hidden[0] not in allowed | {'.expert.log', '.executor.log', '.expert_finalize.log', '.expert_revise.log'}):
                raise ObserverError(403, 'outside_material_roots', 'Unpublished runtime files are not materials')
        if not candidate.is_file():
            raise ObserverError(404, 'not_found', 'Material not found')
        return candidate

    def events(self, topic, step, role, after_seq=0, stream=None):
        workspace = self.workspace(topic)
        directory = workspace.path / 'steps' / f'step-{step:02d}'
        if step < 1 or not directory.is_dir():
            raise ObserverError(404, 'not_found', 'Round not found')
        path = directory / f'.{role}.events.jsonl'
        diagnostic = None
        log = directory / f'.{role}.log'
        if log.exists():
            log = self.readable_path(log.relative_to(self.root))
            with log.open('rb') as source:
                head = source.read(8192)
                source.seek(max(0, os.fstat(source.fileno()).st_size - 8192))
                tail = source.read(8192)
            diagnostics = [line for line in (head + tail).decode('utf-8', errors='replace').splitlines()
                           if line.startswith('Telemetry incomplete:')]
            diagnostic = diagnostics[-1] if diagnostics else None
        current, selected, more, cursor = None, [], False, 0
        if path.exists():
            path = self.readable_path(path.relative_to(self.root), events=True)
            # One open descriptor pins one invocation across atomic replacement.
            with path.open('rb') as source:
                for raw in source:
                    if not raw.endswith(b'\n'):
                        break
                    try:
                        event = json.loads(raw)
                        if set(event) != {'seq', 'ts', 'kind', 'title', 'status', 'detail'} or not isinstance(event['seq'], int):
                            raise ValueError('invalid event fields')
                        if current is None:
                            if event['seq'] != 1 or event['title'] != 'started':
                                raise ValueError('missing start event')
                            current = event['ts']
                            cursor = after_seq if stream == current else 0
                        if event['seq'] <= cursor:
                            continue
                        if len(selected) == 200:
                            more = True
                            break
                        selected.append(event)
                    except (ValueError, TypeError, UnicodeDecodeError) as exc:
                        diagnostic = f'Trace incomplete: {path.name}: {exc}'
                        break
        return dict(stream=current, reset=stream != current, events=selected,
                    next_seq=selected[-1]['seq'] if selected else cursor, more=more,
                    diagnostic=diagnostic)

    def content(self, path, offset=0, limit=262144):
        candidate = self.readable_path(path)
        relative = candidate.relative_to(self.root)
        with candidate.open('rb') as stream:
            if offset > os.fstat(stream.fileno()).st_size:
                offset = 0  # A new invocation can replace this role's log.
            stream.seek(offset)
            chunk = stream.read(limit)
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            text = decoder.decode(chunk, final=False)
            while decoder.getstate()[0]:
                extra = stream.read(1)
                if not extra:
                    break
                chunk += extra
                text += decoder.decode(extra, final=False)
            more = bool(stream.read(1))
        pending = decoder.getstate()[0]
        return dict(path=relative.as_posix(), text=text,
                    offset=offset, next_offset=offset + len(chunk) - len(pending), more=more or bool(pending))
