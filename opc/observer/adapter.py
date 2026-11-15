"""Read-only projection of authoritative topic documents and runtime logs."""
import codecs
import os
from pathlib import Path

from ..core.workspace import TopicWorkspace


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
                    for role in ('expert', 'executor', 'expert_finalize')
                    if (directory / f'.{role}.log').is_file()]
            rounds.append(dict(number=number, completed=(directory / 'result.md').exists(),
                               materials=materials, logs=logs))
        pending = next((item for item in rounds if item['number'] == value['current_round'] and not item['completed']), None)
        current_probe = next((item for item in pending['materials'] if item['name'] == 'probe.md'), None) if pending else None
        return dict(**value, current_probe=current_probe, rounds=sorted(rounds, key=lambda item: item['number']),
                    materials=[self.material(workspace.path / name) for name in ('GOAL.md', 'STATE.md', 'PROGRESS_LOG.md')
                               if (workspace.path / name).is_file()])

    def material(self, path):
        return dict(name=path.name, path=path.relative_to(self.root).as_posix())

    def content(self, path, offset=0, limit=262144):
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ObserverError(403, 'outside_material_roots', 'Material must stay within the project')
        relative = candidate.relative_to(self.root)
        if relative.parts[0] == '.git' or (relative.parts[0] == '.archa' and not candidate.is_relative_to(self.topics)):
            raise ObserverError(403, 'outside_material_roots', 'Private runtime files are not materials')
        if relative.parts[0] == '.archa':
            hidden = [part for part in relative.parts[1:] if part.startswith('.')]
            if hidden and (len(hidden) != 1 or hidden[0] not in {'.expert.log', '.executor.log', '.expert_finalize.log'}):
                raise ObserverError(403, 'outside_material_roots', 'Unpublished runtime files are not materials')
        if not candidate.is_file():
            raise ObserverError(404, 'not_found', 'Material not found')
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
