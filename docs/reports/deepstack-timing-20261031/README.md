# DeepStack 调优选题计时预检

日期：2026-10-31。用户明确授权比较 GEMM 与 DRAM 建模耗时；本次为选题资格预检，不是 ArcHa 正式考试，也未修改或优化上游实现。

## 判断

推荐下一步将调优题聚焦到 **独立 DRAM bank 评估器的等价加速**，以地址/sector 生成、bank/row 分组、行请求合并与服务时间评估为核心，布局搜索作为应用负载。GEMM 的 L2 复用距离估计器保留为备选。此推荐尚不等于已测得可实现的加速倍数。

默认 tiling 的主链 GEMM 单次评估较快，但小 tile 路径与候选扫描不快，不能笼统淘汰 GEMM。DRAM bank 路径有更容易独立定义的确定性语义、可复查中间统计，以及无需只靠极端输入就能形成的批量耗时，因此更适合作为首个调优模块题。它是独立验证 oracle，未接入默认 coarse 主链；优化它不能宣称加速了 DeepStack 端到端推理建模。

## 环境与方法

- 从 `/root/DeepStack` 的 Git 对象用 `git archive` 导出固定提交 `17e21bf54115e11b9e7c6edc0b2d1723d25d022b` 至 `/tmp/archa-deepstack-timing/source`；没有使用原工程未提交修改。关键文件摘要见 `source-sha256.json`。
- 本会话机器：2 vCPU，暴露的 CPU 型号为 Intel Xeon Gold 6133 @ 2.50GHz，Linux x86-64。没有访问其他已部署服务器；数值不代表别的机器。
- `/tmp` 独立虚拟环境：Python 3.11.18；使用上游 requirements 的全部固定版本。完整解析依赖见 `requirements-resolved.txt`。
- OMP/OpenBLAS/MKL 与 Torch 设为单线程；布局搜索串行；模型版本为 `current_corrected`。第二轮 NumPy RNG 从 seed 0 启动，流在各调用间正常推进。
- 每项先测第一次调用，再测 7 组热运行；快调用按第一次耗时决定每组次数（至多 100），结果为每次平均值的中位数。没有扣减空循环时间。各项有 45 秒整项上限。输入对象构造、模块导入、文件输出、profiler 均不计入表中调用时间。
- 主结果在 `confirmed/timings.json`；每项含所有采样、第一次耗时、参数与输出摘要。`confirmed/*.profile.txt` 是额外单次剖析，存在插桩开销，其绝对耗时不能代替计时结果。
- 首轮导入约 8.76 秒，第二轮约 2.94 秒，另计在 environment.json。它们是依赖导入时间，不是建模函数耗时，也不是清空系统缓存后的严格冷启动测量。
- 本预检覆盖有限输入，不测全量 DSE、不验证真实硬件预测精度、不据此承诺普遍最优或最低收益。

## 主要结果

以下均为程序在 CPU 上评估模型所花的墙钟时间，不是模型预测的 GEMM/DRAM 硬件执行时间。

| 场景 | 热运行中位数 | 范围说明 |
| --- | ---: | --- |
| H100 主链 GEMM，默认 tiling | 1.44–2.82 ms/次 | M=1/128/1024/4096，N=K=4096 |
| 合成自有 3D 配置 GEMM，默认 tiling | 0.52–3.48 ms/次 | 同上；配置来自上游公开接口测试，非硬件校准 |
| H100 GEMM，16×16 tile | 266.66 ms/次 | M=1024,N=K=4096；128×128 tile 为 2.82 ms |
| H100 GEMM，27 个候选完整评分 | 2.293 s/轮 | M=64,N=K=512，含上游小 tile 候选 |
| DRAM bank 默认代表性采样 | 4.70–40.38 ms/次 | 方阵 64³ 至 4096³，32³ tile；默认最多 4×4 代表采样 |
| DRAM bank 精确枚举 | 93.46 ms / 632.31 ms | 256³ / 512³，无空间/K采样限制 |
| DRAM 布局搜索 | 382.78 ms/轮 | 1024³，13 个布局，串行 |
| 四种工作负载的 DRAM 布局搜索 | 1.515 s/批 | 4×13=52 个布局评估，各输入不同 |
| 底层 bank sector 评估 | 24.18 ms / 850.29 ms | 65,536 / 1,048,576 个连续 sector；辅助规模检查 |

