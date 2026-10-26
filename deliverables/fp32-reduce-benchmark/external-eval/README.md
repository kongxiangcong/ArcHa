# PRIVATE：仅外部评测者

reference/ 包含固定版本的openTPU归约源码及只做端口连接的包装器。upstream/保存原始下载文件、Apache许可和逐文件出处/哈希。参考在评价时使用与参试者相同的公开add-only原语。

当前没有实测基准分数。运行时先对reference和独立starter做资格检查，再对direct/archa最终提交独立评分。同一个模板、工具链和隐藏种子用于所有组。

隐藏seed在Linux通过deployment/freeze.py生成，权限0600并记录SHA256承诺；当前包不预置最终种子或结果。开发生成器可公开，实际向量与seed在评测账户隔离。测试分布相同并不等于全域形式验证。

judge.py会把候选SV复制进可信模板，保留源码哈希、编译日志、功能测试、面积和时序报告。请在无网络非特权容器里运行，不把恶意RTL的安全隔离寄托在文件拷贝上。summarize.py拒绝不同工具链、冻结清单或seed的结果混排。

完整流程见deployment/LINUX.md。将此目录放在参试者可读目录会使盲测失效。
