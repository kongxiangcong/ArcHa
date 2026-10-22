# 项目说明：<display_name>

> 起草者：Ge；生成时点：识别项目根、只读盘点已有文档与源码之后。
> 来源权威：用户材料、已有项目规范、固定版本代码；未知项明确保留未知。
> 关联 JSON：`.opc/project.json`（`opc.project.v0.2`）。此说明不等于接入就绪或执行授权。
> 保存位置：`.opc/context/PROJECT.md`。用户无需手填，Ge 抽取并列出需要决定的缺项。

## 项目身份

| 字段 | 提取值 |
| --- | --- |
| project_id / display_name | <稳定小写 ID> / <名称> |
| components | <component_id 列表> |
| adapter_id / execution_enabled | <适配器或 unconfigured> / false |
| protocol_version / control_root | opc.v0.2 / .opc |
| artifact_store_alias / workspace_store_alias | artifacts / workspaces |
| baseline_policy | clean_commit_or_explicit_snapshot |

## 方向与已有材料

- 项目解决的问题与主要交付：<用户意图，不提前承诺尚未测得的能力>。
- 当前观察：<已见源码、接口、测试；区分观察到、独立验证过、未知>。
- 本轮范围与排除范围：<链接 REQUIREMENTS 中需求与排除理由>。
- 来源：<每项材料的 URI、SHA-256、locator；不得只指向可漂移的分支名>。
- 关键决定：<链接 `.opc/context/DECISIONS.md`；区分已定、授权自主取舍、延后>。

## 接入盘点

| 项目 | 证据 / 缺项 | 状态 |
| --- | --- | --- |
| 源码基线 | <干净 commit，或明确纳入 dirty changes 的快照 manifest> | 未核验 |
| 构建、测试、仿真入口 | <argv、环境前置条件、工作目录由 adapter 配置承载> | 未核验 |
| 输入与评价器 | <版本、摘要、冻结路径、可获取性> | 未核验 |
| 本地路径绑定 | <artifacts / workspaces 已解析；共享文档不填写机器盘符> | 未核验 |
| 权限与资源预算 | <具体 TaskSpec 约束；没有配置不推断无限资源> | 未核验 |
| 最小 preflight | <服务结果 URI / 缺项；尚未执行就写未执行> | 未核验 |

## 下一步

Ge 的下一动作：<补已有材料 / 配置 adapter / 形成 TaskSpec / 运行已授权 preflight>。
自动就绪条件不能从本表勾选推导；服务核验接入配置、路径、工具与权限后登记结果。
已有 OPC 状态时先对账并补缺项，不覆盖初始化；已有项目规范继续作为 standards 轴来源。
领域参数进入具体 TaskSpec 的 `domain` 或 adapter 配置，不增添 ProjectConfig 未定义的 JSON 字段。
