# 自我进化框架的测试案例

分组：评测。边界：调查外部框架实际用例，为ArcHa和直接Codex对照选择案例与指标，不在此阶段运行实验或修改运行机制。

## 2026-10-25更新：真实工程与探索各一项实验卡

### 后续讨论：openTPU 隐藏参考实现的模块设计选题

- 交付更新：用户已选定并要求生成独立考题与外部评测。文件位于[FR64实验包](../../../../deliverables/fp32-reduce-benchmark/README.md)。已准备规格、独立朴素RTL、固定加法器、独立整数golden、开发/外部评价脚本、Linux说明、四份提示词和固定ArcHa技能runtime；仅静态检查，无本机实验。
- 用户硬约束：外层Codex模拟用户，内层实际顺序调用map→task→loop；调用loop后外层只观察，不提示、纠错、修改、代跑或重启。地图/brief/合同由技能产生，不预填。
- 当前ArcHa要求preflight基线通过，故两组共同采用独立朴素起点，明确改为“从相同基线优化”，不声称空白生成。参考RTL只在私有评测目录。正式指标缩为NanGate45映射面积+零寄生综合后STA，未实现物理PPA流程，不冒充实测。
- 下一步由用户在新Linux服务器部署、资格检查并冻结，再分别运行两组。所有成绩待测；三次重复、总预算及嵌套调用计量见PROTOCOL。环境/评价器缺陷只在正式运行前统一修复重冻结，loop内不救场。

