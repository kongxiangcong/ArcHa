# 给外部评测Codex的提示词

在参试者均停止、最终提交哈希已封存后执行。读取deployment/PROTOCOL.md与LINUX.md。以独立评测身份，从direct最终commit和ArcHa引擎champion commit提取rtl/*.sv，记录哈希；不要取最后工作区里的失败候选。把它们送入可信模板中的统一评价器，使用预先封存seeds.json；参考与starter同样重测。

对每次重复调用external-eval/judge.py生成summary.json，再用summarize.py核对工具链/冻结规则/隐藏种子一致并汇总。报告所有重复，不根据隐藏反馈选择中间候选，不反馈给已经结束的参试组。对功能失败、时序失败和基础设施故障分别列出原因。

补充端到端和各阶段wall time、所有模型调用token、评价次数、停止原因与任何干预。核查ArcHa确实map→task→loop，loop期间外层仅观察。预算覆盖不全或发生人工研究干预时明确降级，不能声称严格自主或等预算优势。只对合格设计比较面积；把相对朴素基线与相对openTPU的收益分开。不把综合估计写成真实芯片PPA。
