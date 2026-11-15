"""Explicit offline example using the same topic files as a real project."""
from pathlib import Path
from ..core.workspace import TopicWorkspace


def create_demo(root: Path):
    root = Path(root)
    workspace = TopicWorkspace(root, 'evidence-demo')
    workspace.initialize(goal='核查已有记录是否支持当前解释，记录适用条件和未解问题。', max_rounds=1)
    (workspace.path / 'STATE.md').write_text('''# Exploration State
STATUS: BUDGET_EXHAUSTED
MAX_ROUNDS: 1

## 已确认事实与适用边界
样本中的三次观测均符合预期；尚不能推及样本之外。

## 未解问题
需要更多环境条件下的观测；当前轮数上限已用尽。
''', encoding='utf-8')
    directory = workspace.path / 'steps/step-01'
    directory.mkdir(exist_ok=True)
    files = {
        'probe.md': '# 探针\n\n核查现有记录是否存在反例；优先查看原件。\n',
        'result.md': '# 结果\n\n三次观测符合预期。范围仅限于所提供的样本。\n',
        '.expert.log': '离线示例：Expert 整理已有记录，生成一个核查问题。\n',
        '.executor.log': '离线示例：Executor 检查样本并记录观测。\n',
        '.expert_finalize.log': '离线示例：收尾消化末轮结果，保留未解问题。\n',
    }
    for name, text in files.items():
        (directory / name).write_text(text, encoding='utf-8')
    return root
