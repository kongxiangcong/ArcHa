> 已被 [ArcHa 端到端重构方案](archa-refactor-plan.md) 替代。本文保留为历史草案，不再作为开发依据。

调整后的工作完全围绕“删减旧防御代码 + 落地轻量内核与通用 Worker”展开，分为四个干净的步骤：

1. **P0：重写通用无绑定 Worker 适配层（`opc/adapters/`）**

   * 删除 `dsh-tool-boundary.mjs` 和 `opc/core/tool_boundary.py`。

     kongxiangcong/archa

   * 重写 `opc/adapters/worker.py`（合并精简 `codex.py` 与 `dsh.py`），实现基于命令模板 + Markdown 文件读写（+ `stdout` 兜底）的无状态调用接口，彻底解耦 Codex CLI 与 DeepSeek Harness。

     kongxiangcong/archa+ 1

2. **P1：重写轻量化调度内核与三文件工作区（`opc/core/`）**

   * 删除 `accept.py`、`promote.py`、`ledger.py`、`results.py`、`onboard.py`、`brief.py` 中的冻结、哈希、Claim 账本和 Repair Loop 逻辑。

     kongxiangcong/archa

   * 重写 `opc/core/engine.py` 与 `workspace.py`，实现基于 `GOAL.md`、`STATE.md`、`steps/step-XX/{probe.md, result.md}` 的双角色极简循环（支持随时中断、人工直接编辑 `.md` 介入后无缝继续）。

3. **P2：重写内化苏格拉底方法论的 `Expert` / `Executor` Prompt（`opc/adapters/prompts.py`）**

   * 移除原 `prompts.py` 中的 `Reviewer` 角色、JSON Schema 强制约束与 `deliverables` 预声明规则。

     kongxiangcong/archa+ 1

   * 写入基于《PIM架构探索讨论.md》提炼的 `Expert`（认知表维护 + 关键路径剪枝 + 单步最小探针）与 `Executor`（源码/已有 Trace 优先 + 干预生效核验 + 事实摘要）提示词模板。

     PIM架构探索讨论.md+ 1

4. **P3：简化 CLI 与技能入口（`opc/cli.py` & `skills/`）**

   * 将原有的 `archa-map -> archa-task -> onboard -> archa-loop` 繁琐链路简化为直接初始化 `GOAL.md` 与 `STATE.md` 并启动 `opc run` 迭代；同步简化 `opc/observer/` 使其直接读取 `STATE.md` 与 `steps/` 目录展示进度。

     kongxiangcong/archa+ 1
以下为 **ArcHa P0（通用无绑定 Worker 适配层）与 P1（轻量化调度内核与三文件工作区）** 的详细开发方案文档。本方案遵循“推倒重写（Clean-Slate）、零哈希校验、零 JSON 账本、零工具拦截、文件即状态”的设计准则，可直接作为代码重构的实施蓝本。

---

## 一、 代码清理与模块重构清单（Clean-Slate 清单）

在启动 P0 和 P1 编码前，首先对现有 `opc/` 目录进行彻底减法，直接移除 S1–S4 引入的防御性审计、契约冻结与工具拦截模块：

| 操作类型 | 模块 / 文件路径 | 处置原因与重构说明 |
| --- | --- | --- |
| **直接删除** | `opc/core/tool_boundary.py`<br>

<br>`opc/adapters/dsh-tool-boundary.mjs` | 彻底移除对 Worker 读取源码、查反汇编、跑模拟器的路径与命令拦截。

 |
| **直接删除** | `opc/core/ledger.py`<br>

<br>`opc/core/results.py`<br>

<br>`opc/core/accept.py`<br>

<br>`opc/core/promote.py`<br>

<br>`opc/core/progress.py` | 彻底移除 SQLite/JSON 主张账本（Claims）、候选版本晋升、独立 `Reviewer` 终验及 `05-delivery-repair-loop` 修复死循环。

 |
| **直接删除** | `opc/adapters/codex.py`<br>

<br>`opc/adapters/dsh.py` | 移除针对特定 CLI 内部日志格式、会话恢复与私有参数的硬编码适配器，合并至通用 `worker.py`。

 |
| **直接删除** | `opc/scaffold/onboard.py`<br>

<br>`opc/scaffold/brief.py`<br>

<br>`opc/scaffold/evaluate_template.py`<br>

