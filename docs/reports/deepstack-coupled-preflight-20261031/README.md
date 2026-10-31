# DRAM 共享端口与 FIFO L2 组合资格预检

2026-10-31。用户同意扩展调优题后，执行有限资格预检；没有修改候选实现，也没有启动 ArcHa 正式考试。

## 结论

七组配置均可运行，21 次独立子进程中结果一致；同一进程内冷/热调用及插入另一物理配置后再调用，完整 dataclass 结果指纹也一致（排除 `runtime_seconds`）。共享端口与 FIFO L2 的组合存在可测计算成本，支持将它们纳入已确认的扩展范围。结果只证明当前配置的可运行性与重复稳定性，不证明完整正确性、优化上限或必须多轮才能完成。

| 配置 | 首次模型调用中位数 | 紧接的热调用 | 子进程峰值 RSS |
| --- | ---: | ---: | ---: |
| 256³，全连接，无 L2 | 29.3 ms | 27.9 ms | 99.7 MiB |
| 256³，8层中2层连接，无 L2 | 46.5 ms | 45.0 ms | 99.8 MiB |
| 同上，8 KiB FIFO L2 | 204.8 ms | 152.9 ms | 100.4 MiB |
| 同上，128 KiB FIFO L2 | 178.7 ms | 129.5 ms | 100.4 MiB |
| 同上，关闭 output pressure | 164.1 ms | 124.9 ms | 100.7 MiB |
| 512³，部分连接＋128 KiB FIFO | 1.116 s | 0.883 s | 104.1 MiB |
| 128³，部分连接＋32 KiB FIFO，13布局搜索 | 260.5 ms | 234.7 ms | 101.4 MiB |

## 方法及适用范围

- 沿用[前次基线](../deepstack-timing-20261031/README.md)：固定提交 `17e21bf54115e11b9e7c6edc0b2d1723d25d022b` 的 `/tmp` 干净副本、Python3.11.18及固定依赖、2 vCPU会话环境，OMP/OpenBLAS/MKL单线程。
- 每组配置使用3个新子进程，串行执行；每个子进程导入和构建公共输入后，清空上游 L2 trace memoization，测一次首次调用及一次热调用。超时为每个子进程45秒。缓存构建在首次模型调用内；导入和输入构造不计时。这是资格探针，不是正式规格中的完整模块导入/初始化计时协议。
- 再用不同 connected_layers 调用一次，然后回到原输入，检查结果不受调用历史污染。这里只验证物理配置变化的一种情况，尚未覆盖全部 cache key 维度。
- 对全部 dataclass 字段递归序列化并计算SHA-256，排除运行时间字段；数组保留dtype、shape及数据。对相同输入要求位级相同的序列化结果，含布局搜索的完整候选列表与best；这不是候选优化的最终字段容差方案。
- RSS为子进程全生命周期峰值，包含依赖导入、两次计时调用及配置变化检查，不能解释为模型单次增量内存。当前仅支持“这些探针约100–104MiB”的结论，不能直接冻结所有最终输入的内存上限。
- shape为方阵，tile=(32,32,32)、stage=2、8 CTA/wave。除连接层数和L2选项之外，使用上游合成 `DramBankSpec()`；无真实硬件校准。完整参数及每次原件见 `results.json`。

## 观察与验收影响

1. 上游已经有 `_cached_gemm_l2_trace`（最多8项），用于复用完整FIFO trace；搜索内不同swizzle可以复用。此次保留既有缓存，首次调用与热调用分别记录。正式基线也必须保留该能力，不制造一个较弱版本来获得容易的提升。
2. 小规模带L2输入触发上游 `l2_exact_profile_threshold=4096`：256³从无L2的20个bank profile变为72个，512³为544个。因此表中的差异同时包含FIFO和profile策略变化，不能把时间比直接解释为“L2自身开销”。优化时须保持这一策略及其输出。
3. 256³从全连接改为部分连接，预测周期从4272变为8952；加入128KiB L2后为5880，读流量从2359296字节降到1310720字节。这些是模型内观察，说明机制影响了结果，不是真实硬件测量。
4. 本组256³输入中output pressure开关没有改变输入命中率或总周期；不能因此声称它无作用。既有边界测试 `test_output_pressure_can_evict_an_otherwise_reused_a_tile` 使用精心设置的容量，检查其确实能改变A命中与DDR流量；本轮该测试通过。最终输入集需保留这种机制有区分度的小例子，而不只选慢输入。
5. 某些负载一次调用仍很快，应该保留用于检查小输入退化。重路径用于衡量收益，小路径和边界用于约束正确性与固定开销。

## 功能资格检查

计时结束后独立运行固定源码的 `test_engine.py` 与 `test_l2_cache.py`，排除唯一的 `process_backends` 测试（本题限制串行）。所选测试全部通过，退出码0；原始输出见 `upstream-tests.txt`。其中包含地址标量参照、部分连接行为、FIFO独立参考、output pressure边界和确定性检查。

这些是上游回归，不等于已经建立本题独立最终验收。共享端口更广组合、非方阵/非整除、不同bank/row几何、L2容量边界与字段容差仍应在材料准备阶段补齐；不把本次结果用于隐藏留出验收。

## 重跑

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
TILESIGHT_MODEL_VERSION=current_corrected \
/tmp/archa-deepstack-timing/venv/bin/python \
docs/reports/deepstack-coupled-preflight-20261031/probe.py \
  --source /tmp/archa-deepstack-timing/source \
  --output /tmp/deepstack-coupled-repeat
```

```bash
PYTHONPATH=/tmp/archa-deepstack-timing/source/src/deepstack:/tmp/archa-deepstack-timing/source/src/tilesight \
/tmp/archa-deepstack-timing/venv/bin/python -m pytest -q \
  -o cache_dir=/tmp/archa-deepstack-timing/pytest-cache \
  /tmp/archa-deepstack-timing/source/src/deepstack/bank_oracle/tests/test_engine.py \
  /tmp/archa-deepstack-timing/source/src/deepstack/bank_oracle/tests/test_l2_cache.py \
  -k 'not process_backends'
```
