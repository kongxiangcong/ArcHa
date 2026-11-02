"""Resolve an explicit research directory without treating it as a project."""
from pathlib import Path


def resolve_topics(directory):
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError('专题路径必须是已有 topics 集合或单个专题目录')
    for project in directory.parents:
        if (project / '.opc/project.json').is_file():
            topics = project / '.opc/research/topics'
            if directory == topics or directory.parent == topics:
                return project, directory
            raise ValueError('请选择 .opc/research/topics 或其中一个专题目录，不能使用任务、运行或文件路径')
    raise ValueError('未找到祖先工程的 .opc/project.json；工作台不会初始化工程')
