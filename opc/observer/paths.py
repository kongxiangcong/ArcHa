"""Resolve an explicit topic collection or single topic without mutation."""
from pathlib import Path


def resolve_topics(directory):
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError('topic path must be an existing directory')
    collection = directory if directory.name == 'topics' and directory.parent.name == '.archa' else directory.parent
    if collection.name != 'topics' or collection.parent.name != '.archa':
        raise ValueError('select .archa/topics or one topic within it')
    return collection.parent.parent, directory
