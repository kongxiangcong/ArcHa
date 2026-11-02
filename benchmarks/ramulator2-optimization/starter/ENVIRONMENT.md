# 运行入口

源码位于 `source/`，固定版本见 `SOURCE.json`。项目提供离线 C++20 工具链依赖。

```bash
./build.sh
python workloads.py --output results/random --pattern random --count 10000
./build/ramulator2 -f results/random/config.json
```

生成 trace 不计入正式性能时间；仿真计时包含启动、读 trace、初始化和统计输出。
原版 LoadStoreTrace 在输入全部被接收时结束，不排空尾部队列，必须保持这一规则。
公开调试可使用 stream/random/samebank/local，最终验收使用同一输入域的未见实例与读写组合。
修改仅限 `source/src/dram_controller/impl/generic_dram_controller.cpp`、
`source/src/dram_controller/impl/scheduler/generic_scheduler.cpp`，以及这两个目录下新增的私有 `.h` 辅助文件。
其他源码、构建配置和运行配置冻结。勿以改时序、容量、采样或统计换取加速。

结果入口自建于 `results/README.md`；只记录必要结论和证据链接，原始数据按需展开。
正式验收会在正确性构建中加相同只读探针，比较接收尝试、实际命令、请求身份、完成与刷新事件及全部统计；计时使用无探针 Release 构建。
提交中须保留探针可识别的系统/控制器接口；内部重构若改变探针插入点，提供定位说明，由操作者核对后适配，不以候选自报轨迹代替验收。
评价为多类负载速度比的几何平均；必须全部正确、平均速度比超过 1.05、每族速度比不低于 0.95，且成对时间的波动足以支持收益。不能只报告最有利负载。
计时使用同机同核、交替顺序至少 5 对；若接近噪声范围则增加重复或标为未证实，不放宽阈值。

至少五组交替配对计时，还要求至少四组跨三类负载的综合速度比大于 1。记录每类速度比及离散范围；不稳定时排除干扰后完整重测。正式默认每类 100,000 请求，事件核对另用小实例，构建与生成输入不计时。
