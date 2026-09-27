# Core Pipeline

> 历史参考：Verilator、旧 emu 和旧 ChiselSim 仿真入口已退役，本文中的相关运行命令不再适用。当前验证见 [GSIM 说明](../../simulator/gsim/README.md)。

## 概览

`src/main/scala/core/Core.scala` 集成当前单发射、顺序提交的 RV64 pipeline。主要模块为：

1. `PC`
2. `InstrFetch`
3. `InstrDecode`
4. `ALU`
5. `LSU`
6. `WirteBack`
7. `RegisterFile`
8. `CSRFile`

流水线不是严格教科书五级实现。为了 bring-up 外设、cache、S-mode 和 RustSBI，当前设计把多周期内存、CSR trap、fence.i、debug halt、I-cache backpressure 统一纳入全局 stall/flush 控制。

核心全局控制信号：

- `pipe_stall`: 来自 LSU 的内存等待。
- `decodeUsesPending`: load-like hazard 检测。
- `ifetch.io.fetch_stall`: I-cache 取指等待。
- `fenceIHold`: `fence.i` 正在刷新 I-cache。
- `debugHalted`: debug module 发起 halt 后暂停流水线。
- `global_stall`: 上述条件的总和，驱动 PC。

## PC 和分支预测

`src/main/scala/core/PC.scala` 保存 `ProgramCounter`，默认 reset 到 `Config.resetVector`，即 `0x80000000`。

当前 BPU 位于 `src/main/scala/core/pipeline/BPU.scala`，是面向 MCU profile 的轻量实现：

- Direct-mapped BTB，默认 512 项。
- BTB index/tag 使用 halfword PC 位，支持 RV64C 的 16-bit 指令边界。
- 每项带 2-bit 饱和计数器。条件分支按 taken/not-taken 更新，JAL/JALR 直接置为 strongly taken。
- Not-taken 条件分支在 BTB miss 时不分配，减少一次性前向分支污染。
- 新分配项显式初始化 BHT 计数器，不依赖未初始化 `Mem` 内容。

预测元数据会随 `PC -> InstrFetch -> InstrDecode -> ALU` 传递。ALU 解析分支后：

- 预测 taken 且目标等于实际目标：不再发 redirect，避免正确预测仍冲刷流水线。
- 预测 taken 但实际 not-taken：redirect 到 fallthrough。
- 预测目标错误或未预测 taken 但实际 taken：redirect 到实际 target。

后续性能方向是把 direct-mapped BTB 升级为小型 set-associative BTB，并增加 RAS/return 预测；在进入超标量前，优先用性能计数器量化 branch redirect、I-cache miss、LSU stall 的比例。

Verilator harness 支持 `ION_PERF=1` 输出性能摘要。基础行 `[perf]` 统计 cycles、retired、IPC、全局 stall、I-fetch stall 和 LSU stall；分支行 `[perf-branch]` 统计分支数量、taken 比例、redirect 比例、BPU taken 预测数量以及 taken-target 正确预测数量。推荐先跑 `make verilator-run-perf` 获得瓶颈分布，再决定是否继续扩大 BTB、增加 RAS，或优先优化 cache/LSU。

I-cache path 额外维护一个 64-bit fetch beat buffer。顺序 PC 仍落在上一拍返回的 beat 内时，`InstrFetch` 直接从 buffer 解码，不再向 I-cache 发起一次命中访问。这个优化对 32-bit 顺序代码可复用同一 8-byte beat 内的第二条指令，同时保留跨 beat compressed 指令的第二次取数逻辑。

当前前端也支持 idle 当拍发起 I-cache 请求：如果 PC 不命中 beat buffer，`InstrFetch` 会在 `sIdle` 同拍拉起 `cache.req.valid`，cache ready 时直接进入 wait 状态。这只减少请求状态机的固定空泡；I-cache 本身仍使用 `SyncReadMem` 一拍读 tag/data，再在 compare 周期返回，不依赖异步 SRAM 读，适合后续 FPGA BRAM 映射。

顺序执行跨到下一 64-bit beat 时，前端会在当前指令仍由 beat buffer 供给的同拍发起下一 beat 请求。该请求只在当前 PC 没有 taken 预测时触发；若后续 trap/redirect 发生，晚到 response 通过 `dropResp` 丢弃。因此它是一个不改变架构语义的 ahead fetch，用来隐藏下一 beat 的一部分 I-cache hit 延迟。

I/D cache set 数由 `SoCFeatures.iCacheSets/dCacheSets` 配置，默认 256 sets，即 2 KiB direct-mapped cache。当前 perf 结果显示 I-fetch stall 中有大量 LSU overlap，短热循环也远小于默认容量，因此不应先通过扩大 I-cache 容量解决；优先方向是 instruction queue、fetch/decode 解耦和更宽 line/refill。