<br>`opc/strategies/param_search.py` | 移除前置契约编译冻结、SHA256 校验、评价器模板强制绑定及网格参数扫描器。

 |
| **推倒重写** | `opc/core/worker_config.py`<br>

<br>`opc/adapters/worker.py`<br>

<br>`opc/adapters/scripted.py` | **【P0 核心】** 实现与具体 Harness 无关的通用命令模板 + 文件落盘/标准输出兜底适配层。

 |
| **推倒重写** | `opc/core/workspace.py`<br>

<br>`opc/core/config.py`<br>

<br>`opc/core/engine.py`<br>

<br>`opc/core/model.py` | **【P1 核心】** 实现基于 `GOAL.md`、`STATE.md`、`steps/step-XX/{probe.md, result.md}` 的无状态推导工作区与双角色极简调度内核。

 |

---

## 二、 P0 详细开发方案：通用无绑定 Worker 适配层 (`opc/adapters/`)

### 1. 现有适配层病灶与重构目标

* **现有病灶**：原 `codex.py` 和 `dsh.py` 深度耦合了各自 CLI 的私有参数、JSON 回执解析、CLI Session 冻结（`01-cli-selection-and-freeze`）与切换预算（`05-cli-sessions-and-switch-budget`），还在 DSH 中强行注入 `dsh-tool-boundary.mjs`。一旦 CLI 升级或切换为其他 Harness（如 Claude Code、Aider、OpenHands 或本地 Python 脚本），适配层即告崩溃。


* **重构目标**：
1. **每次调用完全无状态（Stateless Invocation）**：跨轮次记忆由工作区的 `STATE.md` 唯一承载，不再维护跨轮次的 CLI Session ID。


2. **统一命令模板协议（Command Template Protocol）**：任何 CLI Harness 只需在 `workers.json` 中配置一条包含占位符的启动命令即可接入。


3. **文件落盘优先 + `stdout` 自动兜底**：Prompt 直接要求 Agent 将结果写入目标 `.md` 文件；若某 CLI 工具仅将回复打印到 `stdout` 而未直接写文件，适配层自动捕获非空 `stdout` 写入目标文件，彻底消灭因 JSON 解析失败触发的格式纠错重调。





### 2. 统一 Worker 配置文件规范 (`workers.json`)

将 `opc/scaffold/workers.json` 与项目级 `.archa/workers.json`（兼容 `.opc/local/workers.json`）统一简化为如下结构，支持内置预设（`preset`）或完全自定义的命令行模板（`command`）：

```json
{
  "roles": {
    "expert": {
      "preset": "codex",
      "model": "gpt-5.4",
      "reasoning_effort": "high",
      "timeout_seconds": 600
    },
    "executor": {
      "preset": "dsh",
      "model": "deepseek-reasoner",
      "timeout_seconds": 1200
    }
  },
  "presets": {
    "codex": {
      "command": [
        "codex", "exec",
        "--cd", "{workdir}",
        "--model", "{model}",
        "-c", "model_reasoning_effort=\"{reasoning_effort}\"",
        "--dangerously-bypass-approvals-and-sandbox",
        "-"
      ],
      "input_mode": "stdin"
    },
    "dsh": {
      "command": [
        "dsh",
        "--cwd", "{workdir}",
        "--model", "{model}",
        "--prompt-file", "{prompt_file}"
      ],
      "input_mode": "file"
    },
    "custom_sh": {
      "command": ["bash", "-c", "my-agent-cli --dir {workdir} < {prompt_file} > {output_file}"],
      "input_mode": "file"
    }
  }
}

```

**支持的模板占位符定义**：

* `{workdir}`：目标被测工程的根目录绝对路径（Agent 在该目录下直接查阅源码和运行实验）。


* `{topic_dir}`：当前探索专题目录绝对路径（存放 `GOAL.md`、`STATE.md`、`steps/`）。
* `{prompt_file}`：引擎在每一步自动生成的当前回合完整提示词文件路径（如 `steps/step-01/.expert_prompt.md`）。
* `{output_file}`：当前回合期望产出的目标文件路径（Expert 回合为 `steps/step-01/probe.md`，Executor 回合为 `steps/step-01/result.md`）。
* `{state_file}`：`STATE.md` 的绝对路径。
* `{model}` / `{reasoning_effort}`：角色配置的模型名称与推理强度参数。



