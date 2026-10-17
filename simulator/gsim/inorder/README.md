# Orbital-I1 定向验证

本目录是独立顺序核 GSIM 流程、汇编向量与链接脚本，不是 legacy 顺序核测试。
模型入口：src/test/scala/inorder/；独立 oracle：simulator/gsim/harness/five_stage*。
只用锁定版本 GSIM，不使用 Verilator/ChiselSim。

~~~sh
GSIM_CXX=clang++-19 python3 simulator/gsim/inorder/bandwidth37_acceptance.py --tag YOUR_UNIQUE_TAG
~~~

该入口是受影响短验证，不是全量回归：覆盖 MMU/Home 交接、错误/背压、
256B/32KiB 参数、真实 CPU Bare/Sv39、精确异常、C/A/F/D 和同二进制 O3 短 CoreMark。
须先恢复本地 batch36 收据与旧向量；不能以新结果自充基线、跳过 oracle。

--reuse-compiles 仅在新 FIR 与已有哈希对象完全匹配时复用编译，所有检查仍重新执行；
--components-only 不能产生完整 CPU 验收结论。
历史 bandwidth36_acceptance.py、cpu_timing*_acceptance.py 等保留供阶段复核，
不是最新范围，也不默认串联运行全部历史测试。

batch37 标准吞吐与 batch36 相同，CoreMark 短测约快0.20%；不是正式持续时间评分，
也不证明 FPGA300MHz 达标。详见 [工程记录](../../../docs/orbital-i1.md)。

模型、ELF/bin、FIR、日志和收据进入 Git 忽略的 build/。
小报告/向量/源码快照已归档：
/home/openion/Valence-inorder-evidence/pre-dev2-20261017-r1。