`FrontendQueue` 是 IF/ID 之间的小型 flushable FIFO，默认由 `SoCFeatures.frontendQueueEntries = 4` 打开。LSU 或 load-use stall 发生时，只要队列未满，PC/IF 可以继续向前取顺序或预测路径上的指令；branch redirect、trap、`fence.i` 和 debug I-cache maintenance 会清空队列。该队列只缓存已展开的 32-bit 指令、PC、压缩长度和预测元数据，不改变 I-cache 本身，也不在 cache response 到 PC stall 之间引入组合捷径。

输入来源优先级：

1. reset：输出 reset vector，取指暂时关闭。
2. trap/interrupt：跳转到 `trap_pc`。
3. trap return：跳转到 `trap_epc`。
4. stall 或 `redirectHold`：保持 PC。
5. 正常路径：使用 BPU 预测目标或 `PC + stepBytes`。

`instr_len` 编码：

- `0`: 32-bit 指令，PC 加 4。
- `2`: 16-bit compressed 指令，PC 加 2。

`redirectHold` 是为了避免 redirect 后下一拍 PC 被旧的取指/预测状态推进。这个点在 C 扩展和 cache path bring-up 时很关键。

## Instruction Fetch

`src/main/scala/core/pipeline/InstrFetch.scala` 同时支持 direct ROM path 和 cache path。

### Direct ROM path

`BROM` 输出 64-bit 指令窗口，由 low/high 两个 32-bit ROM 组成。`InstrFetch` 根据 PC 低位选择：

- 低半字或高半字的 16-bit compressed 指令。
- 从高 halfword 开始的 32-bit 指令，通过 64-bit window 拼接。

如果启用 C 扩展，`Compressed.expand` 会把 16-bit 指令展开为标准 32-bit 指令；非法 compressed 编码输出 `Common.instrIllegal`。

### I-cache path

I-cache path 使用 7 状态状态机：

- `sIdle`
- `sFirstReq`
- `sFirstWait`
- `sSecondReq`
- `sSecondWait`
- `sPrefetchWait`
- `sRelease`

关键行为：

- idle 当拍请求当前 PC 所在 64-bit beat；若 cache 暂时不 ready，则在 `sFirstReq` 保持请求。
- 如果 compressed enabled 且 PC 指向 beat 最后一个 halfword，同时低 2 位显示这是 32-bit 指令，则发第二次请求取下一个 beat。
- 当 beat buffer 命中且顺序 next PC 跨到下一 beat 时，若没有 taken 预测，同拍发起下一 beat ahead fetch。
- `assembledCrossBeat = Cat(nextBeat(15,0), crossBeatLowHalf)` 拼接跨 beat 的 32-bit 指令。
- `pc_step_len` 在 cache response 被接受的同拍使用刚解出的 `acceptedLen`，避免“上一条 32-bit 后接 16-bit 时 PC 仍加 4”的 bug。
- flush 后仍保持 response channel 可 drain，避免 late response 把 I-cache 卡在 response 状态，进而阻塞 `fence.i`。

L1 cache hit path 保持 FPGA 友好时序：CPU 请求在 `sIdle` 被接收，tag/data 通过 `SyncReadMem` 读出，下一拍 `sCompare` 做 tag compare 并返回 hit 响应。若 CPU resp backpressure，则把响应数据放入 `refillReg`，回到既有 `sResp` 保持路径。

## Decode

`src/main/scala/core/pipeline/InstrDecode.scala` 使用 `InstrTable.getTable(enabledExt)` 获取当前配置允许的指令表。输出 `DecodedInstr`，包含：

- `rs1/rs2/rd`
- `op1/op2`
- `ctrl`: ALU/mem/CSR/branch 控制信号
- `funct3`
- `atomic/aq/rl`
- `instr_len`
- `br_imm/mem_imm`

异常处理：

- 未命中 decode table 或 ECALL 会生成 `trap_info.valid`。
- ECALL cause 按当前 privilege level 区分 U/S/M。
- MRET/SRET/MNRET 通过 `trap_info.is_ret` 和 `ret_type` 向后传递。

## Execute / ALU

`src/main/scala/core/pipeline/ALU.scala` 负责：

- RV64I/RV64M 运算。
- Zba/Zbb/Zbs bitmanip 子集。
- 分支目标和 redirect 决策。
- CSR read-modify-write 的数据准备。
- load/store/atomic/fence/fence.i 的 `MemoryAccessInfo` 生成。

ALU 支持多级 forward：

- 当前 LSU 返回的 load data。
- ALU result forward。
- 上一拍 ALU result forward。
- writeback forward。
- LSU mem_out forward。

分支重定向规则：

- JAL/JALR 总是视为 taken，需要 redirect。
- 条件分支 taken 时 redirect 到 target。
- 预测 taken 但实际 not taken 时 redirect 到 fallthrough。
- fallthrough 使用 `instr_len`，compressed 指令返回地址是 `PC + 2`。