### 3. 核心代码实现：`opc/core/worker_config.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json
import os

DEFAULT_PRESETS: dict[str, dict] = {
    "codex": {
        "command": [
            "codex", "exec",
            "--cd", "{workdir}",
            "--model", "{model}",
            "-c", 'model_reasoning_effort="{reasoning_effort}"',
            "--dangerously-bypass-approvals-and-sandbox",
            "-"
        ],
        "input_mode": "stdin",
    },
    "dsh": {
        "command": [
            "dsh",
            "--cwd", "{workdir}",
            "--model", "{model}",
            "--prompt-file", "{prompt_file}"
        ],
        "input_mode": "file",
    },
}

@dataclass
class RoleWorkerSpec:
    role: str
    command: list[str]
    input_mode: str = "stdin"  # "stdin" | "file"
    model: str = "gpt-5.4"
    reasoning_effort: str = "high"
    timeout_seconds: int = 900
    env: dict[str, str] = field(default_factory=dict)

def load_worker_specs(project_root: Path) -> dict[str, RoleWorkerSpec]:
    """按优先级加载 Worker 配置：项目本地配置 > 默认内置配置，无任何冻结限制。"""
    candidates = [
        project_root / ".archa" / "workers.json",
        project_root / ".opc" / "local" / "workers.json",
    ]
    raw_cfg: dict = {}
    for path in candidates:
        if path.is_file():
            raw_cfg = json.loads(path.read_text(encoding="utf-8"))
            break

    presets = {**DEFAULT_PRESETS, **raw_cfg.get("presets", {})}
    roles_cfg = raw_cfg.get("roles", raw_cfg)  # 兼容旧版顶层直接写 expert/designer

    specs: dict[str, RoleWorkerSpec] = {}
    for role, default_preset in [("expert", "codex"), ("executor", "codex")]:
        # 兼容旧配置文件中的 "designer" 键名，自动映射为 "executor"
        rcfg = roles_cfg.get(role) or (roles_cfg.get("designer") if role == "executor" else None) or {}
        preset_name = rcfg.get("preset") or rcfg.get("cli") or default_preset
        preset = presets.get(preset_name, DEFAULT_PRESETS["codex"])

        cmd = rcfg.get("command") or preset["command"]
        input_mode = rcfg.get("input_mode") or preset.get("input_mode", "stdin")

        specs[role] = RoleWorkerSpec(
            role=role,
            command=list(cmd),
            input_mode=input_mode,
            model=rcfg.get("model", "gpt-5.4"),
            reasoning_effort=rcfg.get("reasoning_effort", "high"),
            timeout_seconds=int(rcfg.get("timeout_seconds", 900)),
            env=dict(rcfg.get("env", {})),
        )
    return specs

```

### 4. 核心代码实现：`opc/adapters/worker.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import time
from opc.core.worker_config import RoleWorkerSpec

@dataclass
class WorkerRunResult:
    role: str
    returncode: int
    duration_seconds: float
    output_file: Path
    log_file: Path

class UniversalCliWorker:
    """与具体 CLI Harness 解耦的通用无状态执行器。"""

    def __init__(self, spec: RoleWorkerSpec):
        self.spec = spec

    def invoke(
        self,
        *,
        workdir: Path,
        topic_dir: Path,
        prompt_text: str,
        prompt_file: Path,
        output_file: Path,
        log_file: Path,
    ) -> WorkerRunResult:
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt_text, encoding="utf-8")

        state_file = topic_dir / "STATE.md"
        state_mtime_before = state_file.stat().st_mtime if state_file.exists() else 0.0
        output_existed_before = output_file.exists()

        # 渲染命令占位符
        template_vars = {
            "workdir": str(workdir.resolve()),
            "topic_dir": str(topic_dir.resolve()),
            "prompt_file": str(prompt_file.resolve()),
            "output_file": str(output_file.resolve()),
            "state_file": str(state_file.resolve()),
            "model": self.spec.model,
            "reasoning_effort": self.spec.reasoning_effort,
        }
        cmd = [part.format(**template_vars) for part in self.spec.command]

        env = os.environ.copy()
        env.update(self.spec.env)

        stdin_data = prompt_text if self.spec.input_mode == "stdin" else None
        start_t = time.monotonic()

        proc = subprocess.run(
            cmd,
            cwd=str(workdir.resolve()),
            input=stdin_data,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.spec.timeout_seconds,
            env=env,
        )
        duration = time.monotonic() - start_t

        # 保存原始进程日志供调试工作台查看（不参与任何阻塞式校验）
        log_content = (
            f"$ {' '.join(cmd)}\n"
            f"exit_code: {proc.returncode} | duration: {duration:.2f}s\n"
            f"--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}\n"
        )
        log_file.write_text(log_content, encoding="utf-8")

        # 双保险兜底：若 CLI 仅输出到 stdout 而未直接创建 output_file，自动将 stdout 落盘
        if not output_file.exists() or (not output_existed_before and output_file.stat().st_size == 0):
            cleaned_stdout = (proc.stdout or "").strip()
            if cleaned_stdout:
                output_file.write_text(cleaned_stdout + "\n", encoding="utf-8")

        if proc.returncode != 0 and not output_file.exists():
            raise RuntimeError(
                f"Worker '{self.spec.role}' failed (exit {proc.returncode}). See log: {log_file}"
            )

        return WorkerRunResult(
            role=self.spec.role,
            returncode=proc.returncode,
            duration_seconds=duration,
            output_file=output_file,
            log_file=log_file,
        )

