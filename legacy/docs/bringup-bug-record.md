# Bring-up Bug Record

> 历史参考：Verilator、旧 emu 和旧 ChiselSim 仿真入口已退役，本文中的相关运行命令不再适用。当前验证见 [GSIM 说明](../../simulator/gsim/README.md)。

本文记录近期 bring-up 中已经解决或明确归类的问题。每条记录包含症状、根因、修复和验证方式，便于后续遇到相似现象时快速定位。

## 1. RustSBI 早期 CSR 探测卡住

### 症状

RustSBI 能从 ROM 跳入 SRAM，但初始化过程中无明显后续输出，或 trap probe 输出显示访问某些 CSR 后进入异常路径。早期调试输出曾显示类似：

```text
mcause=0x0000000000000002
mepc=0x000000004000f1dc
mtval=0x0000000000000000
```

这代表 illegal instruction/illegal CSR access 类问题。

### 根因

RustSBI 会探测平台 CSR，包括 counter、PMU、PMP、delegation、envcfg 等。CSRFile 当时只实现了基础 CSR，缺少 RustSBI 会访问的若干 machine counter/PMU 相关地址：

- `mcounteren`
- `scounteren`
- `menvcfg`
- `mcountinhibit`
- `mcycle`
- `minstret`
- `mhpmcounter3..31`
- `mhpmevent3..31`
- 多个 `pmpaddr`

缺失 CSR 被权限/地址检查识别为 illegal，RustSBI probe 无法完成。

### 修复

在 `CSR.scala` 和 `CSRFile.scala` 中补齐 CSR 常量、读写映射和测试：

- `mcycle` 每 cycle 自增。
- `minstret` 接入 Core retire pulse。
- `mhpmcounter3..31/mhpmevent3..31` 可读写，并接入 IonSoC 平台事件选择。
- `pmpaddr0..7` 改为 Vec。
- `mcounteren/scounteren/menvcfg/mcountinhibit` 可读写。

### 验证

```bash
mill -i IonSoC.test.testOnly core.CSRFileSpec
make verilator-run-rustsbi
```

RustSBI 现在可打印：

```text
Boot HART Privileged Version: : Version1_12
Boot HART MHPM Mask:          : 0xffffffff
```

## 2. RustSBI 跳入 S-mode 后 payload 取到全 0

### 症状

RustSBI 输出已经显示跳转：

```text
Redirecting hart 0 to 0x00000040080000 in Supervisor mode.
```

boot trace 也显示 PC 进入 payload 区域，但 IF 输出为零：

```text
if_req_pc=0x40080000
if_pc=0x40080000
if_instr=0x00000000
if_len=2
```

随后 PC 变成 `0x40080002` 并 trap，看起来像 compressed/PC step bug。

### 根因

这不是 CPU 跳转失败，也不是总线无法读取 SRAM。真正原因是 RustSBI ELF 的最后一个 LOAD segment `.bss` 范围覆盖了原 payload 地址。

RustSBI 最后一个 LOAD：

```text
vaddr=0x40031000
memsz=0x640f8
end=0x400951f8
```

原 `sbi_payload.ld` 把 S-mode payload 放在：

```text
0x40080000
```

所以 payload 被 RustSBI 清 `.bss` 时清零。Verilator loader 的加载顺序虽然先写 RustSBI 再写 payload，但 RustSBI 运行时自己清 BSS，仍会覆盖 payload。

### 修复

统一将 S-mode payload 移到 `0x40100000`：

- `simulator/payloads/sbi_payload.ld`
- `simulator/firmware/rustsbi/prototyper/prototyper/config/ionsoc.toml`
- Makefile `PROTOTYPER_PAYLOAD_START_ADDRESS`
- Makefile `ION_BOOT_A2`
- Verilator `--rustsbi` 默认 `boot_a2`

### 验证

`readelf` 确认 payload entry：

```text
Entry point address: 0x40100000
LOAD vaddr=0x40100000
```

RustSBI flow：

```bash
make verilator-run-rustsbi
```

最终输出：

```text
Redirecting hart 0 to 0x00000040100000 in Supervisor mode.
IonSoC SBI smoke
[rustsbi]: gp=0, a7=93, a0=0, test passed
```

## 3. `make verilator-run-rustsbi` 默认 cycle 不够

### 症状

手动把 `ION_MAX_CYCLES` 拉高后 RustSBI 能继续输出，但 Makefile 默认运行在 RustSBI banner 或初始化中途结束。

### 根因

RustSBI 初始化和 UART 输出较长，默认 `1_000_000` cycles 不足以完成完整 jump flow 和 SBI console smoke。

### 修复

将 `verilator-run-rustsbi` 和 `--rustsbi` 默认 `ION_MAX_CYCLES` 提到 `8_000_000`。

### 验证

