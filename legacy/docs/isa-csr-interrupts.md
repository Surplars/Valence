# ISA, CSR, and Interrupts

> 历史参考：Verilator、旧 emu 和旧 ChiselSim 仿真入口已退役，本文中的相关运行命令不再适用。当前验证见 [GSIM 说明](../../simulator/gsim/README.md)。

## ISA 扩展选择

扩展枚举在 `src/main/scala/isa/Instruction.scala` 的 `Extension`。默认 `Config.enabledExt` 当前启用：

- `RV64I`
- `Zicsr`
- `Zifencei`
- `S`
- `C`
- `RV64M`
- `RV64A`
- `Zba`
- `Zbb`
- `Zbs`

Decode 表由 `InstrTable.getTable(enabledExt)` 动态生成。`InstrTable` 会根据扩展集合过滤各 provider：

- `InstrSetI`: RV32/64 base integer。
- `InstrSetM`: multiply/divide。
- `InstrSetA`: LR/SC/AMO。
- `InstrSetB`: Zba/Zbb/Zbs 子集。
- `InstrSetZicsr`: CSR 指令。
- `InstrSetZifencei`: fence.i。

设计约束：新增 ISA 扩展时应该以新的 `InstrProvider` 或扩展现有 provider 的方式接入，并通过 `Extension` + `Config.enabledExt` 控制，不要在 decode 里写死始终启用。

## C 扩展

Compressed 指令在 `src/main/scala/isa/Compressed.scala` 展开为 32-bit 指令。`InstrFetch` 在取指阶段完成：

- 判断 halfword 低两位是否为 compressed。
- 对 compressed 指令调用 `Compressed.expand`。
- 对 illegal compressed 编码输出 32-bit illegal instruction。
- 对正常 32-bit 指令保持原样。

当前支持常见 RV64C 形式，包括：

- `c.addi/c.addiw/c.li/c.lui/c.addi16sp/c.addi4spn`
- `c.lw/c.ld/c.sw/c.sd`
- `c.lwsp/c.ldsp/c.swsp/c.sdsp`
- `c.j/c.beqz/c.bnez`
- `c.slli/c.srli/c.srai/c.andi`
- `c.sub/c.xor/c.or/c.and/c.subw/c.addw`
- `c.jr/c.jalr/c.mv/c.add/c.ebreak`

链路约定：后级看到的永远是 32-bit expanded instruction，但 `instr_len` 会保留原始长度，供 PC、JAL/JALR link address、branch fallthrough 使用。

## A 扩展

`InstrSetA` 覆盖 RV32A 和 RV64A 的 W/D 形式：

- LR
- SC
- AMOSWAP
- AMOADD
- AMOXOR
- AMOAND
- AMOOR
- AMOMIN/AMOMAX
- AMOMINU/AMOMAXU

当前实现不使用 TileLink Atomic opcode，而是在 LSU 内部拆解：

1. cache read 旧值。
2. 根据 atomic op 计算新值。
3. 对 SC/AMO 发 cache write。
4. 返回旧值或 SC success/fail code。

限制：

- 当前 reservation 是单 hart 本地状态。
- 没有 cache coherence invalidation。
- atomic to device 会 fault。
- aq/rl 位被 decode 并传递，但当前没有额外 memory ordering 机制。

## Bitmanip 子集

`InstrSetB` 当前覆盖：

- Zbb: `andn/orn/xnor/min/max/minu/maxu/clz/ctz/cpop/clzw/ctzw/cpopw/sext.b/sext.h/rol/ror/rori/rolw/rorw/roriw/orc.b/rev8`
- Zba: `add.uw/sh1add/sh2add/sh3add/sh1add.uw/sh2add.uw/sh3add.uw`
- Zbs: `bset/bclr/binv/bext` 及部分 immediate 形式

ALU 中直接组合实现。后续若补全更多 B 扩展，应注意 RV64 immediate 编码宽度和 OP-32 变体。

## CSRFile

`src/main/scala/core/csr/CSRFile.scala` 管理 privilege、trap、中断、PMP、counter 和 debug CSR access。

当前主要 CSR：

- Machine info: `mvendorid/marchid/mimpid/mhartid`
- Machine trap: `mstatus/misa/medeleg/mideleg/mie/mtvec/mscratch/mepc/mcause/mtval/mip`
- Supervisor trap: `sstatus/sie/stvec/sscratch/sepc/scause/stval/sip`
- Protection/translation: `pmpcfg0/pmpaddr0..7/satp`
- Counters: `mcycle/minstret/mhpmcounter3..31/mhpmevent3..31`
- Counter config: `mcounteren/scounteren/mcountinhibit`
- Environment: `menvcfg`
- NMI placeholders: `mnscratch/mnepc/mncause/mnstatus`

权限检查：

- CSR address bits `[9:8]` 用作 required privilege。
- bits `[11:10] == 3` 视为 read-only CSR，写访问 illegal。
- debug 读写走独立端口，写入只在 core halted 时由 Core 允许。

