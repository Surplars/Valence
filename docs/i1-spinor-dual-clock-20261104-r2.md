# I1—Spinor 独立时钟功能通过（2026-11-04，r2）

真实 CPU 与 Spinor 通过显式独立边沿 GSIM 的定向程序。CPU/VPU 时钟相互独立；VPU 的器件目标仍为 300MHz。本次没有综合、布局布线、物理 CDC 或板级签核结果，也没有加入 SoC 总线、CMU、H CSR/MMU 或向量虚拟内存。

## 功能结果

| CPU/VPU 周期比（数字测试单位） | 内存首 beat 延迟 | CPU 周期 | 退休 | 向量命令 | 精确异常 |
|---|---:|---:|---:|---:|---:|
| 10:6 | 1 | 1453 | 62 | 17 | 2 |
| 10:6 | 12 | 1715 | 62 | 17 | 2 |
| 6:10 | 1 | 2625 | 62 | 17 | 2 |
| 6:10 | 12 | 2871 | 62 | 17 | 2 |

比率只用于数字边沿测试，不是上述 CPU 频率的器件通过证明。周期包括初始化、异常处理、CDC 往返和人为暂停时钟，不是工作负载 IPC 或向量吞吐指标。测试中分别暂停 CPU/VPU 的输入时钟，恢复后程序按原账本完成。

复用同一个独立 ISA/IEEE/内存程序 oracle，检查 VS=Off 拒绝、vsetvli、向量 load/add/store、向量 CSR、f0 源/目的、RUP/NX 与 CPU FCSR 合并、共享 cache 读回、向量 store 清除 LR/SC 保留和只读 CSR 的精确异常。CPU 保留 WB/80位身份直到最终 done；四组均核对完整 token、命令/完成数、GPR/FPR/flags、cause/tval、PC 以及最终 RAM。错误值与 flags 两个负控制均被拒绝，ASAN/UBSAN 启用。

CPU—VPU 指令采用 Spinor 自定义 offer/preview/grant/done；访存另用 TileLink A/D 子集。六条异步 mailbox 分别传递命令+FCSR、preview、grant、done、TL A、TL D。仍是一条向量指令在途，物理普通 RAM、共同 cold-reset epoch；当前没有上下文操作、单域热复位或 CMU 门控/变频验收。

## GSIM 修复及范围

冻结的默认初始化修复工具保持不变；新工具在独立 build/ 目录应用 `explicit-clock-edges.patch`，仅在生成模型时设置 `GSIM_CLOCK_EDGES=1` 才启用。上游 pristine clone 与 Spinor clone 未修改。

修复明确区分组合求值、同步状态提交与异步复位收敛：只有各自顶层时钟的上升沿能提交寄存器/RAM；同时边沿均采样旧状态；条件更新每次重新准备候选，禁止输入 enable 脉冲留下未提交的旧候选；异步复位即使没有新边沿也收敛。断言/打印和内存写只在对应边沿执行一次。派生复位信号保留为可被 reset helper 引用的值。

原七种独立时钟探针现全部匹配，运行后的 AsyncReset 正确清零。新增 90000 组成对求值、1534 次完整 80 位 mailbox 传输，检查时钟比、保持/下降沿、暂停、同时采样、同步/非零异步复位、定义明确的 Mem/SyncReadMem 访问、背压及共同复位。token bit79 注错被拒绝；冻结默认工具仍按原独立边沿契约失败，作为错误行为对照。

资格范围是显式顶层时钟及其别名、当前寄存器/展平复位、定义明确的 RAM 访问与现有 mailbox。不是通用 SystemVerilog 事件仿真器签核；门控/动态生成时钟不在支持范围，会拒绝；未展平异步复位数组也未支持。不声称未定义同址 RAM 碰撞值、物理亚稳态、CDC 布线或全量 CPU/VPU 指令合规。默认快速单钟流程与 R12 原始物理/IPC 证据保持冻结。

## 证据与复现

- 工具资格：`build/gsim-clock-edges-20261104-r1/qualification/receipt.json`，SHA256 `07d150aca5c37f4771d062a8504bd893a7813eb2ed62e35dc91b4e8bbdbc22d1`。
- 实际 CPU/VPU：`build/i1-spinor-dual-clock-20261104-r2/receipt.json`，SHA256 `2b4603d07bbbd9f09001bcfe0a820b95905e41910d75f0149b8a1dc75eaf22cd`。
- 首次实验通过另保留于 `build/gsim-clock-edges-20261104-r1/dual-cpu`；工具原型的失败生成/编译目录也保留，不作为通过证明。正式 r2 仅使用已验证资格的同一工具二进制。
- `entry-format-equivalence.json` 证明复现入口展开排版后与已执行快照的 Python AST 完全一致，没有覆盖原始 receipt 源码哈希。

```sh
source /home/openion/Valence-InOrder/.local-dev/env.sh
mill -i SpinorHost.test.compile
mill -i SpinorHost.test.runClasspath
python3 simulator/gsim/tool_fixes/build_clock_edges.py --output build/FRESH_EDGE_TOOL
python3 simulator/gsim/tool_fixes/qualify_clock_edges.py --tool build/FRESH_EDGE_TOOL/source/build/gsim/gsim --output build/FRESH_EDGE_QUALIFICATION
python3 simulator/gsim/inorder/spinor_dual_clock_program.py --tool-receipt build/FRESH_EDGE_QUALIFICATION/receipt.json --output build/FRESH_DUAL_CLOCK_CPU
```

新目录必须位于已指定 WSL clone 内的 build/。Windows 复核文件在 `E:/VM/Share/Valence-rtl/Valence-InOrder/spinor-dual-clock-20261104-r2`。此前 r1 的“不支持独立边沿”结论继续对其冻结默认工具有效；本 r2 通过依赖新的可选工具，不改写 r1。

H 当前仍为独立译码已验证，CPU 的 H/VS CSR、虚拟化状态、trap/xRET 和两阶段 MMU 未接入。misa.H/V 仍不宣告完整扩展。下一步分别处理 CDC 局部物理约束/模块时序与 H CPU 状态接入，完整 SoC 总线和 CMU 单独评估。

## r3：用于物理实现的诊断跨域修正

物理检查发现 VPU `protocolError` 原为状态组合译码，现先在 VPU 源时钟域注册，再送入原有两级 `CdcLevel`。仅诊断状态增加一个 VPU 周期；CPU 退休和异常所有权不变。

当前实现使用 `build/i1-spinor-dual-clock-20261104-r3/receipt.json`，SHA256 `a6bbf91b8f04aa0dc740611a26cd94319fb0a89e5e44f4e70313fa11ab346950`。重新编译后，四组独立时钟程序、两个错误值/flags 负控制及 ASAN/UBSAN 均通过；四组周期仍为 1453/1715/2625/2871。物理导出的 161 个生产依赖与这份 r3 功能凭据逐项匹配。此前 r2 凭据和源码快照继续保留。
