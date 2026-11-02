# 通信代价接口

入口：`model.estimate(config, traffic) -> dict`。只需 Python 3.11 标准库。
`runner.py` 是固定 JSONL 适配器；只修改 `model.py`，可增加私有辅助 `.py` 模块。

## 输入与单位

- ring：`{"topology":"ring","nodes":4,"bandwidth_bytes_s":10,"hop_latency_s":0.1}`。
- mesh：`{"topology":"mesh","rows":2,"cols":3,"bandwidth_bytes_s":10,"hop_latency_s":0.1}`。
- 节点编号从 0 开始；mesh 为行优先 `r*cols+c`。ring 的 nodes 为整数且至少 2，mesh 的 rows/cols 为正整数，允许单节点。
- traffic 为 N×N 矩阵，每项是非负整数字节数，不能把布尔值当作整数。每条有向流同时开始。对角线流量为本地访问，不占链路、不产生 hop 时间。
- 默认带宽是有限非负数，单位 bytes/s；默认 hop 延迟是有限非负数，单位秒。
- 可选 `links` 数组覆盖特定有向物理链路，例如 `[{"src":0,"dst":1,"bandwidth_bytes_s":5,"hop_latency_s":0.2}]`。两项覆盖值均须提供；链路必须存在且不得重复。未覆盖的边使用默认值。

## 路由与组合语义

ring 采用双向最短跳数路由，等距时走编号递增（模 N）方向。N=2 时同一有向边只计一次。
mesh 采用无环绕的维序路由，先改变行、再改变列。物理链路全双工，两个方向独立计费。整条流走固定路径，不拆分，不取整流量。

每条有向边的 `link_bytes` 是经过它的非本地流量之和。
`hop_time_s` 是所有有正流量的非本地路径中逐边延迟之和的最大值。
`link_time_s` 是所有使用中链路的 `link_bytes / bandwidth_bytes_s` 的最大值。
`total_time_s = hop_time_s + link_time_s`。无非本地流量时三项时间都是 0。
使用中链路带宽为 0 时抛出 ValueError；未使用的零带宽链路合法。

返回 `{"link_bytes":[[src,dst,bytes],...],"hop_time_s":...,"link_time_s":...,"total_time_s":...}`。
只列出有正流量的边，按 `(src,dst)` 排序，字节数保留整数。不得修改输入。
缺字段、未知拓扑、非法维度/节点/边、非有限数、负值及错误矩阵尺寸抛出 ValueError 或 TypeError；缺字段也允许 KeyError。时间比较采用 `rel_tol=1e-10, abs_tol=1e-12`。

## 来源与边界

路由和“最长路径 hop 延迟＋最大链路负载时间”来自 DeepStack 固定提交
`17e21bf54115e11b9e7c6edc0b2d1723d25d022b` 的 `mosaic/noc/noc_topo.py`。
本题公开简化为单层 ring/mesh，规范化返回边表，并显式支持逐边带宽/延迟和错误输入处理；不要求复制上游扩展节点编号、层级端口或全部拓扑。
探索路线自主选择，无需猜测上游私有实现。