`misa` 根据 `enabledExt` 生成，S 扩展开启时设置 S bit。

## S-mode 语义

当前 S-mode 已具备 RustSBI jump flow 需要的基础语义：

- `mideleg/medeleg` 支持委托到 S-mode。
- `sstatus/sie/sip` 是 `mstatus/mie/mip` 的 supervisor view。
- `stvec/sepc/scause/stval/sscratch/satp` 可读写。
- `SRET` 从 `sepc` 返回，并恢复 SIE/SPIE/SPP。
- delegated interrupt/exception 会进入 `stvec`。

限制：

- U-mode 不是当前 bring-up 重点。
- `satp` 可见，但页表 walk/MMU 尚未实现。
- `scounteren/mcounteren` 存在，但 counter 对低权限访问的精细控制还需要补。

## Counter/PMU

为了兼容 RustSBI 的平台探测，当前实现：

- `mcycle` 每 cycle 自增，受 `mcountinhibit[0]` 控制。
- `minstret` 由 Core retire pulse 驱动，受 `mcountinhibit[2]` 控制。
- `mhpmcounter3..31` 可读写，并受 `mcountinhibit[3..31]` 控制。
- `mhpmevent3..31` 选择 IonSoC 平台事件；当前低 8 bit 作为事件号。

当前事件号：

| ID | Event |
| --- | --- |
| 0 | none |
| 1 | retired instruction |
| 2 | global pipeline stall |
| 3 | I-fetch stall |
| 4 | LSU stall |
| 5 | branch resolved |
| 6 | branch taken |
| 7 | branch redirect / mispredict recovery |
| 8 | BPU predicted taken |
| 9 | BPU predicted taken with correct target |
| 10 | LSU cache-load stall |
| 11 | LSU store-buffer/drain stall |
| 12 | LSU fence stall |
| 13 | LSU atomic stall |
| 14 | LSU MMIO stall |

RustSBI 当前会看到较宽的 MHPM mask。bring-up 阶段这是可接受的；后续若做精确 PMU，应让 mask 和 event 能力匹配真实实现。

## CLINT

`src/main/scala/device/CLINT.scala` 实现 SiFive CLINT 风格子集：

- offset `0x0000`: `msip`
- offset `0x4000`: `mtimecmp`
- offset `0xbff8`: `mtime`

`mtime` 每 cycle 自增。`mtip` 在 `mtimecmp != 0 && mtime >= mtimecmp` 时置位。支持 32-bit high/low word 访问，因为地址 decode 会对齐到 64-bit beat。

当前 CLINT 只输出 machine-level `msip/mtip`；S-mode timer interrupt 需要由 SBI 或未来 interrupt file/AIA 路径进一步支持。

## PLIC

`src/main/scala/device/interrupt/PLIC.scala` 实现基础 PLIC：

- source 0 保留。
- 默认 `nSources = 31`。
- priority register: `0x000000 + source * 4`
- pending: `0x001000`
- M context enable: `0x002000`
- S context enable: `0x002080`
- M context threshold/claim: `0x200000/0x200004`
- S context threshold/claim: `0x201000/0x201004`

中断选择规则：

- pending && enable && priority > threshold 才通知 `meip/seip`。
- claim read 返回最高 priority source；同优先级选择较小 source ID。
- claim read 有副作用，会清 pending。
- level gateway 在 claim 后保持 busy，防止源电平仍高时反复重新 pending。
- complete write 释放对应 gateway；如果源电平仍高，会重新投递 pending。
- unsupported TileLink opcode 返回 `denied`。

顶层把 UART IRQ OR 到 PLIC source 1，因此 16550 driver 可以通过 PLIC 收到 UART 中断。

Verilator `uart_irq.S` smoke 会由 harness 注入 RX byte，走 UART RDI -> PLIC source 1 -> M-mode external interrupt -> claim/complete，预期 UART 输出 `UP`。

限制：

- 当前实现固定为 level gateway；还没有 edge-triggered gateway 或 per-source gateway 配置。
- 只有 M/S 两个 context。
- 没有 AIA/APLIC/IMSIC；`InterruptControllerKind.AIA` 只是未来配置方向。

## 中断仲裁

CSRFile 中优先级当前为：

Machine visible:

1. Machine external
2. Machine software
3. Machine timer
4. Supervisor external
5. Supervisor software
6. Supervisor timer

Supervisor visible:

1. Supervisor external
2. Supervisor software
3. Supervisor timer

Machine interrupt 在当前 privilege 低于 M 或 `mstatus.MIE=1` 时可进入；Supervisor interrupt 在当前 privilege 低于 S 或 S-mode 且 `sstatus.SIE=1` 时可进入。

Core 会把中断 PC/cause/vector latch 一拍再注入 pipeline，保证 CSR 和 PC 消费同一份 trap PC。
