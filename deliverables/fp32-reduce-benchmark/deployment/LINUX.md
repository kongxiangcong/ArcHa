# Linux 初始化、运行与评测

## 1. 放置与权限

推荐Ubuntu 24.04或等价Linux，Python >=3.10，至少4核；RAM/磁盘以工具构建需求准备，不把本机资源假设写进分数。顶层包只放评测者的私有目录，例如 `/srv/fr64-admin/package`，chmod 700。参试者分别在 `/srv/fr64-direct/project` 与 `/srv/fr64-archa/project`。
使用容器/独立用户隔离；参试身份无sudo，不能读取admin、另一组、主机其他项目和历史会话。正式候选在无网络、非特权、限CPU/RAM的评测环境运行。仅复制exam，不复制顶层包或external-eval。给ArcHa外层单独提供PROTOCOL.md和03提示词（不含参考设计细节）。

## 2. 工具安装（只在服务器）

基础依赖示例，由部署身份执行：
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv git build-essential cmake ninja-build curl ca-certificates verilator
```
安装带read_slang的Yosys（普通发行版旧Yosys通常不够）、OpenROAD与NanGate45 typical liberty。可用 [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) 和 [OpenROAD官方安装说明](https://openroad.readthedocs.io/en/latest/main/README.html)，工艺库取 [OpenROAD-flow-scripts NanGate45](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/master/flow/platforms/nangate45)。
选定兼容版本后保存release tag、下载SHA256、ORFS commit与镜像digest。所有组使用相同只读安装，不运行中升级。该包不自动选择latest、不预装EDA。库通常名为NangateOpenCellLibrary_typical.lib，最终以真实文件路径为准。此流程无SRAM宏依赖。

把固定技能包复制到ArcHa专用用户技能目录：
```bash
mkdir -p "$HOME/.codex/skills"
cp -a /path/to/approved-skills/archa-map "$HOME/.codex/skills/"
cp -a /path/to/approved-skills/archa-task "$HOME/.codex/skills/"
cp -a /path/to/approved-skills/archa-loop "$HOME/.codex/skills/"
```
这里approved-skills是部署者从deployment/skills导出的安全副本，不开放原始打包父目录。如果已有同名技能，先备份，确认启动会话读的是本次版本。技能包含runtime，map的initialize会自行部署；部署阶段**不调用initialize/map/task/loop**。不复制整份ArcHa研究仓库给参试者。
Codex安装、认证由服务器现有方式处理；先核实 `codex --version` 和 `codex exec --help`。非交互方式与JSONL参见[官方说明](https://learn.chatgpt.com/docs/non-interactive-mode)。每个进程独立日志；嵌套worker日志同样留存。原始凭据不打包。

## 3. 冻结前检查与正式冻结

所有命令由评测身份在包外工作目录执行。路径不用空格。先复制exam为可信模板，例如/srv/fr64-admin/template。冻结脚本参数由实际环境填写：
```bash
python3 /srv/fr64-admin/package/deployment/freeze.py \
  --exam /srv/fr64-admin/template \
  --liberty /opt/fr64/NangateOpenCellLibrary_typical.lib \
  --private /srv/fr64-admin/private \
  --model YOUR_CONFIGURED_MODEL --reasoning YOUR_CONFIGURED_EFFORT
```
若read_slang是动态插件，增加`--yosys-plugin slang`；若内置，省略。脚本记录二进制与库哈希，但动态库/插件及其他系统依赖仍需要冻结镜像或安装清单。不要仅靠版本字符串保证环境一致。

**资格检查（仍未开始优化）：**
```bash
python3 /srv/fr64-admin/template/harness/evaluate.py --out /srv/fr64-admin/qualification/starter
python3 /srv/fr64-admin/package/external-eval/judge.py \
  --template /srv/fr64-admin/template \
  --rtl /srv/fr64-admin/package/external-eval/reference \
  --seeds /srv/fr64-admin/private/seeds.json \
  --label opentpu --out /srv/fr64-admin/qualification/reference