```bash
make verilator-run-rustsbi
```

无需手动设置环境变量即可通过。

## 4. RustSBI xtask 硬依赖 `rust-objcopy`

### 症状

RustSBI prototyper 已编译成功，但 xtask 最后转换 ELF 到 binary 失败：

```text
Failed to execute rust-objcopy. Command not found or failed to start.
Please install cargo-binutils with cmd: cargo install cargo-binutils
```

### 根因

本机已有 `llvm-objcopy` 和 `riscv64-unknown-elf-objcopy`，但 RustSBI xtask 写死调用 `rust-objcopy`。

### 修复

修改 `simulator/firmware/rustsbi/xtask/src/prototyper.rs`：

1. 优先尝试 `rust-objcopy`。
2. fallback 到 `llvm-objcopy`。
3. fallback 到 `riscv64-unknown-elf-objcopy`。

### 验证

构建输出显示：

```text
Converting ELF to binary with llvm-objcopy
Task completed successfully
```

## 5. I-cache path compressed PC step 错误

### 症状

C 扩展启用后，cache path 中 16-bit 指令跟在 32-bit 指令后时，PC 偶发按旧长度推进，表现为跳过半字或从错误地址取指。

### 根因

PC 在 cache response 被接受同拍需要知道“当前刚解码出来的长度”。旧逻辑使用注册后的 `io.instr_len`，可能仍是上一条指令长度。

### 修复

`InstrFetch` cache path 中：

- 引入 `acceptedLen`。
- `io.pc_step_len := Mux(acceptResp, acceptedLen, Mux(state === sRelease, releaseLen, io.instr_len))`。
- 在 release 状态保存 `releaseLen`，保证 stall 后仍使用正确长度。

### 验证

```bash
mill -i IonSoC.test.testOnly core.InstrFetchSpec
```

覆盖用例包括：

- compressed low/high halfword 展开。
- cache path 当前 compressed length 用于 PC stepping。

## 6. I-cache 跨 64-bit beat 的 32-bit 指令

### 症状

启用 C 扩展后，若 PC 位于 64-bit beat 最后一个 halfword，且该 halfword 低两位为 `11`，说明指令是 32-bit，需要跨下一个 beat 拼接。旧 cache path 无法处理。

### 根因

cache path 原来只发一次 beat 请求，无法取到下一 beat 的低 16 bit。

### 修复

`InstrFetch` cache path 改为状态机：

- `sFirstReq/sFirstWait` 取当前 beat。
- 检测 `needsCrossBeat`。
- `sSecondReq/sSecondWait` 取 `reqPc + 2` 所在 beat。
- `assembledCrossBeat = Cat(secondBeat(15,0), crossBeatLowHalf)`。

### 验证

```bash
mill -i IonSoC.test.testOnly core.InstrFetchSpec
```

用例：

```text
InstrFetch cache path assembles a 32-bit instruction crossing a 64-bit beat
```

## 7. I-cache flush 被 late response 卡住

### 症状

`fence.i` 或前端 redirect 后，如果 cache response 晚到，I-cache 可能停在 response 状态，后续 invalidation 无法完成。

### 根因

flush 后 IF 丢弃请求，但 response channel 没有保持 drainable。cache 等待 CPU resp ready，CPU 前端又在等 flush/invalidate，形成僵持。

### 修复

IF cache path 在 flush 后仍保持：

```scala
io.cache.resp.ready := !io.stall
```

并用 `dropResp` 标记 late response 应丢弃。这样 I-cache 能回到 idle 并接受 invalidate。

### 验证

RustSBI flow 和 I-cache 定向测试均通过：

```bash
make verilator-run-rustsbi
mill -i IonSoC.test.testOnly core.InstrFetchSpec
```

## 8. CLINT 32-bit 访问 mtime/mtimecmp

### 症状

裸机或 SBI 风格代码可能按 32-bit high/low word 访问 `mtime`/`mtimecmp`。如果 CLINT 只按完整 64-bit offset decode，会导致 high word 访问读写不到目标寄存器。

### 根因

CLINT register decode 需要对齐到 64-bit beat，而不是直接使用 byte offset。

### 修复

`CLINT.scala` 使用：

```scala
val beat_offset = addr_offset(15, log2Ceil(beatBytes)) ## 0.U(log2Ceil(beatBytes).W)
```

高/低 word 访问都落到同一个 64-bit register，写入用 byte mask 合并。

### 验证

```bash
make verilator-run-clint32
```

## 9. PLIC M/S context 和 UART interrupt

### 症状

需要支持 M-mode 和 S-mode 的外部中断路径，并让 UART 能通过 PLIC source 1 触发外部中断。

### 根因

单 M context 不足以验证 S-mode delegation；UART 也需要标准 PLIC 中断源。

### 修复

