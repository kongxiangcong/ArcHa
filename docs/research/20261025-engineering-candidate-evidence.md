# 工程候选证据：固定精度与输入契约的 DistilBERT CPU 部署优化

日期：2026-10-25。仅调研、读源码和制定方案；未下载权重、安装、导出模型、计时或运行实验。

本附录为源码证据；最终统一实验口径以[主方案的E1卡](20261025-real-cases-experiment-design.md#5-实验卡-e1供审阅)为准。主方案明确采用模型run延迟为主指标，同时报告文本端到端结果；阈值与预算已统一如下。

## 结论及减法

这是比“做一次 INT8 量化”具体得多的工程案例，但仍应列为**有入选条件的推荐**：在固定 CPU 上交付一个可重建的 DistilBERT SST-2 推理产物，在标签精度、动态输入契约和内存预算内，降低真实文本负载的端到端延迟。不能承诺天然需要多轮；若强基线已满足全部需求或没有可诊断的瓶颈，它应转为流程 smoke 或被放弃，不能临时增加轮数或抬高门槛。

首轮不改 ORT C++ 内核，不引入 GPU、QAT、蒸馏、模型权重再训练或跨模型通用优化器；它们会把工程反馈分散到环境或训练。允许逐节点精度分配、量化前处理、合法图改写与 shape 分桶；固定 tokenizer、截断长度、样本、线程数、EP、权重和判定器。

## 固定来源与核实状态

| 资产 | 建议固定版本 | 本轮证据 |
|---|---|---|
| ONNX Runtime | v1.31.0，`402979ac1bef89dcd55add41eaa7277c407599eb` | [tag API](https://api.github.com/repos/microsoft/onnxruntime/git/ref/tags/v1.31.0)核实；读取量化、optimizer 和 QDQ 调试源码，未运行 |
| DistilBERT SST-2 | `714eb0fa89d2f80546fda750413ed43d93601a13` | [模型提交](https://huggingface.co/distilbert/distilbert-base-uncased-finetuned-sst-2-english/commit/714eb0fa89d2f80546fda750413ed43d93601a13)核实；模型卡/目录读取，未读取二进制 |
| SST-2 数据 | `stanfordnlp/sst2`，`8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb` | [官方 API 元数据](https://huggingface.co/api/datasets/stanfordnlp/sst2)核实 SHA；[数据卡](https://huggingface.co/datasets/stanfordnlp/sst2/raw/main/README.md)明确 train 67,349 / validation 872 / test 1,821，test 标签为 -1；未取数 |
| 现成 ONNX | 上述模型 revision 中 `onnx/model.onnx` | [目录](https://huggingface.co/distilbert/distilbert-base-uncased-finetuned-sst-2-english/tree/714eb0fa89d2f80546fda750413ed43d93601a13/onnx)已有文件；未检查 opset、动态轴和可运行性 |

ORT 的 GitHub releases/latest 于本轮返回 [v1.31.0](https://github.com/microsoft/onnxruntime/releases/tag/v1.31.0)，发布时间 2026-10-09；已按该版本重新读取相关源码。正式准备时若版本升级，统一选择并重新冻结，不能让两臂使用不同版本。

已有 ONNX 可减少导出环境负担，但不能不验证就直接作为独立真值。准备阶段以同 checkpoint 的 FP32 Transformers 输出作对照，验证 ONNX 输入语义与 logits；若旧导出有问题，统一重导出并冻结完整导出环境及 artifact hash，费用计入公共准备成本，不计 agent 收益。

## 真实需求与源码支撑

项目层面的需求是“将有准确率的实际模型部署为低延迟 CPU 推理服务/库”。这不是尚未解决的 upstream issue 承诺；ORT 官方文档已讨论量化因额外开销而变慢、精度损失定位和排除敏感节点的问题。[量化文档](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)

读过的源码为：

- [`quantize.py`](https://github.com/microsoft/onnxruntime/blob/402979ac1bef89dcd55add41eaa7277c407599eb/onnxruntime/python/tools/quantization/quantize.py)：dynamic 路径支持 `nodes_to_quantize`、`nodes_to_exclude`、per-channel 和 reduce-range，故“只调用 quantize_dynamic”已是应提供的基线，不是研究成果。
- [`qdq_loss_debug.py`](https://github.com/microsoft/onnxruntime/blob/402979ac1bef89dcd55add41eaa7277c407599eb/onnxruntime/python/tools/quantization/qdq_loss_debug.py)：可以扩增模型输出以采集中间 activation；用于定位 QDQ 精度损失。不能把这份插桩模型的时间当真实部署延迟，也不能假定对所有 dynamic 量化图自动完成张量匹配。
- [`optimizer.py`](https://github.com/microsoft/onnxruntime/blob/402979ac1bef89dcd55add41eaa7277c407599eb/onnxruntime/python/tools/transformers/optimizer.py)：已有 Transformer 融合和 ORT 优化入口。MODEL_TYPES 没有单独 `distilbert` 项；是否可用 BertOnnxModel 完整融合此导出，需要准备阶段验证，不能预先声称一定融合。
- [`fusion_options.py`](https://github.com/microsoft/onnxruntime/blob/402979ac1bef89dcd55add41eaa7277c407599eb/onnxruntime/python/tools/transformers/fusion_options.py)：attention、GELU、LayerNorm 等选项存在；mask 模式对 padding 语义有要求。源码中 right-padding 条件说明了图改写必须与输入契约一起验证。

旧 issue 只能说明历史动机，不能当当前缺陷。尤其主线程已核实 ORT #28552 是已关闭/完成的问题，本题不复活它或要求 agent 重做历史修复。

## 可审阅实验卡草案

**交付物。** `build(input_model, calibration_data, policy) -> artifact` 和 `infer(text_batch) -> logits/labels`，含可重建脚本、量化/改图策略、产物及配置 hash、统一 batch/shape 推理接口。不得输入样本 ID、文件名或标签选择结果；禁止词句哈希查表和按测试数据输出缓存。允许按公开的 batch/sequence shape 选执行图。

**强基线。** 同一 checkpoint 和输入契约下比较：①开启完整 ORT graph optimization 的 FP32；②标准 dynamic INT8（per-tensor 及 per-channel 合理变体）；③标准静态 QDQ 在公开校准集上的可运行方案。若现成 Transformer optimizer 可合法融合，则加入其默认支持的变体。先在开发集选出满足精度/内存约束的最快现成方案，作为主 baseline；全部基线曲线也保留。不能只对未优化 FP32 报提速。

**独立正确性。** 裁判不由候选修改：ONNX checker、接口 shape/type、mask/padding、不含 NaN、重复一致性；纯等价图变换对 FP32 reference 做误差限差分，量化方案用真实 SST-2 标签 accuracy 约束并报告与 FP32 的预测翻转。可测试同句不同 padding/batch 组成结果稳定性。标签精度不能只由 logits 相似度替代。

**建议约束。** accuracy 降幅不超过 1 个百分点，保留配对正确/错误四格表及置信区间；统一主卡提案为peak RSS不超过FP32的110%，完整工件字节不超过FP32的75%。这些是供审阅的部署要求，并非已有用户SLA或已达到指标。若样本量不足支持所需精度等价结论，就扩大独立标注集或将结论明确限于固定样本，不能把“不显著”当等价。

**性能。** 固定 CPU EP、核心亲和性、线程、功耗状态、tokenizer 和最大长度。分别报告①从文本到 logits 的端到端 P50/P95；②预分词 tensor 输入的模型 P50/P95；③峰值 RSS、完整 artifact 字节、冷启动/建 session 时间。异构方案保持请求/文本完全相同。热身、重复、随机交错 baseline/candidate、独立进程 RSS 采样，最终都关闭 profiling。不能缓存最终输出。主分数为通过所有门后各预注册 shape 桶的几何平均加速比，另报最差桶退化，不让一个大桶掩盖小桶恶化。

**开发/留出。** 校准与日常开发选自 train 且按句子归一化去重/家族分组，避免短语近重复跨分区；model 本来在 train 训练过，不能把这里的精度称为模型泛化证据。保留整个 872 条 validation 作为 agent 不可读的最终标签集，不把它拆成更小份反复调优；test 的 -1 不能用于本地准确率。最终阶段还保留未用于选策略的 batch/shape 组合与 padding 情况。如果该 validation 已被先前本地开发查看，则改用独立标注数据，或明确它只算已暴露验证集。公开数据无法排除基础模型预训练见过，因而只宣称“本次 agent 运行未访问”，配合隔离输入和输出查表审计。

**自然多步反馈。** 例：模型文件变小但短句变慢 → 检查动态量化开销或图断裂；只在长句/某层出错 → 区分校准范围不足、敏感层和 mask/shape 语义；排除该层恢复精度但 RSS/延迟回升 → 检查相邻精度边界与融合变化；局部算子快而文本端到端无改善 → 确认 tokenizer/调度占比。只是可能反馈，不预定 agent 必须经历这些轮次；同时承认竞争解释为测量噪声，需独立交错复测区分。

**公平比较。** 两臂拿到同样的 ONNX/权重、baseline 构建脚本、冻结评价器、开发输入和文档快照；同模型、推理强度、工具、CPU 和调用限额。直接 Codex 可持续修改和测试、保留研究笔记。ArcHa 的 map/task 接入不偷带优化指导；外层 Codex 在 loop 后仅记录。最终留出不回流；选冠军依据开发分数，不能用留出挑历史最佳。

**成本与建议研究预算。** 准备需 CPU ORT、ONNX/NumPy、tokenizer、权重/数据；同源 FP32 验证若需 Transformers/PyTorch，属于准备依赖。本轮未安装；不声称需要几分钟。单次评价成本 = 构建产物 + session 加载 + 开发标签前向 + shape 桶重复计时 + RSS 监测，可先小开发反馈，再完整复核；两臂使用相同分层规则，失败候选也收费。统一主方案提案为每臂4小时墙钟及250k总输入+输出token，先到即止；这是资源上限而非所需时间估计，不要求用满或至少N轮。先做公共资格检查，校准一次完整评价实际成本，若预算只够极少有效反馈，应调整任务规模并在正式比较前重新冻结。后续建议3对独立研究启动作探索性对照，不凭一对宣称普遍优势。

**结果承诺边界。** 这是实际 NLP 模型的 CPU 部署任务，贴近推理与图优化，但硬件限于测试机 x86，不能声称 ARM/NPU 端侧性能。若从强基线无提升，保留不提升作为有效结论。若标准 API 已解决需求，则案例多步区分度不足，不能通过削弱 baseline 挽救它。
