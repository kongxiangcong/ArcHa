# 跨平台运行

ArcHa 支持 Python 3.10+；CI 在 Linux/Windows 的 Python 3.10、3.12、3.14 上运行核心与工具回归。当前使用入口见 [README](../README.md)。Worker 指定的程序、依赖和实验环境须在本机可用。

命令配置使用 argv 数组，不隐式启动 shell。Windows `.cmd`/`.bat` 包装器会被拒绝；指定实际 `.exe` 或 Node/Python 入口。Windows Job 在子进程恢复执行前建立归属，登记失败会停止启动；POSIX 使用独立 session 管理进程树。这些机制提供生命周期管理，不是针对恶意程序的操作系统沙箱。

工程独占锁使用稳定文件上的 OS 锁，控制器崩溃后由 OS 释放。PID 本身不能证明旧执行归属，无法确认旧进程结束时拒绝新派发。进程树清理和 Job 启动失败回归保留在 `opc/tests/test_platform.py`，其他停止/并发行为由专题控制测试验证。

初始化器在项目 `.archa/` 内创建继承项目权限的暂存目录，再原子移动为 runtime。不要将私有临时目录的 ACL 随 rename 带入部署目录：Windows Python 3.13+ 的 mode 0700 可能让独立沙箱账户无法读取 runtime。部署快照仅包含 Python 标准库所需的核心代码与资源；工作台依赖通过 observer extra 单独安装。

限制性外层沙箱可能阻止 HTTP 测试、进程操作或目录访问。验收应保留真实错误，并在授权宿主环境复核，不将失败改成无条件跳过。Linux 验收不能替代 Windows Job 与原生锁测试，Windows 专属用例在 Linux 明确跳过并由 CI 执行。
