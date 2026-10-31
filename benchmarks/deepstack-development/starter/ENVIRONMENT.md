# 环境入口

Python 3.11，仅用标准库。阅读 `INTERFACE.md`，实现 `model.py`。

```sh
python test_public.py
printf '%s\n' '{"config":{"topology":"ring","nodes":2,"bandwidth_bytes_s":10,"hop_latency_s":0},"traffic":[[0,10],[0,0]]}' | python runner.py
```

当前 `model.py` 故意未实现，公开测试失败属于题目起点。外置验收核对功能与边界输入；参考答案不在题内。交付实现、调用说明及必要测试，短结果索引链接详细材料即可。
