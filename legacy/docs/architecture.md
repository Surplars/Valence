# SoC Architecture

## 设计目标

IonSoC 是一个 Scala 2.13 + Chisel 7.3 实现的 RV64 SoC。当前目标是同时支持三类形态：

- 精简 MCU：无 MMU、可关闭 I/D cache、可关闭外部中断控制器，适合裸机和快速仿真。
- 固定 BareMetal MCU：无 MMU、I/D cache、CLINT、PLIC、UART16550-like、JTAG 和默认 SRAM，是当前默认平台契约。
- 现代无 MMU/未来 Linux-capable SoC：带较大 SRAM、RustSBI/OpenSBI 启动契约，并预留 MMU/AIA 扩展。

可配置入口在 `src/main/scala/config/config.scala`：

- `SoCFeatures`: `mmu`、`iCache`、`dCache`、`sramBase`、`sramSizeBytes`、`uart`、`clint`、`interruptController`。
- `SoCProfiles.MinimalMCU`: 最小 smoke 配置，无 cache、无 PLIC。
- `SoCProfiles.BareMetalMCU`: 当前默认 MCU 配置，RV64IMAC(+B 子集)、无 MMU、I/D cache、UART、CLINT、PLIC。
- `SoCProfiles.LinuxCapablePLIC`: 16 MiB SRAM、I/D cache、PLIC、CLINT、UART，MMU 标志打开。
- `SoCProfiles.ModernAIA`: 当前只是 AIA profile 占位，AIA 控制器尚未实现。

## Roadmap Position

2026-09-18 更新：产品线规划包含顺序核和 2/4/6 发射乱序核，当前研发重心转向首个双发射乱序核。
新核使用 GSIM 作为主仿真后端，具体接口、恢复/访存规则和验收阶段见 [OoO Core 架构草案](../../docs/ooo-core-plan.md)。
现有顺序核已知有 bug，仅保留为历史问题复现来源，不能作为新核的正确性标准；平台模块需独立验证后才能复用。
本文其余部分描述现有实现，不表示新乱序核已经具备这些能力。

仿真 profile 在 `src/test/scala/sim.scala`：

- `SimTop`: 默认 SoC，当前等价于 BareMetal MCU 合约。
- `SimTopMCU`: 明确的 MCU RTL emission target，输出到 `build/rtl-mcu`。
- `SimTopICache`: 打开 I-cache。
- `SimTopFirmware`: 使用 16 MiB SRAM + PLIC/CLINT/UART，MMU 暂时关闭，用于 RustSBI bring-up。

## 顶层模块

`src/main/scala/system/IonSoC.scala` 是顶层集成点。主要实例包括：

- `Core`: 单 hart RV64 核心。
- `BROM`: reset 后直接取指的 boot ROM，当前 reset vector 为 `0x80000000`。
- `TLRAM`: TileLink SRAM，从 `features.sramBase` 开始。
- `TLROM`: 通过 TileLink 访问 ROM 内容。
- `UartTx`: 16550/8250 风格寄存器子集，地址 `0x10010000`。
- `CLINT`: `mtime`、`mtimecmp`、`msip`，地址 `0x02000000`。
- `PLIC`: 基础平台级中断控制器，地址 `0x0c000000`。
- `DebugModule`: debug MMIO/DMI 寄存器块，地址 `0x00000000`。
- `JtagTap`: remote-bitbang 可连接的 JTAG TAP。
- `TLXbar`: 单 master、多 slave MMIO crossbar。

顶层把 core DBus 接入 `TLXbar`，再按配置连接 debug、TLROM、SRAM、UART、CLINT、PLIC。未实例化的可选外设不会连接到 crossbar；保留 MMIO 区域通过地址 decode 和 denied response 暴露错误。

## 地址空间

核心地址定义在 `Config`：

| Region | Base | Size | 用途 |
| --- | ---: | ---: | --- |
| Debug | `0x00000000` | `0x4000` | Debug Module MMIO |
| CLINT | `0x02000000` | `0x10000` | MSIP/MTIMECMP/MTIME |
| PLIC | `0x0c000000` | `0x04000000` | M/S context 外部中断 |
| UART | `0x10010000` | `0x1000` | ns16550a-like UART |
| Default SRAM | `0x10000000` | `0x10000` | 裸机测试 |
| Firmware SRAM | `0x40000000` | `0x01000000` | RustSBI/firmware profile |
| ROM | `0x80000000` | `0x20000` | reset boot ROM |

RustSBI firmware profile 使用以下启动契约：

- trampoline 位于 ROM，入口 `0x80000000`。
- RustSBI ELF 加载到 `0x40000000`。
- DTB 加载到 `0x40f00000`，作为 `a1` 传给 firmware。
- S-mode payload 加载到 `0x40100000`，作为 `a2` 传给 RustSBI/prototyper jump 配置。

`simulator/firmware/ionsoc.dts` 描述了 firmware profile 的设备树，包括 memory、CPU ISA 字符串、UART、CLINT、PLIC。

## 总线结构

核心内部有一个 data-side system crossbar：

- D-cache 或 uncached bridge 作为 master 0。
- MMIO tracker 作为 master 1。
- I-cache 打开时作为 master 2。

这个内部 `TLSystemXbar` 汇聚成 core 的 `DBus`。SoC 顶层再把 `DBus` 接到系统 `TLXbar`，路由到 debug、ROM、SRAM 和外设。

当前使用 TileLink A/D 通道子集，主要覆盖 `Get`、`PutFullData`、`PutPartialData` 和 denied response。B/C/E 一致性通道的数据结构已定义但未启用，因此系统是 TL-UL-like non-coherent interconnect。PMA/地址属性负责让 SRAM 走 cacheable 路径、MMIO/ROM/debug 走 device/uncached 路径；普通 `fence` 会通过 LSU 触发 D-cache whole-cache clean+invalidate，`fence.i` 会触发 I-cache invalidate。

## 模块化边界

项目当前已经按照“功能可裁剪”的方向组织：

- 默认 `Config.features` 指向 `SoCProfiles.BareMetalMCU`，用于稳定 MCU 规格。
- 指令集由 `Config.enabledExt` 和 `InstrTable.getTable(enabledExt)` 控制。
- `Core` 根据 `features.iCache/dCache` 决定实例化 `L1Cache` 或 `UncachedTileLinkBridge`。
- `IonSoC` 根据 `features.uart/clint/interruptController` 决定外设是否存在。
- `MemoryAccessStage` 从 CSR 输出的 `MemorySystemConfig` 获取 `mmu_en`、`satp`、PMP 等信息，为后续 MMU 接入保留接口。

后续新增功能应优先沿这些配置点扩展，避免把 Linux-class SoC 特性硬塞进 Minimal MCU profile。
