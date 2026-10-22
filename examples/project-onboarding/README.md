# 项目接入与实验路径验证

更新：2026-10-22。此例验证 OPC 元数据可附加到不同目录结构的项目，以及实验路径可确定计算。它没有安装 agent、运行实验、建立 Git worktree 或授予执行权限。

## 接入辅助工具

在 Ge 项目根运行。目标目录必须已经存在；`init` 默认只预览，只有显式 `--apply` 才写入一个新的 `.opc/`：

```powershell
python tools/project_layout.py init --project-root D:/your-project --project-id my-project --name "My project"
python tools/project_layout.py init --project-root D:/your-project --project-id my-project --name "My project" --apply
```

`project_id` 使用1至64位小写字母、数字与连字符；不能使用 Windows 保留设备名、路径片段或大写别名。生产注册表还必须保证 project ID 全局唯一，工具无法发现其他主机的重复注册。

写入的内容：

```text
<project>/.opc/
  project.json                 # execution_enabled=false, adapter_id=unconfigured
  .gitignore                   # /local/，不修改项目根.gitignore
  README.md
  context/PROJECT.md
  context/REQUIREMENTS.md
  context/DECISIONS.md
  components/README.md         # default 仅预留，尚未生成有效组件合同
  tasks/README.md
```

已有 `.opc` 文件、目录或链接一律拒绝覆盖；原始源码、Git 状态、根 `.gitignore` 和其他项目配置保持不变。异常中断可能留下不完整的 `.opc` 草案，工具不会自动删除或覆盖它，需先检查文件再处理。该工具不提供生产多进程锁或防止同权限攻击的安全隔离。

接入后应由 Ge 补齐组件可改路径、冻结参考、评价器、工具 argv、预算、干净 commit/显式 snapshot 及主机路径绑定，然后运行生产 preflight。目录存在不代表已经可派发。

## 计算每次实验的位置

```powershell
python tools/project_layout.py paths --project-root D:/your-project --project-id my-project --task-id optimize-one --run-id run-20261022-demo --attempt 1 --workspace-root D:/opc-workspaces
```

默认 artifact root 为 `<project>/.opc/local/artifacts`；也可用 `--artifact-root D:/opc-artifacts`。此命令只打印路径，不创建工作区、实验记录或接纳决定。

产物路径为：

```text
<artifact-root>/<project-id>/<task-id>/<run-id>/attempts/a000001/
  plan.json
  candidate/source/
  experiment/jobs/<job-id>/{stdout.txt,stderr.txt,receipt.json}
  submissions/<submission-id>/manifest.json
  reviews/<review-id>/{Standards.json,Spec.json,decision.json}

<workspace-root>/<project-id>/<task-id>/<run-id>/a000001/
  designer/
  reviewer/
```

`--job-id`、`--submission-id`、`--review-id` 可显式传入；默认只是 `job-000001`、`submission-000001`、`review-000001` 的路径示例。生产 ID 应由控制服务分配并持久保存，不能由时间戳或此示例默认值推断全局唯一。

工作区根必须位于目标项目外，且与项目及 artifact root 不重叠。项目内部 artifact root 只允许 `.opc/local/artifacts`；外部根不得包含项目本身。对子路径 resolve 后拒绝跳转或越界，包括已存在的符号链接重定向；每一级已存在的父路径必须是目录，预期目录叶不能是文件，预期文件叶不能是目录。绝对路径仅出现在本机路径绑定/输出；对外引用同时生成 `artifact://<project>/<task>/<run>/...`，不会把本机盘符写入逻辑合同。

## 本轮实际验证

两个 fixture 的源码结构不同：

- [compiler-project](fixtures/compiler-project/src/pipeline.py)：`src/pipeline.py`。
- [rtl-project](fixtures/rtl-project/rtl/identity.sv)：`rtl/identity.sv`。

两者均实际执行了 dry-run 和 `--apply`，源码前后 SHA-256 相同。compiler 使用默认本地 artifact root，RTL 使用项目外 artifact root；各输出了 attempt 1/2 的路径，未创建实验工作区。

证据分别在 [compiler evidence](fixtures/evidence/compiler/source-preservation.json) 和 [RTL evidence](fixtures/evidence/rtl/source-preservation.json)，同目录保存 init 预览/结果和两份 layout JSON。这些是接入演示工件，不是编译器、RTL 或自动优化的功能验收。

测试命令：

```powershell
$env:TEMP = 'D:/dsh-proj/Ge/examples/project-onboarding/fixtures/.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
python -m pytest tools/tests/test_project_layout.py -q --basetemp examples/project-onboarding/fixtures/.tmp/pytest-final --junitxml examples/project-onboarding/fixtures/tests.xml
python -m ruff check tools/project_layout.py tools/tests/test_project_layout.py
python -m mypy tools/project_layout.py --follow-imports=skip
```

审后测试结果见 [JUnit](fixtures/tests-reviewed.xml)；初版 [JUnit](fixtures/tests.xml) 保留为历史。Windows 当前环境无法创建符号链接，因此实际链接越界测试跳过；该路径仅经代码审查，不记作实测通过。其余测试验证默认无写、重复初始化拒绝、源码保留、项目/轮次区分、穿越/设备名拒绝、工作区/产物根重叠拒绝，以及生成子路径的文件/目录冲突拒绝。

独立审查发现初版只检查根路径中的文件祖先，未检查 `candidate` 等生成子目录；该问题已修复，并增加4种冲突回归。生成需求 ID 已统一为 v0.2 合同接受的小写 `req-001`；两个 fixture 仅相应草案行被修正，原源码仍与接入前摘要一致。修订记录见 [compiler](fixtures/evidence/compiler/metadata-correction.json) 与 [RTL](fixtures/evidence/rtl/metadata-correction.json)。