```
必须两者pass。检查编译/STA警告、全部端口约束、无blackbox/latch/组合环、liberty时间/电容单位为ns/pF。必须确认独立Python黄金与原语在边界输入一致；不能用参考RTL自身生成全部正确答案。
再制作几个临时坏候选（恒零输出、提前/延后一个有效拍、忽略en或rst），确保评价失败；坏候选只留admin。可做基线综合网表对标准单元仿真库的独立复验，若不做须保留“RTL仿真、综合网表未复验”的限制。当前包未提供形式化证明。
时序/测试边沿不符时停止并调查包/接口错误，不能删测试、放宽数值语义或改参考架构。修复记录后在新模板/私有目录重新freeze，所有组用新版本，不覆盖已经冻结的campaign。10ns是预设约束，未实测；不保证现有两份实现一定通过。若真实需要改题，建立新版本并明确原因。
参考资格结果和seed只留admin。公开模板中仅保留共同基线的开发验证结果，不能放参考分数。

## 4. 两组独立副本和Git

将完成资格检查的可信模板各复制一份，不含任何.out/.opc或参考文件。工具安装路径需两组同样可读。由参试用户在各自项目执行：
```bash
git init -b main
git add .
git -c user.name=FR64 -c user.email=fr64@example.invalid commit -m 'FR64 frozen common baseline'
```
设定正常Git identity供后续技能提交。冻结文件在OS层只读或在只读挂载中，rtl可写；ArcHa需要创建.opc、Git worktree和提交，验证沙箱允许这些必要操作，但不扩大到admin。冻结文件digest检查不替代OS隔离。
对比两组初始rtl/primitives/harness/SPEC/toolchain/campaign哈希完全一致。`exam/`内不得有.opc；研究地图、brief和合同由正式技能会话产生。

## 5. 正式运行

各用全新会话和干净记忆，依次发送02-direct-codex.md、03-archa-simulated-user.md；两个组不可共享会话上下文。三次独立重复使用新的项目副本，不能从上次优化结果续跑；交替运行先后。
部署者设置统一CPU/RAM配额和总墙钟watchdog。阶段日志覆盖外层、内层技能会话、onboard及loop worker。总token=所有调用input+output（cached input是input的子集，不重复加）；记录provider实际口径。CLI不同版本日志事件可能变化，先用小型非硬件会话验证统计，不静默丢失未知字段。
`campaign.json`里的预算是必须监督的协议，提示词不是强制计量器。统计不到嵌套token时标记budget_unverified。启动loop前核对剩余预算合同，loop开始后不改合同、不人工干预；到预设总墙钟由外部监督截停，保存账本及终态。
ArcHa引擎本来就负责内部候选迭代，这不算外层干预。三个技能的阶段顺序和确认问答必须有真实日志。

## 6. 最终外部评测

在最后一次开发评价后封存最终commit。由评测者导出每个提交的rtl到干净提交目录；ArcHa用report中的champion。不得将候选自己的harness、toolchain.json或.opc拷入可信模板。
```bash
python3 /srv/fr64-admin/package/external-eval/judge.py \
  --template /srv/fr64-admin/template --rtl /srv/fr64-admin/submissions/direct-1 \
  --seeds /srv/fr64-admin/private/seeds.json --label direct --out /srv/fr64-admin/final/direct-1
python3 /srv/fr64-admin/package/external-eval/judge.py \
  --template /srv/fr64-admin/template --rtl /srv/fr64-admin/submissions/archa-1 \
  --seeds /srv/fr64-admin/private/seeds.json --label archa --out /srv/fr64-admin/final/archa-1
python3 /srv/fr64-admin/package/external-eval/judge.py \
  --template /srv/fr64-admin/template --rtl /srv/fr64-admin/template/rtl \
  --seeds /srv/fr64-admin/private/seeds.json --label starter --out /srv/fr64-admin/final/starter
python3 /srv/fr64-admin/package/external-eval/judge.py \
  --template /srv/fr64-admin/template --rtl /srv/fr64-admin/package/external-eval/reference \
  --seeds /srv/fr64-admin/private/seeds.json --label opentpu --out /srv/fr64-admin/final/opentpu
python3 /srv/fr64-admin/package/external-eval/summarize.py \
  /srv/fr64-admin/final/direct-1/summary.json /srv/fr64-admin/final/archa-1/summary.json \
  /srv/fr64-admin/final/starter/summary.json /srv/fr64-admin/final/opentpu/summary.json \
  --out /srv/fr64-admin/final/comparison.md
```
每个输出目录必须是新的。其余两次重复同理，汇总全部summary，不挑最好一次。judge输出可能含失败向量/seed，仅在所有提交结束后解封。完整结果附成本表，不能只有一列面积。

## 7. 验证范围

本机交付：静态文件准备与审阅。服务器资格检查：工具兼容、参考/基线正确性、拒绝坏候选。正式实验：只在服务器由上述两组实际运行。最终结果：同一NanGate45综合映射与零寄生STA估计；未来若增加布局布线，需为所有组统一追加新评价阶段，不能把两种口径混排。
