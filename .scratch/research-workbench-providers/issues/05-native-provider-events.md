# 05: 在 L2 实时观察 Codex／DSH 工具事件

**What to build:** 研究者在已展开的 L2 中持续看到 Codex 或 DSH 实际输出的工具活动、用量和诊断。原始日志仍完整可读，未知文本不被伪装成事件，解析或写入故障不会改变研究提交。

**Blocked by:** 02 — 使用 DSH 与 Codex 交叉开展研究；04 — 在 L2 查看四种角色的调用生命周期。

Status: resolved

**规格：** [Research Workbench 与多 Provider 执行](../spec.md)。本票完成原生事件从进程日志到 L2 的正常路径和基本故障隔离；日志洪峰、资源预算和收尾超限的强化行为由 06 交付。

- [x] 旁路尾随器读取文件直写日志，约每 200ms 向统一事件流追加 Provider 解析结果，不将进程 stdout/stderr 改回解析管道，不接管研究调度。
- [x] Codex、DSH 的已支持原生事件映射到六字段 tool、usage、diagnostic 事件，由尾随器统一分配 seq；公共生命周期与解析事件保持可读顺序，最终只在实际进程结束后标示进程结果。
- [x] 普通文本与未支持的原生事件保留原始日志但不生成事件；不从最终聊天提取研究产物，不将任意 JSON 当作已支持事件。
- [x] 处理 UTF-8 分片、跨读取批次的行和进程退出后的剩余内容，避免重复解析或丢失正常尾部事件；已识别事件格式错误提供明确诊断。
- [x] L2 实时追加真实工具开始／结束记录，不将它们合并成可变卡片；Provider、耗时和用量仅展示确实取得的信息，不从自由文本反向解析独立指标。
- [x] custom 不执行 Provider 内部事件解析，仍只显示公共生命周期、必要诊断及原始日志；四角色、重试换流和旧调用提示继续有效。
- [x] 解析异常或事件写入失败只产生必要的简短诊断，标明 Trace 不完整，可停止本次提取但不阻止合法研究产物提交；事件文件不可写时仍有命令／原始日志诊断，不能静默吞错或写成研究失败。
- [x] 通过真实形状原生 JSONL 的替身进程，贯通已安装调用、事件文件、HTTP 和浏览器；覆盖普通文本、未知事件、半行、Unicode、解析异常及写入失败，不新增生产故障注入接口。
- [x] 在既有真实 Provider 联调场景中核对实际可取得的事件与原始日志一致，保留必要证据；不以构造的 JSONL 宣称真实 CLI 事件协议已验证，不为每种故障另跑付费研究循环。
- [x] 生命周期、工具事件和材料展示继续明确区分进程成功与研究提交；观测路径不修改权威研究材料，新增模块纳入已安装运行时。


## Comments

- 2026-11-18：独立文件尾随器与 Codex／DSH 原生投影已纳入安装运行时。stdout/stderr 继续直写日志；200ms、256 KiB 批次、1 MiB 行缓冲和 2 秒收尾为基本边界，洪峰及收尾并发强化交给 06。
- 验证：首个 installed DSH→HTTP 用例先 red（只有生命周期）再 green；`test_native_events.py` 6 passed，含在线 Codex UTF-8 分片／半行／无换行尾部、DSH 工具配对／用量、未知文本、格式错误与事件文件不可写仍提交 probe、custom 隔离、真实 Chromium 打开 L2 后追加工具行且保留原 DOM 行。连同 DSH 与 installed CLI 回归 70 passed；`npm --prefix web run build` 通过。浏览器验收需先构建前端并安装 Playwright。
- 已批准的真实联调：复用 02 的 `/tmp/archa-provider-real/codex-dsh/.../step-01/.expert.log`，实际 Codex `item.started/completed` 解析出 6 条工具事件和 1 条用量，无 schema 错误；未将 fixture 当成真实协议证据。DSH 当前日志尚无原生 JSONL，真实联调项保留未勾选，待 02 的认证／启动结果。未重复运行付费研究循环。

- 2026-11-18：02 真实 DSH 成功日志已核对：正向 Executor 10 条 tool／5 条 usage，反向 Expert 16／5，Finalize 4／3，无 schema 错误。复用 `/tmp/archa-provider-real/{codex-dsh,dsh-codex}/.../step-01/.<role>.log`，通过已安装子进程重放原始日志，事件文件与 Observer HTTP 逐条相等（3 passed）；这是实际日志重放，不冒称原始调用使用了后装的尾随器，也未追加模型调用。保留原始日志和该回放脚本 `/tmp/archa-provider-real/test_replay.py` 供复核。
