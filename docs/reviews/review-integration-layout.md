# 独立审查：项目接入与目录布局

日期：2026-10-22。审查者：独立子 agent `opentpu_layout`，未参与 `tools/project_layout.py` 编写。审查范围是接入辅助工具、其测试、项目接入规范、两个 fixture 与路径证据。按本轮新增文件审查，不套用需要 Git 基线的完整 code-review 流程。

## 发现：P2，生成路径的文件祖先没有被预检拒绝

位置：`tools/project_layout.py` 的 `under()`（约第 51–59 行）及 `layout()` 生成各 artifact/workspace 子路径的调用。

根目录经过 `check_directory_chain()`，但生成的 `<project-id>/<task-id>/<run-id>/attempts/...` 子树只检查 resolve 后是否仍在指定根内。若 `.../a000001/candidate` 已经是一个普通文件，`layout()` 仍返回 `.../candidate/source` 作为有效源码归档目录。这条路径不越界，但无法落盘；同类问题也可发生在 `experiment/jobs` 等中间层。现有测试只覆盖 `.opc` 本身是文件的根祖先场景，没有覆盖生成子树。

已运行的最小负例：在项目自己的 `.tmp/integration-layout-review/` 创建独立 fixture 与普通文件 `artifacts/p/t/r/attempts/a000001/candidate`，调用 `layout(..., project_id='p', task_id='t', run_id='r', attempt=1)`。工具成功返回 candidate/source；原文件保持不变。证据：[file-ancestor-probe.json](../../.tmp/integration-layout-review/file-ancestor-probe.json)。未访问或修改其他项目。

影响是路径预检可靠性：目标项目可能已经有旧文件或中断留下的冲突路径，接入报告却宣称计划可用；真实 runner 直到写原件时才失败。**没有观察到覆盖源码、写出授权根或删除数据。**

建议：生成路径也校验所有现存父组件必须为目录；目录型叶子（candidate source、designer/reviewer workspace 等）如存在须为目录；文件型叶子按读取/创建策略验证类型。保留 `paths` 纯预览语义，不为修复冲突自动删除或覆盖。加入生成子树普通文件阻塞的回归。

初审状态：已修复并独立定向复验关闭。当前没有未关闭的 P1/P2。

### 修复后复核

`under()` 已对全部现存父目录调用目录链检查，并区分目录型/文件型叶子；run、attempt、workspace、candidate source 与 designer/reviewer 目录调用点明确传入 `directory=True`。文件型叶子如已存在目录则拒绝，合法现存文件可用于只读路径查询，实际创建仍使用独占写入。

独立重新运行原文件祖先反例，现抛出 `planned directory contains a non-directory path`。另外验证了目录叶子被普通文件占用、文件叶子被目录占用，两者均拒绝；全新合法路径仍成功返回且不创建 artifact/workspace 目录，原冲突文件 bytes 不变。复核证据：[path-types-recheck.json](../../.tmp/integration-layout-review/path-types-recheck.json)。没有重复运行全套测试。

修复仅提升预检可靠性，不消除检查与使用间竞态，不构成操作系统隔离。Windows 当前环境的实际符号链接用例仍未运行，不因本次修复升级其验证状态。

## 与规范一致的部分

- init 默认仅输出预览；apply 只创建新的 `.opc/`，使用独占创建，已有 `.opc`/`.OPC` 名字拒绝合并或覆盖；不会改根 `.gitignore` 或 Git 状态。
- project/task/run/job/submission/review ID 限定可移植的小写字符，拒绝路径分隔符、冒号、Windows 保留设备名和大小写别名；attempt 范围有界。
- workspace root 明确要求项目外；artifact root 项目内只接受 `.opc/local/artifacts`；artifact/workspace 根不重叠。比较按路径组件进行，没有字符串前缀误判。
- `under()` 会拒绝其所见的符号链接重定向；但当前 Windows 环境不能建立该测试链接，JUnit 对该例记 skipped。未将其描述为真实链接隔离测试通过。
- 路径输出与规范的 project/task/run/attempt/job/submission/review 分层一致，实验原件与设计/复算工作区分开。两个 fixture 的不同源码结构均保留。
- 独立重算 compiler 与 RTL fixture 当前源码 SHA-256，均与保存的 before/after 相同；各自 ProjectConfig 的 `execution_enabled=false`。

## 能力边界

这是元数据初始化与路径计算，不是运行服务。它不创建任务、ledger、实验、Git worktree、外部job、权限隔离或接纳记录；手工 run ID 不具备分布式唯一分配保证。生命周期、失败保存、冻结、GC、跨机器映射与真实预检写在设计中，本工具未声称已实施。

当前过程存在一般文件系统检查与使用之间的竞态；README 已明确没有同权限对抗或生产多进程锁。源码保护结论针对本次工具操作和 fixture，不能外推成生产 sandbox。已有 `.opc` 的升级/import 尚待独立实现，重复 init 拒绝是保护行为。