PLIC 增加两个 context：

- context 0 -> M-mode `meip`
- context 1 -> S-mode `seip`

顶层将 UART IRQ OR 到 `sources(1)`。

### 验证

```bash
make verilator-run-plic
make verilator-run-plic-s
```

## 10. JTAG/OpenOCD remote-bitbang bring-up

### 症状

OpenOCD 能连接 remote_bitbang，但早期无法稳定识别 TAP/CPU，或者 simulator 被 kill 后 OpenOCD 卡住。

后续加入 SBA 后，`read_memory/write_memory` smoke 曾出现写入 `0x10000000` 后读回 0 或旧值。

SBA 可以直接改 SRAM，但当前 TileLink/Cache 不是 coherent 系统。若 hart 已缓存过目标地址，debugger 改内存后可能继续看到旧 D-cache 数据，或 I-cache 继续取旧指令。

### 根因

JTAG TAP/DTM/DM 仍处于第一阶段实现。remote-bitbang socket 与 simulator 生命周期强相关；如果 simulator 被外部 kill，OpenOCD 可能还在等待 socket/TAP 状态。

SBA 侧另有两个兼容性问题：

- `sbreadonaddr` 写 `sbaddress0` 同周期触发读时，硬件使用了旧 `sbAddress` 寄存器值。
- OpenOCD 高层 memory helper 可能在 SBA 尚未完成时读取 `sbdata0`；DM 如果直接返回旧数据，会让上层误判读完成。

### 修复

当前已加入：

- `openocd/ionsoc-rbb.cfg`
- JTAG TAP IDCODE `0x10e31913`
- DTMCS/DMI instruction
- Debug Module 基础 DMI register
- `hartinfo/abstractauto/haltsum0/sbcs` 基础寄存器面
- `abstractauto` 已支持 `data0/data1/progbuf0/progbuf1` 访问触发当前 abstract command
- halt/resume/GPR/CSR abstract command 子集
- halted PC 捕获到 `dpc`
- `progbuf0/progbuf1` backing register 已预留，并支持 `nop/fence/fence.i/ebreak` 的安全 postexec 子集
- `abstractcs.progbufsize=2` 已打开，用于满足 OpenOCD fence/postexec 探测；不支持的 program-buffer 指令返回 `cmderr`
- SBA 作为 TileLink master 接入 SoC crossbar，可通过 `sbaddress/sbdata` 读写系统内存
- `sbreadonaddr` 写 `sbaddress0` 时使用刚写入的新地址旁路发起 SBA 读，避免 64-bit 地址半更新时误发请求
- SBA 支持跨 beat split 访问，覆盖 unaligned 32/64-bit 读写，并按原始 `sbaccess` 做 `sbautoincrement`
- SBA 忙时访问 `sbaddress/sbdata` 返回 DMI busy op，给 OpenOCD 重试机会
- 增加 IonSoC 私有 DMI register `IonCacheCtl`，地址 `0x70`。写 bit 0 触发 D-cache clean+invalidate，写 bit 1 触发 I-cache invalidate；bit 8/9 是 done sticky，bit 16/17 是 error sticky，sticky 位写 1 清除。
- Core 对 debug cache maintenance 做仲裁：D-cache 维护期间冻结流水线，I-cache 维护等待已有 `fence.i` 或 fetch response drain 后再占用 I-cache CPU port，避免抢走普通 frontend/fence 响应。
- harness remote-bitbang server

### 验证

```bash
make verilator-jtag
openocd -f openocd/ionsoc-rbb.cfg
make openocd-smoke
```

`make openocd-smoke` 已覆盖 TAP identify、CPU examine、halt/resume、OpenOCD fence/postexec 探测、直接 DMI-SBA SRAM 写读，以及 `IonCacheCtl` cache maintenance。日志应包含 `progbufsize=2`、`ION_OPENOCD_SBA_OK` 与 `ION_OPENOCD_CACHE_OK`，且不应再出现 fence execution error。完整调试功能仍需要继续补真实 hart program buffer 执行入口、cache 一致性和更完整 debug spec 细节。

## 11. Verilator ELF loader 与真实启动流

### 背景

早期仿真依赖 loader 直接把 `.text/.data` 放进内存并跳转。随着 TileLink/ROM/SRAM/firmware flow 完善，需要更接近真实 SoC：

- reset 从 ROM 开始。
- ROM trampoline 跳 SRAM firmware。
- firmware 接收 boot args。
- firmware 再跳 payload。

### 当前状态

`verilator_main.cpp` 仍保留 direct ELF load，便于 smoke/debug；同时新增 `--rustsbi` 模式支持：

- 多 ELF 加载。
- DTB blob 加载。
- SRAM base/size 参数化。
- `a0/a1/a2` 注入。
- boot trace。

