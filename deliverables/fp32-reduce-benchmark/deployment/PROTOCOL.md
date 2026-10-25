# 实验协议（给部署者和外层协调 Codex）

## 三类身份

1. 部署/评测者：独立OS用户，持有external-eval、原始模板、隐藏seed和参考分数；安装工具，冻结规则，独立评分。
2. direct参试者：只能访问自己的考题副本、固定开发工具和模型服务；可自主多轮实现、测试和优化。
3. archa参试者：外层Codex模拟用户，内层Codex逐阶段调用三个原始技能。二者均不能读取评测私有目录。外层不做研究、不给优化方法、不改RTL。

仅换工作目录不是隔离。使用不同无sudo用户或独立容器/VM；参试者不能访问打包父目录、另一组目录、部署者HOME、外部评测目录、隐藏日志、参考仓库或其Git对象。保留原语许可证，但不给参试者全库。工具文档预置本地；正式运行仅放行所需模型服务、禁用其他浏览/检索连接器。不能证明模型预训练未见过公开代码，报告这项限制。
技能包deployment/skills只安装给ArcHa会话；它含固定runtime。其安装、认证、环境验证均在计时前，不在参试会话中暴露参考结果。清洁HOME/记忆，不沿用本次选题对话。

## 起点与预算

ArcHa源码的ONBOARDING要求正确、可测基线。故两组都收到同一朴素RTL基线，不让外层Codex在map/task之前或之后偷做实现。朴素基线只是合法起点；openTPU固定实现才是成熟参考，不移除其优化来制造改善。
默认每组每次独立运行8小时、100万总token、96次开发评价；三次独立重复，运行顺序交替。部署者在正式会话之前可调整campaign.json，冻结后两组相同。预算不是必须用满的额度，也不是成功承诺。
map/task/onboard和外层模拟用户的成本全部计入ArcHa组；单独列loop。模型/推理强度对齐外层、内层、onboard和expert/designer，固定版本。多agent调用不免费，所有模型使用均汇总。
启动loop前给合同的max_wall_seconds/max_tokens必须是剩余额度，max_attempts=48，max_stagnation=12，max_consecutive_infra=3；不设基于参考成绩的target。外部watchdog可在总墙钟截止时终止整个进程组，这是预先冻结的行政截停，不是研究干预；标记administrative_budget_stop。token和开发评价额度需要外部日志/代理计数，不能依赖提示词自报。部署者验证计数链覆盖嵌套CLI；做不到时仍可运行探索，但标记budget_unverified，禁止声称严格等预算胜出。不能把父会话统计当作所有worker统计。

## 严格阶段顺序

外层Codex作为模拟用户，启动一个真正执行技能的内层Codex会话。两者角色清晰，不在同一段自问自答中假装完成用户确认。可用Codex CLI exec及resume，保存完整JSONL和最终消息，或服务器已有的等价会话控制工具。检查实际CLI --help；不是靠创建预填文档替代技能。

- map：内层调用$archa-map。外层只按SPEC/campaign回答目标、边界、约束和地图组织方式。默认单个主任务，问题树形式；不要求额外实现项目。根据输出明确确认范围，真实记录模拟用户回答。完成研究地图、任务占位和discussion后结束该阶段。
- task：内层调用$archa-task实际地图绝对路径。技能按其规则调研和提出brief大纲，外层只检查契约完整性、排除越界范围并明确确认；不提供资源复用/调度等解题路线。随后由技能生成brief、brief-check、onboard及合同核对，保持execution_enabled=false。需要预算时提供已冻结剩余额度。引擎ID/revision从实际交接读取，不硬编码。
- loop：内层调用$archa-loop实际brief绝对路径。技能自身按原流程完成执行开关、必要Git提交、check和preflight，再调用run。**外层从调用loop起就进入只观察状态**；不改文件/合同、不给提示、不回应研究性问题、不修故障、不人工测试候选、不重启run。不因失败“救场”。技能内部启动前的规定准备步骤不是外层干预；run开始后只有引擎负责研究。
- 终态：保存report、champion、stop reason。引擎blocked/paused/closed及额度耗尽均如实终止本次实验。若需要修复环境，评测者在所有相关组停止后处理并新建campaign，不恢复原轮冒充无干预。

外层遇到SPEC之外会改变实验定义的关键缺口，记protocol_blocked，交给评测者修订整个campaign，不自行补题。正常工程选择交给内层，而非让模拟用户决定答案。

## 评价接入说明（由onboard生成合同，不提供现成合同）

唯一优化范围rtl/*.sv；notes可存研究记录但不影响评分。evaluator_files覆盖SPEC、primitives/**、harness/**、campaign.json、toolchain.json、frozen.json及.onboard生成的薄适配器。开发门调用 `python3 harness/evaluate.py --out {out}/fr64`；该子目录必须不存在。metrics路径为`{out}/fr64/metrics.json`，适配层保留退出码。指标键在metrics对象中。
objective=area_um2/minimize，min_rel_gain=0.001；约束correct==1、wns_ns>=0，repeats=1，deterministic=false；不设置未实测的达成target。环境工具固定在只读共享位置，副本不能修改工具和库。`preflight`不通过就阻塞，不降低标准强行启动。

## 最终提交与结论

各组在开发反馈下选定一个最终Git commit（ArcHa取引擎champion，非最后失败候选），封存源文件哈希后才运行隐藏测试。外部评测只拷贝rtl/*.sv到可信模板；不执行提交者的评测脚本或构建脚本。在无网络、非特权、限资源容器内编译候选RTL。
所有重复都报告，不能只挑最佳一次。公开starter、direct、archa、opentpu四类评分，但后者不是同预算生成组。正确性/时序失败不排名；INFRA与功能失败区分。收益分别相对starter和opentpu计算；原始面积和时序必须同时保留。
三次重复仍是pilot，不能据此断言普遍优越。保存阶段成本、所有模型tokens、开发评价次数、无干预日志与停止原因；缺成本只能比较设计结果。该包只做仿真与综合估计，不宣称形式验证、布局布线、功耗或实际板卡性能。
