# Windows 与 Linux

ArcHa 的合同、迭代、预算、接纳、恢复和晋升使用同一套代码。运行要求是 Python 3.10+、Git，以及目标项目自己的工具链。Windows 建议 Windows 10/11 与 Git for Windows；Linux 可直接运行，也可在 WSL 的 Linux 文件系统内运行。

## 安装和命令

在仓库目录执行：

```text
python -m pip install -e .
python -m opc --help
python -m opc check -p <project> --task <task>
```

Linux 上若只有 `python3`，用它替代以上 `python`。合同里的 Python 命令使用 `"{python}"`，由引擎替换为当前解释器；新生成的工具链探针也使用该占位符。已有合同里的 `python3` 不会自动改写，更新合同后应提交并开启新 revision/run。

Windows PowerShell 不需要设置 Bash 的 `export PYTHONPATH`。路径参数作为独立 argv 元素传递，包含空格和中文也无需拼接 shell 字符串。合同里的相对文件路径统一使用 `/`。

## Worker 入口

`binary` 接受可执行文件名/路径、`.py` 脚本（当前 Python 启动）或完整 argv 前缀，例如：

```json
{"kind": "codex", "binary": "C:/tools/codex.exe"}
```

```json
{"kind": "dsh", "binary": ["node", "C:/tools/dsh/cli.js"]}
```

onboard 的 `OPC_CODEX_BIN` / `OPC_DSH_BIN` 同样接受路径或 JSON 数组字符串。Windows 的 `.cmd` / `.bat` 包装器会被拒绝；请指定实际 `.exe` 或 Node/Python 入口，避免引入 shell 的参数重解释。gate 与 toolchain 的 `argv` 也应直接调用实际程序或解释器。

Windows 上没有指定 `binary` 或 `OPC_CODEX_BIN` 时，Codex worker 优先查找 PATH 中的 `codex.exe`，避免靠前的 npm `codex.cmd` 遮蔽已安装的原生 CLI。显式指定的入口始终优先，不自动换版本或改模型、账号、全局配置；实际启动 argv 保存在 worker 的 `*-request.json` 中。

CLI 在会话创建前退出时，worker 把它归类为基础设施失败，并在没有 JSON 错误事件时返回 stderr 诊断。配置解析失败、模型要求更新 CLI、app-server 初始化失败也归为基础设施问题，不消耗算法搜索次数。旧 CLI 不支持当前配置或模型时，应更新/选择兼容 CLI；ArcHa 不通过改写配置值或降级模型隐藏不兼容。

专家计划采用 strict JSON schema，所有声明属性都在 `required` 中；普通计划返回 `exhausted=false`，没有实验可做时返回 `true`。服务端 schema 拒绝属于协议基础设施故障，不能记作调度算法失败。

## 同样的保证，不同的系统实现

- 写入锁：POSIX 使用 `flock`，Windows 使用非阻塞字节范围锁。同一项目第二个控制器立即失败，异常退出后由操作系统释放锁。锁文件保留，不通过删除锁文件“解锁”。不要让原生 Windows 和 WSL 同时控制同一个工作目录；不同系统的锁协议不互通，也不承诺网络文件系统锁语义。
- 进程：POSIX 建立独立 session/process group；Windows 创建暂停进程，成功加入禁止 breakaway 的 Job Object 后恢复执行。绑定失败则终止启动。超时、异常和正常返回都会清理所属进程树，包括父进程先退出后留下的普通后代。Windows 使用 [Job Object 的 kill-on-close 机制](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
- 文件：Git 补丁通过字节管道传输，避免 Windows 换行转换；文本文件显式使用 UTF-8。冻结路径的拒绝匹配在两端均不区分大小写，授权匹配仍区分大小写。拒绝路径穿越、盘符、反斜杠、备用数据流、保留设备名与尾随点/空格；候选软链接和 junction 不进入可接纳补丁。
- 比较：工具链摘要包含系统名称、版本、架构及 Python 版本；环境变化触发现有冠军复测机制，不直接把不同系统的数字当作同一测量条件。摘要格式升级也会导致旧测量复测。

进程管理不等于恶意代码隔离：POSIX 子进程主动创建新 session 可以逃离进程组，现有 worktree + worker 沙箱 + 事后检查也不是 OS 安全边界。需要执行不可信代码时仍需独立账号或容器。两端均保留这一既有安全边界。

目标项目的评价器和依赖必须能在当前系统运行；Linux 专属编译器、Bash 脚本和模拟器不会因引擎跨平台而自动移植。已部署的 `.opc/runtime` 仍固定在原快照，安装新技能不会自动升级它。

初始化器在项目 `.opc/` 下创建继承项目权限的暂存目录，校验后再原子移动为 runtime。不要把 `TemporaryDirectory` 的私有 ACL 随 rename 带入部署目录：Windows Python 3.13+ 的 mode 0700 会使以独立沙箱账户运行的 worker 无法读取它。升级前已受影响的目录需要显式重新部署并核对摘要；不通过关闭 worker 沙箱解决。

## 测试

```text
python -m pip install -e . pytest
python -m pytest -q
```

CI 在 Windows、Ubuntu 的 Python 3.10/3.12/3.14 上执行同一套测试。覆盖跨进程锁竞争和崩溃释放、真实孙进程清理、worker/gate 超时、平台摘要、中文/空格路径、LF/CRLF/无末尾换行补丁、冻结路径拒绝，以及迭代/恢复/晋升回归。Windows 无软链接权限时只跳过对应软链接测试，另有不需要该权限的 junction 测试；Job Object 测试仅在 Windows 执行。

限制性外层沙箱仍可能拒绝 junction 创建或安装器对私有临时目录的访问。遇到 `Access is denied` 时保留原始输出，用相同测试节点在获授权的正常宿主环境复核，区分宿主限制与产品回归；不要把测试改成无条件跳过。起草 worker 自建验证夹具的目录权限规则见 `opc/scaffold/ONBOARDING.md` 第 6 节。
