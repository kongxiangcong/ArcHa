# FR64：独立考题与外部评测包

准备日期：2026-10-25。**当前只准备文件；未安装工具、未在本机运行仿真/综合/优化实验。所有成绩待Linux实测。**

| 路径 | 接收者 | 用途 |
|---|---|---|
| exam/ | 两组各一份干净副本 | 规格、独立朴素起点、固定加法器、公开评价器 |
| external-eval/ | 仅部署/评测者 | 固定版本参考、隐藏测试种子入口、独立重测与汇总 |
| deployment/ | 部署者 | Linux说明、隔离协议、提示词、固定ArcHa技能/runtime |

**不要把整个包放进参试Codex的可读目录。** 顶层包和external-eval含参考实现。分别授予最小目录访问，不能仅用提示词要求不看。

先给服务器部署Codex [初始化提示词](deployment/prompts/01-linux-setup.md)，完成Linux资格检查与隔离。然后在全新会话分别使用 [直接Codex提示词](deployment/prompts/02-direct-codex.md) 和 [ArcHa模拟用户提示词](deployment/prompts/03-archa-simulated-user.md)。两组结束后用 [外部评测提示词](deployment/prompts/04-final-evaluation.md)。详细命令见 [Linux说明](deployment/LINUX.md)。

ArcHa严格执行map → task（含onboard）→ loop；外层Codex只模拟用户，调用loop后只观察。没有预生成.opc或合同。ArcHa当前需要可测基线，所以该实验是**从相同朴素起点优化**，不是从空白生成。原语是许可复用的数值基础，不含参考归约调度。

首版比较标准单元映射面积和零布线寄生的综合后STA。它是可复算的同口径模块基准，不是物理实现或FPGA部署成绩。面积、WNS和资格检查目前均为**未测**。保留已知成熟参考，避免只比较人为简单的起点。

参考快照为openTPU `7e42a626f714edd07867702c38c954082d51f587`；从该提交公开raw内容下载，哈希见external-eval/upstream/provenance.json。它是本实验冻结版本，不会在运行时静默跟随上游更新。ArcHa runtime来自本仓库打包时工作树，基准commit与逐文件哈希见deployment/skills/archa-map/assets/runtime/manifest.json。

交付检查限于文件、语法、哈希和泄漏边界的静态核对；这不证明硬件或EDA流程已通过。服务器必须先对starter与reference共同资格检查，任何兼容修复均在两组开始前记录并重新冻结。