DRAM 配置是上游 `DramBankSpec()` 的合成参数（8层、8连接层、每层4 bank、4KiB row、128B sector），无 L2 cache，具体参数存于 JSON。四种批量工作负载为 `(128,1024,1024)`、`(256,2048,1024)`、`(1024,1024,1024)`、`(1024,4096,4096)`。

## 热点与竞争解释

- GEMM：已剖析路径的主耗时在 `L2_hit_rate_flow_sim_reuse_distance`，它遍历 tile 网格并更新复用距离。相同 shape 改变 tile 后，调用耗时从毫秒级增长到数百毫秒，支持“细粒度 tiling 增加模型计算量”这一解释，而非导入开销。该实现使用 NumPy 随机排列；若选择此题，必须固定随机输入/状态契约，不能把随机波动当优化收益。
- DRAM：布局搜索热点包含 `touched_sectors` / `_raw_sectors`、`build_bank_histogram`、`service_histogram` 与下界计算。连续百万 sector 的单独测试主要耗时在去重与分组；它只是底层压力测试，不能单独代表完整调优题。
- “耗时高”也可能只是模型要求更多工作，不必然是低效实现。这里只证明热点存在且具备可测绝对成本；是否能在保持输出的条件下明显加速，需要后续候选实现与独立验收证明。
- 不能通过减少采样点、删掉布局、降低统计精度、将精确枚举换成近似来满足等价加速。`runtime_seconds` 这种运行元数据应排除在语义等价字段外，物理预测、布局排序及必要中间统计则需冻结检查。

## 首轮问题与修正

`results/` 保留首轮原件，脚本为 `measure-initial.py`。首轮误用 `tilesight.arch.H100`，缺少主链需要的 `support_utcmma` 属性；五项 H100 测试失败。这是探针选错接口，不是经本次确认的上游故障。第二轮改用主链实际的 `mosaic.arch.h100.H100`，未打补丁，H100 项全部成功。

首轮大 shape 的 108 候选扫描触发整项 45 秒上限，首轮脚本未即时保存首轮单次时间；不能由此声称“一次扫描超过45秒”。第二轮改用较小 shape 测完候选扫描，并补充中等 tile 的独立计时以定位耗时来源。首轮合成配置与 bank 数据仅作辅助，最终表格取第二轮。

安装时普通网络调用失败，经环境允许的提升执行下载后，uv 默认索引优先级不能解析全部固定版本；使用上游指定 PyPI/PyTorch 两个索引的 best-match 解析完成。没有替换依赖版本或修改 requirements。

## 重跑

在已经准备好固定源码和依赖的环境下：

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
TILESIGHT_MODEL_VERSION=current_corrected MPLCONFIGDIR=/tmp/archa-deepstack-timing/mpl \
/tmp/archa-deepstack-timing/venv/bin/python \
docs/reports/deepstack-timing-20261031/measure.py \
  --source /tmp/archa-deepstack-timing/source \
  --output /tmp/deepstack-timing-repeat
```

## 来源

- [固定 GEMM 接口](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/mosaic/op_dtype/gemm_wrapper.py)
- [L2 复用距离估计](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/tilesight/tilesight/util/L2_hit_rate_flow_sim_reuse_distance.py)
- [DRAM bank GEMM 映射](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/bank_oracle/gemm.py)
- [bank 服务模型](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/bank_oracle/engine.py)
- [独立 oracle 边界说明](https://github.com/tile-ai/DeepStack/blob/17e21bf54115e11b9e7c6edc0b2d1723d25d022b/src/deepstack/bank_oracle/README.md)