```

---

## 三、 P1 详细开发方案：轻量化调度内核与三文件工作区 (`opc/core/`)

### 1. 三文件工作区设计 (`opc/core/workspace.py`)

废除原 `.opc/` 下复杂的 `project.json`、`contract.json`、回执账本与 SHA256 哈希树，工作区仅由 **3 类纯文本 Markdown 文件**构成，所有运行状态直接从文件系统实时推导：

```text
<project_root>/.archa/topics/<topic_slug>/
├── GOAL.md                  # 顶层目标、代码/模拟器环境入口与停止标准
├── STATE.md                 # 唯一跨轮次共享认知表（Expert 每轮原地更新）
└── steps/
    ├── step-01/
    │   ├── probe.md         # Expert 产出的单步最小可区分问题与实验设计
    │   ├── result.md        # Executor 产出的源码核查/实测结果与原件路径
    │   ├── .expert.log      # 进程原始日志（仅供排查，不进上下文）
    │   └── .executor.log
    └── step-02/
        └── ...

```

#### (1) `STATE.md` 标准结构模板（内化 PIM 探索收敛表）

直接将《PIM架构探索讨论.md》第 5、11、14 轮与《PIM 架构探索：实验归类与问题演进.md》第 6 节的认知推进表固化为 `STATE.md` 初始骨架：

```markdown
# Architecture Exploration State
STATUS: IN_PROGRESS

## 1. 已确认机制与定量参数 (Confirmed Mechanics & Parameters)
- (尚无确认项，待第 1 轮锚定时间单位、计时起止窗口与基本拓扑)

## 2. 当前性能与关键路径模型 (Analytical & Critical-Path Model)
- (待建立工作量映射与阶段关键路径方程)

## 3. 已证伪与已关闭分支 (Falsified Hypotheses & Closed Branches - 严禁重入)
- (记录已验证通过或已通过关键路径/数学推演排除的无效方向，后续轮次禁止重复实验)

## 4. 待解关键缺口队列 (Prioritized Open Questions - 每次仅取 Top 1)
1. [P0] 明确模拟器的测量边界、时间单位与单次执行的工作量映射关系。

## 5. 最新一轮认知演进一句话总结 (Last Step Delta)
- 初始状态。

