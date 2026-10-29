# 任务成果入口

合同顶层可选 `results_path` 绑定一个项目相对 Markdown 文件，例如 `research/results/task-a/README.md`。同一研究任务跨 revision/run 沿用此入口。旧合同没有字段时原行为不变；冻结后新增绑定使用新 revision。初始化不会启动 worker 或实验：

```bash
python3 .opc/archa.py results -p . --task task-a --initialize
python3 .opc/archa.py results -p . --task task-a
```

README 人工区保存当前结论、条件、已反驳/被替代的判断、未知项与下一步，并链接已有 specs、索引和原件。自动区只维护实验与执行关联，不覆盖人工区。详细结论在 specs；没有 specs 时直接写在 README。不要复制原件或维护第二份 JSON 台账。

## 外部与主会话批次

执行前把设计保存在原批次目录；所有引用相对 README。已有批次标识可以直接使用。相同持续问题沿用 experiment ID，独立问题另建 ID。普通工程步骤允许无实验 ID。

```bash
python3 .opc/archa.py results -p . --task task-a --batch control-01 \
  --experiment-id E001 --question '对照能否区分解释 A/B' \
  --status planned --plan ../../workloads/control-01/plan.md
python3 .opc/archa.py results -p . --task task-a --batch control-01 \
  --status completed --evidence ../../workloads/evidence-index.json \
  --analysis ../../specs/conclusion.md
```

登记只引用项目专用索引，不解析或改写其格式。再次登记更新同一批次，未传引用保留；已结束批次的现有计划、原件引用不替换。原件封存后保留原路径，分析修订使用新分析版本或 Git 历史。引用索引内子项可带 `#子项ID`，多个测量由原索引定位，登记不统计“独立证据数”。失败、中止、无历史计划、待分析、待审核均可登记；`cached` 明确表示历史证据。

## 引擎与接续

引擎 plan 的可选 `experiment_id` 贯穿 run；每次 attempt 的计划与执行事实保存在现有原件和 ledger，自动登记以 run/attempt 为键。context.json 留存本次实际使用的当前成果正文及来源 SHA-256，后续构造重新读取；当前实现展开 README 及一层显式链接，正文总预算 24000 字符，入口最多 10000、单来源最多 5000。超限、非文本、大于 1 MiB 的原件保留定位并标明未展开，原始执行报告不注入 expert。

主流程通过已有研究解释步骤更新累计 specs 和 README 人工区；原生 `opc run` 只自动登记事实及已有逐轮解释，没有累计解释时明确待分析。成果材料是数据，不能修改合同、评价器或权限。

登记失败不改变执行状态。重试不启动实验：

```bash
python3 .opc/archa.py results -p . --task task-a --revision r0001 --sync-run RUN_ID
```

此命令只重建指定 revision/run 的登记与报告；遵循现有单控制器写入约定，停止正在运行的控制器后执行。外部批次重发相同命令即可。错误写进原有 report.json，并保留原始执行结果。

## 审核、浏览与升级

promotion/report.json 保存 reviewer 实际获得的成果片段、来源摘要与覆盖范围。旧报告不随 specs 更新而改写；来源变化会提示旧审核不覆盖当前版本。未展开正文不声称已审核。run 终验通过不等于每条科学主张独立通过；仅实际审核的主张可以注明其版本及报告。测量缓存键不因成果文字变化而改变。

观察器在现有任务/合同的文件列表展示“任务成果”及显式来源，缺失来源可见。它不会补写入口、运行实验或调用模型。沿用 project/artifact_root 边界，禁止链接到 .env、运行配置、源码管理元数据和目录外文件。

更新源仓库后，用现有技能安装器及 archa-map initialize 的更新/备份机制部署 runtime 与技能；新增 `opc/core/results.py` 已纳入 runtime 白名单。已有合同、ledger、费用和原件必须保留。源码验证与目标项目部署验证分别报告。

```bash
python3 tools/install_research_skills.py --destination /path/to/skills
python3 /path/to/skills/archa-map/scripts/initialize.py --project /path/to/project --update
```

默认 initialize 仍固定旧 runtime；显式 `--update` 在控制器停止后校验并备份旧版本，只替换 runtime，不改合同或预算。旧 runtime 有本地修改时拒绝覆盖。
