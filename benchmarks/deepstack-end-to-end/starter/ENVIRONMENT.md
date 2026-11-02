# 材料入口与环境

`source/README.md` 为原始项目入口；`source/` 含固定源码发行版、原始示例/测试及许可。
`references/deepstack-paper.pdf` 是原始论文，`SOURCE.json` 标明固定源码提交。
环境为 CPython 3.11 和 CPU 依赖，无需 GPU、权重或联网。

```bash
python source/examples/custom_accelerator.py
```

此命令只验证环境可运行；研究路线与深入核对的链路由你选择。
自行建立 `results/README.md`，组织整体解释并链接分项分析、原始证据和未知边界。
验收要求贯通主要模块与输入输出；代表性验证深度可以不同，不要求穷举所有配置或唯一还原不可见公式。