```

#### (2) 零哈希、零账本的“文件系统状态自动推导”逻辑

不需要任何数据库或恢复兼容性校验（`04-resume-compatibility`），引擎在启动或恢复时只需扫描 `STATE.md` 与 `steps/` 目录，即可 100% 确定当前所处阶段：

* **规则 1**：若 `STATE.md` 首部包含 `STATUS: COMPLETED`，则专题已完成，引擎直接退出。
* **规则 2**：扫描 `steps/step-XX/`（按编号升序）：
* 若没有任何 `step-XX` 目录 $\rightarrow$ 创建 `step-01`，当前动作为 **`RUN_EXPERT(step=1)`**。
* 若最新目录 `step-N` 下**不存在** `probe.md`（或为空） $\rightarrow$ 当前动作为 **`RUN_EXPERT(step=N)`**。
* 若最新目录 `step-N` 下**存在** `probe.md`，但**不存在** `result.md`（或为空） $\rightarrow$ 当前动作为 **`RUN_EXECUTOR(step=N)`**。
* 若最新目录 `step-N` 下**同时存在** `probe.md` 和 `result.md` $\rightarrow$ 创建 `step-(N+1)`，当前动作为 **`RUN_EXPERT(step=N+1)`**。



**这种设计带来的直接好处**：

1. **随时 `Ctrl+C` 零损坏**：无论在 Expert 还是 Executor 运行途中中断，重启时自动接着未写完的那一步继续。
2. **人工无缝介入（Human-in-the-Loop）**：用户随时可以用编辑器直接打开 `STATE.md` 划掉某个错误方向，或者直接修改 `step-03/probe.md` 的实验要求，保存后再运行命令，引擎零报错直接按人工修改后的意图执行。



#### (3) 核心代码实现：`opc/core/workspace.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

INITIAL_STATE_TEMPLATE = """# Architecture Exploration State
STATUS: IN_PROGRESS

## 1. 已确认机制与定量参数 (Confirmed Mechanics & Parameters)
- (待锚定)

## 2. 当前性能与关键路径模型 (Analytical & Critical-Path Model)
- (待建立)

## 3. 已证伪与已关闭分支 (Falsified Hypotheses & Closed Branches - 严禁重入)
- (尚无)

## 4. 待解关键缺口队列 (Prioritized Open Questions - 每次仅取 Top 1)
1. 核实基础执行语义、计时起止边界与有效工作量映射。

## 5. 最新一轮认知演进一句话总结 (Last Step Delta)
- 初始化探索工作区。
"""

class NextActionType(str, Enum):
    COMPLETED = "completed"
    RUN_EXPERT = "run_expert"
    RUN_EXECUTOR = "run_executor"

@dataclass
class StepContext:
    step_index: int
    step_dir: Path
    probe_file: Path
    result_file: Path

class TopicWorkspace:
    """管理三文件工作区（GOAL.md, STATE.md, steps/step-XX/），零哈希、零 JSON 账本。"""

    def __init__(self, project_root: Path, topic_dir: Path):
        self.project_root = project_root.resolve()
        self.topic_dir = topic_dir.resolve()
        self.goal_file = self.topic_dir / "GOAL.md"
        self.state_file = self.topic_dir / "STATE.md"
        self.steps_root = self.topic_dir / "steps"

    def ensure_initialized(self, default_goal: str = "") -> None:
        self.topic_dir.mkdir(parents=True, exist_ok=True)
        self.steps_root.mkdir(parents=True, exist_ok=True)
        if not self.goal_file.exists():
            self.goal_file.write_text(default_goal or "# Exploration Goal\n", encoding="utf-8")
        if not self.state_file.exists():
            self.state_file.write_text(INITIAL_STATE_TEMPLATE, encoding="utf-8")

    def is_completed(self) -> bool:
        if not self.state_file.exists():
            return False
        text = self.state_file.read_text(encoding="utf-8")
        return bool(re.search(r"^STATUS:\s*COMPLETED\b", text, re.MULTILINE | re.IGNORECASE))

    def get_step(self, step_index: int) -> StepContext:
        step_dir = self.steps_root / f"step-{step_index:02d}"
        return StepContext(
            step_index=step_index,
            step_dir=step_dir,
            probe_file=step_dir / "probe.md",
            result_file=step_dir / "result.md",
        )

    def existing_steps(self) -> list[StepContext]:
        if not self.steps_root.exists():
            return []
        indices: list[int] = []
        for d in self.steps_root.iterdir():
            if d.is_dir() and d.name.startswith("step-"):
                try:
                    indices.append(int(d.name.split("-", 1)[1]))
                except ValueError:
                    continue
        return [self.get_step(idx) for idx in sorted(indices)]

    def derive_next_action(self) -> tuple[NextActionType, StepContext]:
        """完全从当前磁盘文件状态推导下一步动作。"""
        if self.is_completed():
            steps = self.existing_steps()
            last_step = steps[-1] if steps else self.get_step(1)
            return NextActionType.COMPLETED, last_step

        steps = self.existing_steps()
        if not steps:
            return NextActionType.RUN_EXPERT, self.get_step(1)

        latest = steps[-1]
        has_probe = latest.probe_file.is_file() and latest.probe_file.stat().st_size > 0
        has_result = latest.result_file.is_file() and latest.result_file.stat().st_size > 0

        if not has_probe:
            return NextActionType.RUN_EXPERT, latest
        if not has_result:
            return NextActionType.RUN_EXECUTOR, latest
        return NextActionType.RUN_EXPERT, self.get_step(latest.step_index + 1)

