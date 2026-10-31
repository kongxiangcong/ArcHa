# 材料入口与环境

`source/README.md` 是固定发行版入口；源码、原始示例、测试与许可均在 `source/`。
`references/deepstack-paper.pdf` 是原始论文。`SOURCE.json` 标明固定提交。
提供完整原始发行版以保留必要调用者和依赖；本题研究范围仍限定存储建模及必要上下游。
运行环境为 CPython 3.11、CPU 依赖，无需 GPU、模型权重或联网。

```bash
python -m pytest -q source/tests/test_custom_arch_profile.py
```

此命令用于环境自检，不构成本题研究交付。`PYTHONPATH` 已由执行入口指向题内源码。
自行建立 `results/README.md` 作为结果入口，链接分析、实验条件、分项数据及 trace；无需每轮写多份报告。
任务验收检查题面要求的解释和证据，参考源码事实与可重放行为，不以报告长度或固定实验次数评分。
