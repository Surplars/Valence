# Orbital-I1 定向验证

本目录是独立顺序核 GSIM 流程、汇编向量与链接脚本，不是 legacy 顺序核测试。
模型入口：src/test/scala/inorder/；独立 oracle：simulator/gsim/harness/five_stage*。
只用锁定版本 GSIM，不使用 Verilator/ChiselSim。

~~~sh
GSIM_CXX=clang++-19 python3 simulator/gsim/inorder/bandwidth40_acceptance.py --tag YOUR_UNIQUE_TAG
~~~

该入口是受影响短验证，不是全量回归：覆盖 MMU/Home 交接、错误/背压、
256B/32KiB 参数、真实 CPU Bare/Sv39、精确异常、C/A/F/D 和同二进制 O3 短 CoreMark。
须先恢复本地 batch39 收据及其引用的旧向量/证明链；不能以新结果自充基线、跳过 oracle。

--reuse-compiles 仅在新 FIR 与已有哈希对象完全匹配时复用编译，所有检查仍重新执行；
--components-only 不能产生完整 CPU 验收结论。
历史 bandwidth36_acceptance.py、cpu_timing*_acceptance.py 等保留供阶段复核，
不是最新范围，也不默认串联运行全部历史测试。

batch40另加RV32/64直接/分段PMP和执行通路的正例/负控，合计49项；13项性能门通过。
六组Bare/Sv39和短O3 CoreMark逐字段等同batch39；6999寄存器/89内存声明完全相同。
严格审计入口为fpga/inorder/audit_batch40_short.py；不允许用未完成收据导出整板。
batch39增加预测器、masked probe/victim及非页对齐窗口的受影响检查，合计37项；
六组Bare/Sv39及短O3 CoreMark与batch38逐字段相同，容量/寄存器/内存声明不变。
batch38 修复 Home RAM 推断与 DT 回复→地址组合回环，吞吐和 CoreMark 与 batch37 相同；
batch37 的 CoreMark 相对 batch36 短测约快0.20%。不是正式持续时间评分，
也不证明 FPGA300MHz 达标。详见 [工程记录](../../../docs/orbital-i1.md)。

模型、ELF/bin、FIR、日志和收据进入 Git 忽略的 build/。
小报告/向量/源码快照已归档：
/home/openion/Valence-inorder-evidence/pre-dev2-20261017-r1。