```

---

### 2. 轻量化双角色调度内核 (`opc/core/engine.py`)

#### (1) 核心上下文经济学（Enforced Context Economy）

为防止像旧版那样随着迭代轮次增加导致 Prompt 呈平方级膨胀：

* **传给 `Expert` 的上下文**只包含 3 样东西：
1. `GOAL.md` 全文；
2. 当前 `STATE.md` 全文（由于每轮原地更新而非无限追加，始终保持精简）；
3. **仅上一轮（`step-(N-1)`）** 的 `probe.md` 与 `result.md` 全文（更早的历史轮次只列出文件路径索引，Expert 若需回看某次特定数据可自行查阅，不塞入默认 Prompt）。


* **传给 `Executor` 的上下文**只包含 3 样东西：
1. `GOAL.md` 全文；
2. 当前 `STATE.md` 全文（让 Executor 知道已确认事实和已关闭分支，避免做无用功）；
3. **本轮（`step-N`）** 的 `probe.md` 全文。



#### (2) 核心代码实现：`opc/core/engine.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from opc.adapters.prompts import build_expert_prompt, build_executor_prompt
from opc.adapters.worker import UniversalCliWorker
from opc.core.worker_config import load_worker_specs
from opc.core.workspace import NextActionType, StepContext, TopicWorkspace

@dataclass
class EngineSummary:
    status: str  # "completed" | "max_steps_reached" | "stopped"
    last_step: int
    state_file: Path

class LightweightEngine:
    """极简双角色（Expert <-> Executor）探索调度引擎。"""

    def __init__(
        self,
        project_root: Path,
        topic_dir: Path,
        workers: dict[str, UniversalCliWorker] | None = None,
    ):
        self.workspace = TopicWorkspace(project_root, topic_dir)
        self.workspace.ensure_initialized()
        if workers is not None:
            self.workers = workers
        else:
            specs = load_worker_specs(self.workspace.project_root)
            self.workers = {role: UniversalCliWorker(spec) for role, spec in specs.items()}

    def step_once(self) -> tuple[NextActionType, StepContext]:
        """执行单步动作（Expert 或 Executor），支持单步调试与随时恢复。"""
        action, step_ctx = self.workspace.derive_next_action()
        if action == NextActionType.COMPLETED:
            return action, step_ctx

        step_ctx.step_dir.mkdir(parents=True, exist_ok=True)
        goal_text = self.workspace.goal_file.read_text(encoding="utf-8")
        state_text = self.workspace.state_file.read_text(encoding="utf-8")

        if action == NextActionType.RUN_EXPERT:
            prev_probe, prev_result = "", ""
            if step_ctx.step_index > 1:
                prev_ctx = self.workspace.get_step(step_ctx.step_index - 1)
                if prev_ctx.probe_file.is_file():
                    prev_probe = prev_ctx.probe_file.read_text(encoding="utf-8")
                if prev_ctx.result_file.is_file():
                    prev_result = prev_ctx.result_file.read_text(encoding="utf-8")

            prompt = build_expert_prompt(
                step_index=step_ctx.step_index,
                goal_text=goal_text,
                state_text=state_text,
                prev_probe_text=prev_probe,
                prev_result_text=prev_result,
                state_file_path=self.workspace.state_file,
                probe_file_path=step_ctx.probe_file,
            )
            self.workers["expert"].invoke(
                workdir=self.workspace.project_root,
                topic_dir=self.workspace.topic_dir,
                prompt_text=prompt,
                prompt_file=step_ctx.step_dir / ".expert_prompt.md",
                output_file=step_ctx.probe_file,
                log_file=step_ctx.step_dir / ".expert.log",
            )
            return self.workspace.derive_next_action()

        if action == NextActionType.RUN_EXECUTOR:
            probe_text = step_ctx.probe_file.read_text(encoding="utf-8")
            prompt = build_executor_prompt(
                step_index=step_ctx.step_index,
                goal_text=goal_text,
                state_text=state_text,
                probe_text=probe_text,
                result_file_path=step_ctx.result_file,
                step_dir_path=step_ctx.step_dir,
            )
            self.workers["executor"].invoke(
                workdir=self.workspace.project_root,
                topic_dir=self.workspace.topic_dir,
                prompt_text=prompt,
                prompt_file=step_ctx.step_dir / ".executor_prompt.md",
                output_file=step_ctx.result_file,
                log_file=step_ctx.step_dir / ".executor.log",
            )
            return self.workspace.derive_next_action()

        return action, step_ctx

    def run_loop(self, max_steps: int = 20) -> EngineSummary:
        """持续推进 Expert <-> Executor 循环，直到 STATE.md 标记 COMPLETED 或达到最大步数。"""
        while True:
            action, step_ctx = self.workspace.derive_next_action()
            if action == NextActionType.COMPLETED:
                return EngineSummary("completed", step_ctx.step_index, self.workspace.state_file)
            if step_ctx.step_index > max_steps:
                return EngineSummary("max_steps_reached", step_ctx.step_index - 1, self.workspace.state_file)
            self.step_once()

