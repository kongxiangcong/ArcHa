# Ramulator 调优题：操作者规格

当前题面见 [TASK.md](TASK.md)，固定输入域、修改范围及性能门槛均在 [公开环境说明](starter/ENVIRONMENT.md)中。构建/验收操作见 [共用说明](../ENVIRONMENT.md)，实际验证见 [准备报告](../../docs/reports/benchmark-preparation-20261031/README.md)。

固定 `v2.0a` commit `be93be78055d922aa1d4d33e15bcc8f2b0c61a9d`、MIT；DDR4_8Gb_x8、DDR4_2400R、单 channel 双 rank、Generic/FRFCFS、AllBank、ClosedRow cap=4、RoBaRaCoCh、时钟比1:1。源码与依赖从 commit 导出，GCC13.3 C++20 Release，其他配置冻结。只改两处公开 cpp 及其目录内新增私有头文件。

保持原版输入注入终止、不排空尾部；请求接受/拒绝、命令周期与原始顺序、请求选择身份、刷新、可观察完成及全部输出统计逐项核对。ReqBuffer 的 size() <= max_size、平局先遇先选、读写切换等原版边界也保持。基线缺陷可另记，不能以修复原行为计入等价提速。

外置探针记录系统 send、Generic 选择/priority/完成及实际 DDR4 issue_command。固定 LoadStoreTrace 不提供用户自定义回调，当前检验覆盖其完成路径和顺序；不外推到未提供的其他前端。观察版无计时用途，需与原版核对统计。候选重构需适配插入点时由操作者核查，不能采信候选自报轨迹。逐事件差分支持已测输入的基线等价，并非所有可能输入的形式证明。

未见实例由外置固定生成器提供，公开输入域一致；核心正确性覆盖 stream/random/samebank/local × 纯读/纯写/混合，含背压、刷新与完成覆盖检查。正式性能使用三族100,000请求、五对交替计时，阈值公开冻结。所有计时在构建完成且无并发压力后运行，记录原始每对耗时/RSS和统计。接近噪声或受干扰时完整重测；不能改门槛或挑有利轮次。

既有 [耗时预检](../../docs/reports/ramulator2-preflight-20261031/README.md)：十万请求随机/顺序/同bank中位约1.261/1.863/10.876秒，百万约12.360/17.878/109.345秒，仅证明成本可测，未证明优化热点或可达加速。不预填解法或最低迭代数。正式考试仍待框架改造和 Worker 工具隔离接入。
