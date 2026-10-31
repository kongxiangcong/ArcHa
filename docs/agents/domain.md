# Domain Docs

本仓库采用 single-context 领域文档布局。

## 探索代码前

- 阅读根目录的 `GLOSSARY.md`。
- 阅读 `docs/adr/` 中与当前工作相关的架构决策。

文件或目录尚不存在时，直接继续。
术语或决策实际确定后，由 `/domain-modeling` 按需创建文档。

## 文件布局

- `GLOSSARY.md`：全仓库领域术语。
- `docs/adr/`：架构决策记录。

## 使用术语表中的词汇

在事项标题、重构提案、假设和测试名称中，使用 `GLOSSARY.md` 定义的领域术语。

需要的概念尚未收录时，先判断是否符合项目用语；确有缺口时，记录为后续 `/domain-modeling` 的输入。

## 标明 ADR 冲突

提案与现有 ADR 冲突时，明确指出对应 ADR 和重新讨论的理由。