```

---

### 3. 配套轻量级提示词接口 (`opc/adapters/prompts.py` 骨架)

为了让 P0 与 P1 立即跑通闭环，`opc/adapters/prompts.py` 彻底移除旧版的 JSON Schema 校验和 `Reviewer` 提示词，改为直接驱动 `STATE.md`、`probe.md` 和 `result.md` 的极简苏格拉底协议：

```python
from __future__ import annotations
from pathlib import Path

def build_expert_prompt(
    *,
    step_index: int,
    goal_text: str,
    state_text: str,
    prev_probe_text: str,
    prev_result_text: str,
    state_file_path: Path,
    probe_file_path: Path,
) -> str:
    prev_section = ""
    if prev_result_text:
        prev_section = (
            f"## 上一轮探针 (Step {step_index - 1} Probe)\n{prev_probe_text}\n\n"
            f"## 上一轮执行结果 (Step {step_index - 1} Result)\n{prev_result_text}\n\n"
        )

    return f"""你是架构探索项目的主导架构师（Expert）。你通过与实验执行者（Executor）的多轮协作，建立可解释、可预测的架构模型并支撑设计决策。

## 核心工作准则（严禁违反）
1. **先消化上一轮结果并原地更新 `{state_file_path}`**：
   - 将已证实的硬件/软件机制、计数边界、关键路径方程写入第 1、2 节。
   - **果断关闭分支**：若上一轮反事实实验已证伪某假设（如证实某粒度只是软件硬编码），或通过关键路径数学算式（如 max_c(E_c)）证明某局部停顿优化收益极小，立即将该分支写入第 3 节 `Closed Branches`，**严禁在同一局部指标上反复打磨或搭建校准流水线**。
   - 在第 5 节用一句话写清：“本轮结果改变了哪条架构判断，下一步还缺哪一种信息”。
2. **完成态判定**：
   - 如果 `GOAL.md` 中的核心架构问题均已形成有证据支撑的结论与模型，将 `{state_file_path}` 顶部的状态改为 `STATUS: COMPLETED`，并在 `{probe_file_path}` 中写入最终架构规格总结，无需再发新实验。
3. **单步最小探针原则（One Question, Minimal Probe）**：
   - 若仍需推进，从 `STATE.md` 第 4 节取出 **Top 1** 待解缺口，写入 `{probe_file_path}`。
   - 每一轮 `{probe_file_path}` **只允许提出 1 个可区分竞争假设（Hypothesis A vs B）的具体问题**。
   - **零成本优先**：能通过查阅源码、反汇编或复核已有 Trace 回答的问题，要求 Executor 直接核查源码/已有原件，不要启动模拟器。
   - **最小对照**：确需运行模拟器时，优先设计 1~2 次最小反事实探针，严禁在未摸清机制前下发大规模网格扫描。

## 顶层目标 (`GOAL.md`)
{goal_text}

## 当前认知状态 (`STATE.md`)
{state_text}

{prev_section}## 本轮输出要求
1. 直接修改更新文件：`{state_file_path}`（保持 5 个标准小节结构，总行数控制在 250 行以内）。
2. 将第 {step_index} 轮的最小探针指令写入文件：`{probe_file_path}`（包含：本轮唯一问题、竞争假设 A/B、最小核查或实验步骤、预期观测指标）。
"""