## LSU

`src/main/scala/core/pipeline/LSU.scala` 是当前 pipeline 最复杂的模块，负责 cache/MMIO/load-store/atomic 统一调度。

主要子结构：

- `MemoryAccessStage`: 地址属性、PMP、未来 MMU 入口。
- `StoreBuffer(4)`: 非设备 store 入队后异步 drain 到 D-cache。
- cache load pending FSM。
- MMIO pending FSM。
- atomic pending FSM。
- LR/SC reservation。

LSU stall 已拆成可观测子类，便于后续优化定位：

- `lsuLoadStall`: cacheable load 等待 D-cache 响应，或 load 等待已有 store drain。
- `lsuStoreStall`: store buffer 满，或 store buffer/drain 正在占用 D-cache。
- `lsuMmioStall`: device load/store 等待 TileLink MMIO 响应。
- `lsuAtomicStall`: LR/SC/AMO 序列化读写等待。
- `lsuFenceStall`: fence 等待 store buffer 和 D-cache 维护响应。

访问分类：

- SRAM/cacheable: 经 D-cache 或 uncached bridge。
- device/MMIO: 经 `TLTransTracker` 发 TileLink。
- atomic: 当前在 LSU 内序列化为 cache read + optional cache write，不使用 TileLink Atomic opcode。

异常：

- misaligned load/store/atomic 产生 address misaligned。
- atomic to device 产生 access fault。
- PMP/access stage fault 产生 load/store access fault。
- TileLink denied response 转换为 load/store access fault。

当前 atomic 设计为单 hart 语义：

- LR 读取并设置 reservation。
- SC reservation 命中则写回并返回 0；未命中返回 1。
- AMO 读取旧值，计算新值，写回新值，返回旧值。
- store drain 和 atomic write 会清除 reservation。

## Writeback

`src/main/scala/core/pipeline/WirteBack.scala` 将 LSU 输出写回寄存器堆。写回条件：

- `rd != x0`
- `mem_in.reg_write`
- `valid_in`
- 当前没有 trap

文件名当前拼写为 `WirteBack.scala`，这是历史命名问题；重命名会影响引用，可以作为后续结构整理任务单独做。

## Hazard 和 Stall

当前核心主要处理以下 hazard：

- load-like pending：Load/LR/SC/AMO 目标寄存器尚未可用，而 decode 指令使用该 rd，则 stall。
- LSU 多周期访问：cache miss、MMIO、atomic、store buffer full 会拉住 `pipe_stall`。
- I-cache miss 或跨 beat fetch：`fetch_stall` 阻止 PC/前级推进。
- fence.i：等待 I-cache flush 完成后释放。
- debug halt：halted 时冻结 pipeline，并允许 debug module 访问 GPR/CSR。

旁路优先级主要在 `Core.decodeBypass` 和 `ALU` 输入选择中实现。需要注意 LSU 和 ALU 内部仍存在若干 RegNext 风格的时序补偿，后续性能优化可以考虑统一 forward network。

## Trap、Interrupt、Return

pipeline trap 来自 LSU 的 `trap_info_out`。外部中断由 CSRFile 仲裁后，在 Core 中 latch：

- `interrupt_detect`: CSR 看到 pending interrupt，且 pipeline 没有 stall/trap/ret。
- `interruptPending`: latch PC/cause/target，等待可注入周期。
- `interrupt_fire`: 生成一次 combined trap。

trap 和 return 冲刷前端：

- `redirect_flush = combined_trap || ret_redirect`
- `frontend_flush = redirect_flush || fenceIActive`
- IF/ID/ALU 使用这些信号丢弃旧指令。

return 使用 `retConsumed` 防止同一个 `MRET/SRET` 被重复消费。

## fence.i

`fence.i` 在 ALU 阶段识别为 `MemOpType.FenceI`。Core 会：

1. 计算 fence 指令 fallthrough PC。
2. 向 PC 注入一次 redirect。
3. 如果有 I-cache，发起 whole-cache invalidate。
4. 等待 I-cache 返回维护完成响应。
5. 释放 pipeline。

如果没有 I-cache，`fence.i` 退化为短暂 flush。

## Debug Halt

Debug Module 通过 `debug_haltreq/debug_resumereq` 控制 `debugHalted`。halt 生效要求当前没有 LSU stall，避免半个内存事务中间暂停。halted 后：

- GPR debug write 才被允许。
- CSR debug write 才被允许。
- pipeline 全局冻结。

`haltreq` 可以保持为电平请求；`resumereq` 是 DMControl 写入产生的一拍脉冲，寄存器读回时该 bit 会被清掉。系统级 JTAG 测试需要按硬件 DMI 布局打包：`op[1:0]`、`data[33:2]`、`addr[40:34]`。

当前 debug 侧适合 bring-up/OpenOCD examine，尚不是完整生产级 debug subsystem。