- 用户补充可在全新 Linux 环境开发，想仅提供必要条件、隐藏 openTPU 当前进展与结果，让 ArcHa 自主设计优化后比较。此轮仅选题，不安装或启动实验。Linux 条件解除此前平台限制，不代表工具链已验证。
- 新的硬件方向首推荐：**固定功能与吞吐约束的流式 FP32 归约模块设计优化**，从 `rtl/vpu/otpu_vtree.sv` 提取需求。不是重新实现整个 TPU；仿真作为冻结裁判，不同时让 agent 修改评价模型。此建议针对新增硬件目标，不撤销前文 ORT/ZigZag 作为其他类别的候选。
- 本轮读取本地 main 引用 `7e42a626f714edd07867702c38c954082d51f587`、vtree/fpipe/mxu 源码、fp32.py 语义和浮点/量化 RTL 回归；git -C 受权限限制，版本来自 `.git/refs/heads/main`，未校验工作树与提交完全一致。没有构建、仿真、综合或测量。在线查阅 FeSens/openTPU README 与 RTLScout v3（2026-09-14）摘要。
- 已知 vtree 接收64个部分和，按 LANES 分拍输入，有 en 暂停与输出有效标记；存在资源复用和特殊配置路径。可抽取独立时序契约，建议首题固定8路与数值加法原语，仅开放调度、复用、缓冲与流水组织。严格保留归约配对、舍入、特殊值语义；不能将任意加法重排当作等价。
- 给执行者：自洽语义/接口/合法输入节奏、复位暂停规则、固定延迟或明确延迟上限、吞吐下限、数值原语、工具链与目标库、公开测试及开发评价反馈。隐藏：参考模块RTL、优化说明、历史提交、参考成绩、最终留出。规格中的数学归约树必须公开；其物理调度不公开。新执行上下文不继承本选题讨论，也不挂载完整来源仓库；不能声称排除了训练数据记忆。
- 评价建议：正确性先行，冻结吞吐/延迟/时钟约束后最小化映射面积；OpenROAD物理验证用于最终候选。选 ASIC NanGate45 时原实现也必须在同一流程重测，只称移植到同一ASIC目标后的比较，不能与原FPGA LUT/频率直接比较，也不称硅后实测或功耗优化。
- 从规格开始是设计生成加优化，首个正确实现与后续优化分开记录。ArcHa与同预算、同模型、可自主多轮的直接Codex比较才能判断框架收益；仅和openTPU比较只能判断设计质量。至少重复运行以分辨随机性；所有准备和执行成本分别记录。
- 减法：删掉整机复刻、同时改仿真器与硬件；推迟DDR/PCIe、整MXU、板级部署与功耗结论。竞争路线是固定RTL的快速周期预测模型，适合研究建模误差与查询成本，但无法单独证明设计优化能力。若模块预检显示优化余量不足，承认结果，不削弱参考实现制造收益。
- 下一步：制作不泄露解法的模块规格和外部judge设计，先验证参考模块可独立仿真/综合，再冻结实验卡。当前独立抽取成本、时序门槛及改善余量仍未知。
- 来源：[vtree](https://github.com/FeSens/openTPU/blob/7e42a626f714edd07867702c38c954082d51f587/rtl/vpu/otpu_vtree.sv)、[fpipe](https://github.com/FeSens/openTPU/blob/7e42a626f714edd07867702c38c954082d51f587/rtl/vpu/otpu_fpipe.sv)、[RTLScout v3](https://arxiv.org/abs/2606.06530v3)。后者已有 agent+EDA 反馈路线，因此不能把“agent优化RTL”本身声称为新贡献；本轮只读摘要，未复现。

- 最新完整交付：[五候选与实验卡](../../../research/20261025-real-cases-experiment-design.md)。工程主推荐为ORT DistilBERT受约束CPU部署；探索主推荐为ZigZag固定架构的有限预算低能耗temporal mapping。备选openTPU编译器内存/布局、SCALE-Sim快速模型；Roll策略研究推迟。替代下文旧主推荐次序，历史证据保留。
- 已核openTPU HEAD `7e42a626`：已有位精确ISA、Verilator RTL以及专用offload模型；ISA Lens无周期模型，不能用其时间线宣布硬件加速。compiler已有next-fit/best-fit与bank-aware stride，不能以重新实现已有机制造收益。
- WSL2发行版SchedResearch-R12可进入，Ubuntu24.04.4、Python3.12.3、16逻辑CPU/约13GiB RAM，可读/mnt/d项目，PyPI HTTPS可达；直接进程找到git/cmake/ninja，未找到g++/Verilator，系统Python未发现numpy/pytest/ORT/torch/zigzag。仅环境探针已执行，未迁移、安装或实验。
- ZigZag3.9.1 `7f918832`源码存在SALSA内外latency目标及total0/total2口径差异，LOMA/SALSA也非相同LPF合并域；首卡选择energy_total，冻结共同域。ORT当前stable v1.31.0 `402979ac`，模型/数据revision固定于工程附录。
- 对照共同规则：直接Codex允许自主多轮；ArcHa启动后外部仅观察；强基线、独立judge和留出冻结；map/task/onboard与执行期分别计账并有端到端总成本；不要求最少N轮，不预设ArcHa胜出。
- 主卡建议每臂4小时/250k token是待审资源上限，非实测耗时；中立预检若显示标准方案饱和，承认案例区分度不足，不削弱基线。下一步先审阅部署约束和能耗目标，再由用户决定是否实施。

## 前序范围：领域工程与建模（保留讨论演进）

- 用户方向：端侧架构、编译器与推理；性能建模、架构建模也可。环境：Windows、无独立GPU、无RTL仿真。数学/竞赛题退出主候选。
- 当前建议：[CPU/架构/Roll方案](../../../research/20261025-domain-benchmark-proposal.md)。主候选是实测驱动的CPU推理成本模型、ZigZag预算化mapping搜索；ONNX选择性量化/图优化及SCALE-Sim代理作备选。
- 模型内架构效果与真实CPU测量分开，不承诺无硬件时的硅后精度。ZigZag官方有Windows安装说明，但本机尚未运行。AccelForge有本地源码但复杂本地依赖未验证，不当首个入口。
- Roll为可选应用案例：已有真实SMA探索回测，短窗/少交易不足策略结论。沿ADR0005独立助研，先可靠逐日回放再比较样本外策略；Markov不是强制，事后最优不能当可执行策略。
- 本轮只调研/方案，不安装、不编译、不运行新benchmark，也不改Roll或架构工具实现。下一步先审实验卡，不默认启动。

## 目标与当前状态

用户要求先调研NVIDIA“Pi-SOL”和其他自我进化框架用什么测试cases。前序纠正：FT06常一轮完成，不能充作主要搜索优化任务；用户要求先方案，不能立即实验。本专题沿用这两个约束。

2026-10-25核实项目为SoL-Pi，结合官方论文/项目页/仓库调查ShinkaEvolve、FunSearch、AlphaEvolve、OpenEvolve、autoresearch、DGM、ADAS和RD-Agent。

## 证据与判断

完整调查：[自我进化测试案例调研](../../../research/20261025-self-evolution-benchmark-survey.md)。

- 改任务解法与改agent/harness是两个层次，ArcHa当前优先对照前者。
- SoL-Pi开发环境与最终benchmark隔离；其内核任务与本仓库kernel-opt同源，不当全新case。
- 优先借ALE-Bench从强解继续优化、AlgoTune等价提速、EdgeBench真实长程工程案例；不是先造更弱初始解来制造改善。
- 推荐候选为AHC039/AHC025、少量AlgoTune任务、integer_compression_codec/ann_vector_search_qps；当前是来源核实与初步适配判断，未验证本机完整judge/镜像。
- 金融研究参考RD-Agent的股票池/跨年独立评价，近六个月单股收益反复调参暂缓。

## 减法记录

- FT06留作流程smoke，主效果验证不继续加码。
- 不先搬全量EdgeBench、不启动GPU训练或多agent大群，不把官方预算成绩搬到缩短预算实验。
- 不因这一轮调研增加ArcHa角色、状态协议或防御框架。
- 轮数不作为主要成绩；用质量—时间/token曲线、独立复验与同质量成本判断收益。

## 下一步

先向用户交付案例来源、任务和评价差异；若进入实验设计，再审阅候选task/judge与资源预算，形成实验卡后决定实施。本轮不启动新实验。