def build_executor_prompt(
    *,
    step_index: int,
    goal_text: str,
    state_text: str,
    probe_text: str,
    result_file_path: Path,
    step_dir_path: Path,
) -> str:
    return f"""你是架构探索项目的实验执行者（Executor）。你的任务是在目标工程中精确执行架构师（Expert）提出的第 {step_index} 轮最小探针（`probe.md`），并将客观事实写入 `{result_file_path}`。

## 核心工作准则
1. **源码与已有 Trace 优先**：如果 `probe.md` 的问题可以通过阅读源码、配置文件或离线分析已有 Trace 回答，直接提取代码行号/Trace 证据，不要重复跑模拟器。
2. **干预生效自检（Intervention Check）**：若修改了配置或代码并运行模拟器，必须先核对底层请求数、命令序列或寄存器状态是否真实发生变化，明确区分“参数修改已生效”与“修改未被执行路径消费（No-op）”。
3. **禁止过度工程**：只做回答本轮 `probe.md` 所需的最小改动或脚本，将衍生数据保存在 `{step_dir_path}` 下，不要搭建复杂的自检框架或防御性包装脚本。

## 顶层目标 (`GOAL.md`)
{goal_text}

## 当前认知状态 (`STATE.md`)
{state_text}

## 本轮探针要求 (`Step {step_index} Probe`)
{probe_text}

## 本轮输出要求
请完成核查或实验后，将结果直接写入 `{result_file_path}`，包含：
1. **执行动作与干预核验**：查了哪些源码/原件，或跑了什么命令（干预是否真实改变了内部执行行为）。
2. **关键观测数据**：直接给出定量计数、时间戳分布、关键路径对比表或源码片段。
3. **结论与原件路径**：直接回答 `probe.md` 的竞争假设（支持 A 还是 B），并列出留存原件路径。
"""

```

---

## 四、 P0 & P1 测试桩与回归验证方案 (`opc/tests/`)

删除原 `opc/tests/` 下针对账本恢复、合同冻结、切换预算、工具边界和交付修复循环的冗余测试（如 `test_accounting_recovery.py`, `test_delivery_repair.py`, `test_tool_boundary.py`, `test_switch_budget.py` 等），替换为以下 3 个核心测试：

1. **`test_universal_worker.py`（验证 P0 通用 Worker 适配层）**：
* **用例 1（文件直写模式）**：模拟 CLI 工具（如 `codex` / `dsh`）在运行中直接修改 `STATE.md` 并写入 `probe.md`，验证 `UniversalCliWorker` 正确渲染 `{workdir}`、`{prompt_file}`、`{output_file}` 占位符并正常返回。
* **用例 2（`stdout` 自动兜底模式）**：模拟某个只往 `stdout` 打印 Markdown 而不写文件的第三方 CLI 工具，验证 `UniversalCliWorker` 自动将 `stdout` 落盘为 `probe.md` / `result.md`，无需任何格式重试。


2. **`test_workspace_resume.py`（验证 P1 零哈希状态推导与人工介入恢复）**：
* 在空目录初始化 `TopicWorkspace`，验证 `derive_next_action()` 依次在 `RUN_EXPERT(step=1)` $\rightarrow$ 写入 `probe.md` 后变为 `RUN_EXECUTOR(step=1)` $\rightarrow$ 写入 `result.md` 后变为 `RUN_EXPERT(step=2)` 之间准确切换。
* 模拟人工直接编辑 `STATE.md` 写入 `STATUS: COMPLETED`，验证引擎立即识别为 `NextActionType.COMPLETED` 并停止。


3. **`test_lightweight_engine_loop.py`（验证 P0 + P1 端到端闭环）**：
* 使用简化的 `ScriptedWorker` 模拟 3 轮 PIM 探索（第 1 轮核查 CK 单位与计时窗口 $\rightarrow$ 第 2 轮核查 350 CK 刷新与四通道关键路径并关闭单通道刷新分支 $\rightarrow$ 第 3 轮验证 N=1024 四组反事实并将 `STATE.md` 置为 `COMPLETED`），验证整个循环在 1 秒内跑通且文件结构干净无冗余。



