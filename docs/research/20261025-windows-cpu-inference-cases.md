# Windows CPU 推理工程：ArcHa 候选实验方案

日期：2026-10-25。状态：只做方案调研；未安装依赖、下载模型、编译或运行推理实验。证据等级：A=官方文档/模型卡；B=读取源码；C=本机只读观测；D=本次建议，尚未实测。

## 当前机器边界

本机注册表返回处理器名称 `AMD Ryzen 7 7840H with Radeon 780M Graphics`（C）。该命令同时有注册表类型转换警告；CIM读取被沙箱拒绝，故未独立验证核心数/内存/指令集。PATH查找得到Git与Python3.14，没有找到cmake/cl/ninja；这只表示当前shell未发现，不能推断VS工具链一定未安装。未使用集显或假设GPU驱动可用。

官方确认ONNX Runtime提供CPU发行与Windows构建路径；源码构建较重，但图优化/量化实验可使用CPU Python包避免编译整个ORT。官方llama.cpp支持Windows x86/x64/arm64的MSVC或clang构建。[ORT安装](https://onnxruntime.ai/docs/install/)、[ORT构建](https://onnxruntime.ai/docs/build/inferencing.html)、[llama.cpp构建](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)（A）

## 候选1：精度约束的 DistilBERT CPU 图优化与选择性量化（推荐先做）

### 具体问题

固定已训练DistilBERT SST-2分类器，开发一个可重复运行的ONNX优化流程，在精度约束下减少实际CPU推理延迟和模型体积。冻结线程数、执行provider、输入tokenization及最大长度，开放**依据激活误差与profile选择量化节点、量化粒度、校准策略和图改写**；不是线程/批大小网格搜索，也不重新训练或换模型。（D）

模型选发布方维护的 [distilbert/distilbert-base-uncased-finetuned-sst-2-english](https://huggingface.co/distilbert/distilbert-base-uncased-finetuned-sst-2-english)；数据用 [Stanford SST-2](https://huggingface.co/datasets/stanfordnlp/sst2)。模型卡列出91.3%开发集准确率，但实验以锁定模型和本机FP32结果为参照，不能直接拿模型卡分数作验收。（A/D）

### 冻结与可改范围

| 要素 | 建议设计 |
| --- | --- |
| 原始模型 | 开始前锁定HF revision、tokenizer与权重SHA；一次性导出ONNX并对齐FP32输出，原件只读 |
| 开发数据 | 从训练数据固定抽取校准样本；validation再按固定ID切分搜索反馈集和一次性最终留出集。此处是**工程优化留出**，不声称相对预训练/finetune完全未见 |
| 可改文件 | `optimizer.py`及明确列出的图改写模块，输出候选ONNX；不改权重来源、tokenizer、输入长度、评测脚本和标签 |
| 基线A | 原始FP32 ONNX+ORT最高可用原生graph optimization；不能故意关闭默认优化制造优势 |
| 基线B | 官方现成dynamic INT8方案；若有静态QDQ对照亦单列，不拿只会调用quantize API的结果冒充进化能力 |
| 正确性门 | ONNX结构检查、所有输入有效；在开发/最终集对FP32准确率下降不超过预先约定门限，另记录标签翻转和logit偏差；建议1个百分点只是待校准值 |
| 优化指标 | 固定长度桶32/64/128、batch1为主，报告热推理p50/p95、各桶最差退化、模型大小和工作集；主指标用预先固定桶权重的延迟比 |
| 禁止捷径 | 缓存具体样本输出、利用标签、截短输入、减少精度评价集、改变计时边界 |

官方ORT量化文档提供dynamic/static API、MinMax/Entropy/Percentile校准，并提供 `qdq_loss_debug` 的权重与激活匹配接口；其建议是在预处理中做模型优化，避免量化期间图重写破坏误差定位。CPU文档推荐S8S8 QDQ起步，指出S8S8 QOperator在x86-64一般较慢。这些提供“诊断→定位精度损失→选择性回退→复测延迟”的真实反馈链。[官方量化与debug文档](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)（A）

环境负担：ORT CPU、ONNX、tokenizer/数据读取；若缺现成可信ONNX，需要一次性CPU PyTorch/Transformers导出，下载与磁盘负担高于纯ORT运行，但不需GPU/C++全量构建。需先核对现有Python与稳定CPU wheel兼容性，不直接默认Python3.14可用。（D）

难度判断：比单次全INT8转换有更多机制空间，但仍可能被现成方案一轮解决。正式比较前应预声明淘汰条件：若官方量化基线已在所有长度桶满足目标且候选改进空间很小，撤掉该题，不事后降低目标或要求强行多轮。（D）

## 候选2：llama.cpp/ggml 量化CPU kernel优化（更贴近底层推理）

### 具体问题

在锁定llama.cpp版本下，优化AMD CPU上的一组Q4_K/Q8相关矩阵向量/小批矩阵乘热路径。可探索SIMD实现、分块、访存复用、布局/打包与安全的形状分派；保持算子语义和量化格式，冻结线程、编译器、flags、CPU backend。第一阶段以算子组评价，第二阶段用真实小模型验证端到端收益。（D）

模型建议发布方提供的 [Qwen/Qwen2.5-0.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)，固定一个量化文件与SHA，不换量化等级争取速度。先用小模型降低内存和每轮等待；不把它的收益外推到手机ARM或所有模型。（A/D）

### 评价和范围

| 要素 | 建议设计 |
| --- | --- |
| 算子输入 | 多组真实模型维度，覆盖decode的M=1与prefill小批量；开发与留出维度/随机seed分离，覆盖尾块、对齐边界和非连续stride |
| 可改范围 | profiling后指定 `ggml/src/ggml-cpu/` 下实际调用的量化dot/matmul相关实现，精确到函数/文件；不得顺手更改API、测试容差或模型 |
| 正确性门 | 上游 `test-backend-ops` 对照CPU/reference数值输出；额外冻结目标类型/边界测试，误差容限预先锁定；最终固定文本下检查logits偏差/困惑度漂移 |
| 基线 | 未改动上游Release CPU构建，与候选同编译器/flags/线程/模型；编译时间作为研发开销另计 |
| 主指标 | 多维度kernel latency加权几何均值，且任何关键维度退化不得超过固定上限；不能只选最有利形状 |
| 端到端 | `llama-bench` 的prompt-processing与text-generation分开，固定pp128/pp512、tg128等开发负载；留出pp256及不同context depth；强制CPU路径 |
| 复验 | 新进程、交错运行baseline/candidate、相同电源策略和热身，保存每重复值、均值/中位数与离散度；独立检查源码无测试识别或结果缓存 |

`tests/test-backend-ops.cpp` 源码明确提供跨backend一致性测试和perf模式，命令解析支持 `test`/`perf`及 `-o` 算子过滤；已读该入口和说明，未运行。[官方测试源码](https://github.com/ggml-org/llama.cpp/blob/master/tests/test-backend-ops.cpp)（B）

官方 `tools/llama-bench`（旧examples路径已失效）支持pp/tg/pg三类测试、repetitions，输出t/s及标准差，JSON等格式还包含单次重复结果。故计时可以保留原始分布，不能仅看一条屏幕吞吐数。[官方benchmark README](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench)（A）

环境负担：需可用Windows C++工具链、CMake、一次CPU Release构建及模型下载。之后只重编受影响目标。现有shell没有确认工具链就绪，属于方案前置检查，不是已跑通。ggml已有大量优化，可能没有轻易收益；这恰好允许观察研究失败/假设推翻，不能承诺ArcHa必胜。（D）

## 两题如何测 ArcHa 与直接 Codex

固定初始源码、模型与评价器，两臂都可自主修改和开发集复测；ArcHa严格经map→task→loop，启动后外层观察者只记录。直接Codex使用长会话自主迭代，不限制一次提交。累计质量/时间/token曲线优于“达到某个简单阈值就立即结束”的单点比较；最终留出反馈不再回流。框架修复或环境干预保留原失败及成本，修复后新运行单列。（D）

## 更贴近“性能建模”的首选变体：ORT CPU成本模型

若用户当前焦点是架构/编译器性能建模而非直接改kernel，首选任务改为：**根据ONNX图结构、shape、dtype与固定CPU配置预测端到端推理延迟，并用预测选择执行方案**。主目标是未见shape/graph家族上P90相对预测误差，辅以配置选择regret与模型预测耗时；线程数等可以是模型输入/受预测的配置，不能把完成小网格穷举当作研究成果。（D）

数据设计：冻结MatMul、attention子图、Conv/Depthwise、带Transpose/Reshape的复合图及真实DistilBERT子图，既有单算子又有融合/访存主导例；按graph家族及shape区间留出，不能随机拆近重复样本。开发者可改特征提取、解析计算/带宽项、融合和布局开销模型、轻量残差拟合；不能改实测数据、评价划分或用留出延迟拟合。基线包括FLOP/带宽roofline和逐算子查表相加，而非恒常预测。每个候选输出可重放预测与机制说明。（D）

官方ORT可通过SessionOptions开启profiling并导出JSON trace，支持查算子/线程执行信息。[官方profiling文档](https://onnxruntime.ai/docs/performance/tune-performance/profiling-tools.html)（A）。**profile节点dur求和不能当端到端真值**：并行、调度、融合、计时探针和session运行开销会让两者不同。真值应来自独立、关闭profiling的热身后整次 `InferenceSession.run` 墙钟，输入构造/加载/编译另计，定义是否包含IO copy；trace只帮助模型解释。基线和候选在同一Windows机器测得的数据才能比较，不外推ARM/NPU。（D）

最终建议顺序：①ORT CPU成本模型；②精度约束的ORT量化/图改写；③Windows编译链确认后再做ggml底层kernel优化。成本模型减少先搭RTL的负担，但仍需要真实CPU采样；本轮只提出方案，没有采样或宣称可达误差。（D）