这让 bring-up 同时保留“快速裸机测试”和“接近真实 firmware 链路”两种入口。

## 12. Linux Sv39 text patch fixmap fault

### 症状

Linux 已能通过 `make verilator-run-linux` 从 ROM trampoline、OpenSBI 进入 S-mode kernel，并打印到 `Initmem setup node 0`。这证明 OpenSBI -> Linux handoff、DTB、early console 和早期内存初始化链路已经走通。

继续把期望点推到 `Memory:` 时仍失败：

```bash
env LINUX_EXPECT_UART='Memory:' LINUX_MAX_CYCLES=120000000 make verilator-run-linux
```

当前日志显示：

```text
Unable to handle kernel paging request at virtual address fffffffffebfa030
Current swapper pgtable: 4K pagesize, 39-bit VAs, pgdp=0x00000000403cb000
[fffffffffebfa030] pgd=0000000000000000, p4d=0000000000000000, pud=0000000000000000
epc : 0xffffffff8000771e
ra  : 0xffffffff80007888
status: 0000000000000100 badaddr: fffffffffebfa030 cause: 000000000000000d
```

`epc` 落在 `patch_unmap` 跳入 `__set_fixmap` 附近，`ra` 落在 `patch_insn_write`。进入 fault 前的 boot trace 显示 `a3=0xfffffffffebfa000`，即 Linux text patch 使用的 `FIX_TEXT_POKE0` fixmap page。

### 已确认事实

- Linux 此时已在 Sv39：`satp = 0x80000000000403cb`。
- `swapper_pg_dir` 符号地址为 `0xffffffff801cb000`，物理页为 `0x403cb000`。
- fault VA `0xfffffffffebfa030` 的 Sv39 PGD index 是 511，对应根页表项地址 `0x403cbff8`。
- LSU/PTW trace 显示 PTW 请求 `0x403cbff8`，最终返回 `0x0000000000000000`，于是报 store page fault。
- `patch_insn_write` 通过 `FIX_TEXT_POKE0` 调用 `__set_fixmap` 后，再对返回的 fixmap VA 调用 `copy_to_kernel_nofault()`。
- `__set_fixmap` 按运行时 `pgtable_l5_enabled/pgtable_l4_enabled` 和 `kernel_map.page_offset` 计算 fixmap VA 与 `fixmap_pte` 下标。
- `setup_vm_final()` 会用 `create_pgd_mapping(swapper_pg_dir, FIXADDR_START, __pa_symbol(fixmap_pgd_next), PGDIR_SIZE, PAGE_TABLE)` 建 final fixmap 顶层映射。

### 已排除/收窄

项目内基础 `sv39` payload 已通过：

```bash
make regress
# simulator/build/difftest-matrix/sv39.log: HIT GOOD TRAP
```

另外新增 `simulator/payloads/sv39_fixmap.S` 作为定向诊断。它显式建立高半区 fixmap 映射：

```text
root[511] -> l1[501] -> l0[506] -> 0xfffffffffebfa000
```

并在启用 Sv39 后通过该 VA store/load。Linux profile binary 下运行结果为 `test passed`。这说明当前故障不像是“硬件完全不能访问 Sv39 高半区 fixmap VA”，更可能是 Linux final fixmap 页表建立、运行时 VA layout 或相关初始化顺序没有把 `swapper_pg_dir[511]` 建好。

### 下一步

需要继续追踪：

- `setup_vm_final()` 实际传给 `create_pgd_mapping()` 的 `FIXADDR_START` 在 Sv39 下对应哪个 PGD slot。
- `patch_insn_write()` 中 `FIX_TEXT_POKE0` 计算出的 fixmap VA 为什么落在 slot 511。
- `pgtable_l4_enabled/pgtable_l5_enabled/kernel_map.page_offset` 在 `setup_vm_final()` 和 `patch_insn_write()` 两处是否一致。
- 是否需要修 SoC 的页表/缓存一致性，还是需要调整 Linux 配置、DTB/bootarg 或内核 VA layout。

## 13. 当前剩余风险

- Linux 仍只是 early boot 里程碑通过，还未到 `Memory:`，更未证明 rootfs/userspace 完整启动。
- CSR PMU 事件号目前是 IonSoC 平台定义，尚未做更完整的 RISC-V Sscofpmf/overflow 语义。
- Sv39 页表 walk 已接入 IF/LSU；TLB、ASID、accessed/dirty 自动更新和完整 Linux 后续压力仍需继续补齐。
- PLIC 已有 level gateway busy/complete 语义；edge/configurable gateway 和 AIA 未实现。
- Cache line 太小，直接映射，性能有限。
- Atomic reservation 只适合单 hart。
- Debug Module 仍是 OpenOCD bring-up 子集。
- TileLink 地址宽度默认 32-bit，未来扩展高地址需要统一。
