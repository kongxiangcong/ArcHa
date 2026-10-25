# DGM 与 R&D-Agent 的实验案例证据

访问日期：2026-10-25。作者：research 子 agent。状态：已读原论文、官方项目页/README 和 DGM 调度源码；未运行任何实验。网页所指 main 未锁定 SHA，不能当作可复现实验版本。

## 1. DGM：进化的是 coding agent，自身不是单个算法候选

主要来源：[DGM 论文 v3，2026-03-12](https://arxiv.org/html/2505.22954v3)，§4、附录 E；[作者官方项目页](https://sakana.ai/dgm/)；[官方代码](https://github.com/jennyzzt/dgm)。

实际 cases：

- **SWE-bench Verified**：真实仓库 issue 修复，含 Django、Sphinx 等，可能跨多个文件；论文任务清单包括 `django__django-10973`、`django__django-11066`、`sphinx-doc__sphinx-7454`。成功指标是任务解决率，而非运行速度。
- **Polyglot**：多语言功能实现；实际任务包括 `go__dominoes`、`cpp__all-your-base`、`java__sgf-parsing`、`rust__variable-length-quantity`、`rust__bowling`，按 ground-truth tests 判定。
- 阶段门：先 10 题确认基本编辑功能；SWE 再加 50 题，达到筛选条件后扩大至 200 题。Polyglot 正文说 10→50，但附录 E.3 写“Additional 50”，这里存在口径差异，应核对仓库列表再执行复现，不能静默消除。
- SWE 的 20%→50% 是上述 **200 题子集口径**，不是全量 SWE-bench。Polyglot 搜索集 14%→38%，最终完整 benchmark 为 14.2%→30.7%；论文不在所查段落明确写全量题数，此处不推断。
- 预算：80 次进化；SWE 使用 Claude 3.5 Sonnet (New)；Polyglot 自修改用该模型、任务评价用 o3-mini；SWE 一轮完整进化约两周、估计 API 成本 22,000 美元。消融约 10,000 美元，**并非等成本比较**。
- 基线：初始 agent、无 self-improve、无 open-ended archive、OpenHands/CodeAct 和 Aider；跨模型、跨 benchmark、Python→其他语言迁移评价补充检查泛化。

[DGM_outer.py 源码](https://github.com/jennyzzt/dgm/blob/main/DGM_outer.py) 可核实：加载 `swe_bench/subsets/{small,medium,big}.json` / `polyglot/subsets/*`，按档案分数筛选扩展评价，默认 `max_generation=80`。这不是严格的隐藏测试全程隔离；跨 benchmark 转移才是论文明确的完全 held-out 测试。任务 agent 不看 Polyglot 真值测试反馈，报告 pass@1，与 Aider 常见 pass@2 口径不同。

复用判断：适合借鉴“任务集解决率＋阶段评价＋独立迁移集”，但单个 Polyglot 功能题仍可能一次解决；它检验的是进化后 agent 在一组任务上的能力，不直接证明 ArcHa 在一个问题中持续改进算法。

## 2. RD-Agent：MLE-bench 上的机器学习工程迭代

来源：[官方论文 v2，2025-10-01](https://arxiv.org/html/2505.14738v2)，§4、附录 C/D；[官方仓库](https://github.com/microsoft/RD-Agent)。

- 主评测 MLE-bench：75 个 Kaggle 比赛，22 Low、38 Medium、15 High；论文 40 比赛子集用于消融，不能当作完整集。
- 实际案例包括 `jigsaw-toxic-comment-classification-challenge`（论文专门分析）、`spooky-author-identification`、`nomad2018-predict-transparent-conductors`、`leaf-classification`、图像/音频任务等。agent 执行特征工程、建模、调参、验证和集成，输出 submission。
- 指标：有效提交率、超过人类中位数比例、铜/银/金牌率、Any Medal；过程还报告 R&D loops、改善轮次比例、首次获牌时间。
- 该论文 v2 主配置是 GPT-5、12 小时、12 vCPU、220 GB RAM、1 张 V100，3 独立种子，Any Medal 35.1±0.4%（SEM）。平均每比赛 Research/Development API 成本分别约 $6.99/$13.75，总 $20.74；该表没有充分说明完整机器/GPU租金是否包含，不能称端到端全成本。
- 对照含 AIDE、OpenHands、ML-Master 等，但跨论文模型/硬件不同。论文另重跑 ML-Master 的同环境配置，须与跨环境排行榜比较分开。
- README 另有 o1-preview/o3+GPT-4.1 的旧配置成绩；版本和模型不同，不把它与 v2 的 GPT-5 35.1%合并。

## 3. MLE-bench 案例、隐藏集与资源口径

来源：[MLE-bench 官方 README](https://github.com/openai/mle-bench)，Dataset、Lite Evaluation、leaderboard submission guidance。

- Kaggle 原始隐藏测试标签通常不可得，因此官方准备脚本从公开训练数据重新切分训练/测试集，评分脚本控制留出标签。
- 官方默认建议每任务24小时、36 vCPU、440GB RAM、1张24GB A10，至少3种子；资源不是硬性要求，但改变必须报告。
- Lite不是“小玩具”，22比赛约158GB，完整75比赛约3.3TB。小数据候选例如 `spooky-author-identification` 约0.0019GB、`detecting-insults-in-social-commentary`约0.002GB、`nomad2018-predict-transparent-conductors`约0.00624GB、`leaf-classification`约0.036GB。这些大小是 README 口径，本轮没有下载验证。
- README 已列明某些数据泄漏、准备错误、排行榜过度拥挤问题。挑案例需逐一检查已知问题，不能把比赛名当作评价器正确的保证。

## 4. RD-Agent(Q)：股票池、多年分割，而非单股六个月优化

来源：[R&D-Agent-Quant v2，2025-09-25](https://arxiv.org/html/2505.15155v2)，§3、附录 C/D；[官方 README](https://github.com/microsoft/RD-Agent)。

- 主实验 CSI300 股票池：2008–2014训练，2015–2016验证，2017-01-01至2020-08-01测试；扩展 CSI500 与 NASDAQ100：2008–2021训练、2022–2023验证、2024至2025-06测试。
- 三条任务：固定LightGBM优化因子；固定Alpha20优化模型；因子/模型联合优化。对照包括Alpha101/158/360、AutoAlpha、传统与深度时序模型。
- 评价同时看IC/RankIC及稳定性、ARR、IR、最大回撤、Calmar。单模块6小时、联合12小时；implementation最多10次内循环、600秒，validation 3600秒。用5随机种子中位ARR评价模型稳健性。
- **RD2Bench** 是更直接的功能正确性案例：40个金融因子任务，27个可实现、13个不可实现；测执行、格式、与参考实现输出相关性，并比较有限 top-k 实现预算下的任务选择。
- 注意原论文交易成本表述不一致（附录C逐项买卖费率与D.1概括费率不同）；若迁移收益评测，须以冻结代码复核。论文“低于$10”指LLM调用成本，不能忽略其CPU/GPU硬件和12小时运行。

## 5. 对 ArcHa 的可迁移判断（推断）

最贴近“单任务内反复研究、实现、评价”的是 MLE-bench 的小数据完整比赛和 RD-Agent(Q) 的股票池因子/模型优化；前者有现成留出评分更容易形成客观比较。DGM 的 SWE/Polyglot 更适合以后评测 ArcHa 自身 harness 改动能否跨任务提高能力。

金融方向可先选 RD2Bench 参考因子实现，或固定股票池/多年切分的因子生成；江西铜业六个月可作为外部案例展示，不能替代股票池泛化评价。这里仅给方案依据，未授权或执行实验。
