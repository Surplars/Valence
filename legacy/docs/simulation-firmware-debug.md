# Simulation, Firmware, and Debug

> 历史参考：Verilator、旧 emu 和旧 ChiselSim 仿真入口已退役，本文中的相关运行命令不再适用。当前验证见 [GSIM 说明](../../simulator/gsim/README.md)。

## 构建工具

项目主要使用 Mill 构建 Chisel/Scala：

```bash
mill -i IonSoC.compile
mill -i IonSoC.test
mill -i IonSoC.test.runMain sim.TopMain
```

Makefile 封装了常用 RTL 生成、payload 编译和 Verilator 运行：

```bash
make sim-verilog
make sim-verilog-icache
make sim-verilog-firmware
make payload
make verilator
make regress
make regress-icache
make verilator-run-rustsbi
make verilator-run-linux
```

依赖：

- `riscv64-unknown-elf-gcc`
- `riscv64-unknown-elf-objcopy`
- `verilator`
- `dtc`
- Rust nightly / RustSBI 需要的 target
- `llvm-objcopy` 或 `rust-objcopy` 或 `riscv64-unknown-elf-objcopy`

## RTL 生成 Profile

`src/test/scala/sim.scala` 定义三个 emission entry：

- `sim.TopMain` -> `build/rtl`
- `sim.McuTopMain` -> `build/rtl-mcu`
- `sim.ICacheTopMain` -> `build/rtl-icache`
- `sim.FirmwareTopMain` -> `build/rtl-firmware`

对应 Make target：

```bash
make sim-verilog
make sim-verilog-mcu
make sim-verilog-icache
make sim-verilog-firmware
```

Firmware profile 使用 `SoCProfiles.LinuxCapablePLIC.copy(mmu = false)`，即 16 MiB SRAM、I/D cache、PLIC、CLINT、UART，但 MMU 暂时关闭。

常规本地测试优先使用：

```bash
make test-fast
```

`test-fast` 覆盖配置、bus、设备、PLIC、L1 cache、CSR 和 IF。更细的本地目标如下：

```bash
make test-profile
make test-bus
make test-devices
make test-clint
make test-uart
make test-plic
make test-debug
make test-cache
make test-core-fast
make test-core-mem
```

设备测试已经拆成独立 spec：`CLINTSpec`、`TLDeviceSpec`、`UartSpec` 和 `PLICSpec`。Debug 相关测试在 `src/test/scala/debug`。改单个外设时优先跑对应 Make target，或直接运行单个 spec：

```bash
mill -i IonSoC.test.testOnly device.UartSpec
mill -i IonSoC.test.testOnly debug.DebugModuleSpec
```

顶层 SoC/JTAG/debug halt 属于慢测，放在：

```bash
make test-slow
```

## Payload

裸机 payload 位于 `simulator/payloads`。

常用 payload：

- `timer.S`: timer/CLINT smoke。
- `clint32.S`: 32-bit CLINT high/low word 访问。
- `tlerror.S`: unmapped/denied response smoke。
- `amo.S`: A 扩展 smoke。
- `hazard.S`: pipeline hazard smoke。
- `bitmanip.S`: Zba/Zbb/Zbs 常用指令 smoke。
- `plic.S`: M-mode PLIC smoke。
- `plic_s.S`: S-mode PLIC/delegation smoke。
- `uart_irq.S`: harness 注入 UART RX byte，验证 UART RDI -> PLIC source 1 -> M-mode external interrupt -> claim/complete。
- `firmware_trampoline.S`: ROM 到 firmware SRAM 的 trampoline。
- `firmware_probe.S`: firmware bring-up probe。
- `sbi_smoke.S`: RustSBI 跳入 S-mode 后的 SBI console smoke。
- `sv39.S`: 基础 Sv39 页表 walk smoke。
- `sv39_fixmap.S`: 高半区 fixmap VA 定向诊断，用来验证 Linux text poke 使用的 `0xfffffffffebfa000` 附近地址。

Linker scripts：

- `payload.ld`: ROM `0x80000000` + default SRAM `0x10000000`。
- `firmware.ld`: firmware probe 放在 `0x40000000`。
- `sbi_payload.ld`: S-mode payload 放在 `0x40100000`。

## Verilator Harness

主 harness 是 `simulator/harness/verilator_main.cpp`。

能力：

- ELF program header loader。
- 支持 ROM/SRAM 按地址加载。
- 支持 firmware profile 的多 ELF 加载：trampoline、RustSBI、S-mode payload。
- 支持 DTB blob 加载。
- 可以注入 `a0/a1/a2`。
- UART stdout 捕获和可选 stdin。
- CLINT/PLIC/外部中断仿真入口。
- JTAG remote-bitbang server。
- boot trace / CPU trace / IRQ trace / DMI trace。
- 可选 FST trace，默认不生成波形文件。

常用环境变量：

| 变量 | 用途 |
| --- | --- |
| `ION_MAX_CYCLES` | 最大 simulator tick；当前一个完整时钟周期约为 2 tick（变量名为历史命名） |
| `ION_TRACE_BOOT=1` | 打印 ROM/SRAM/payload/trap/cache boot trace |
| `ION_TRACE_CPU=1` | 打印 CPU trace |
| `ION_TRACE_PC_START/END` | 限制 CPU trace PC 范围 |
| `ION_TRACE_LSU_PTW=1` | 打印 LSU/PTW translation trace |
| `ION_TRACE_LSU_PTW_VADDR` | 限制 LSU/PTW trace 到指定 VA |
| `ION_TRACE_DMEM=1` | 打印 D-memory/arbiter trace |
| `ION_TRACE_DMEM_ADDR` | 限制 D-memory trace 到指定地址 |
| `ION_TRACE_DMEM_PC_START/END` | 按 PC 范围限制 D-memory trace |
| `ION_TRACE_IRQ=1` | 打印中断状态 |
| `ION_TRACE_DMI=1` | 打印 DMI/JTAG debug 状态 |
| `ION_PERF=1` | 打印 cycles、retired、IPC 和 stall 分解 |
| `ION_TRACE_COMMIT=1` | 实时打印架构顺序的 retire/trap 事件；长仿真建议只在缩小范围后打开 |
| `ION_DEBUG_HISTORY` | 内存中保留的最近 retire/trap 事件数，默认 256；失败时自动打印，设为 0 可关闭 |
| `ION_DEBUG_HISTORY_ALWAYS=1` | 通过时也打印最近架构事件 |
| `ION_NO_RETIRE_TIMEOUT` | 连续多少个上升沿 cycle 无退休即停止并打印历史；默认 0，WFI 场景应保持关闭 |
| `ION_STOP_PC` | 指定 PC 一退休就停止并打印提交历史，用于快速截断到首个可疑点 |
| `ION_TRACE_WAVE=1` | 生成 `simulator/build/wave.fst`；需要同时以 `TRACE=1` 构建 |
| `ION_TRACE_WAVE_START/STOP` | 按 simulator tick 限制波形窗口；一个 tick 是半个时钟周期 |
| `ION_TRACE_WAVE_PC` | 等到指定 PC 退休或产生 arch event 后才打开波形 |
| `ION_TRACE_WAVE_LEN` | PC 命中后记录的 tick 数；0 表示持续到 STOP/仿真结束 |
| `ION_TRACE_WAVE_PATH` | 覆盖 FST 输出路径 |
| `ION_TRACE_WAVE_DEPTH` | 配合 `ION_TRACE_WAVE_SCOPE` 使用的 scope 深度，默认 99，最小 1 |
| `ION_TRACE_WAVE_SCOPE` | 可选层次过滤，例如 `TOP.SimTop.core.lsu`；不设置时 DEPTH 不限制全局层次 |
| `ION_EXPECT_UART` | UART 预期字符串 |
| `ION_ACCEPT_UART_MATCH=1` | UART 命中 `ION_EXPECT_UART` 即可作为仿真通过条件，适合不会写 `a7=93/a0=0` 退出哨兵的 OS |
| `ION_STOP_ON_UART_MATCH=1` | UART 命中 `ION_EXPECT_UART` 后立即停止仿真 |
| `ION_SRAM_BASE/SIZE` | 覆盖 SRAM 地址/大小 |
| `ION_DTB_ADDR` | DTB 加载地址 |
| `ION_BOOT_A0/A1/A2` | 注入启动寄存器 |
| `ION_UART_STDIN=1` | 将 stdin 接入模拟 UART RX |
| `ION_JTAG_RBB_PORT` | remote-bitbang 端口 |
| `ION_JTAG_ONLY=1` | JTAG-only 运行模式 |

默认 Verilator binary 不编译波形 trace 支持，以减少生成代码、编译时间和运行开销。普通失败无需波形：harness 始终维护一个定长的架构事件环，测试失败或 watchdog 触发时，会按时间顺序打印最近的 commit 与 trap。commit 使用退休 PC/指令，而不是可能处于预测或 stall 状态的取指 PC；压缩指令的 `len=2`，但 `instr` 是解压后的 32-bit 指令。异步 cache/MMIO fault 的 trap `instr` 目前是 best-effort，可能为 0；定位异常时应以 `pc/cause/tval` 为准。

普通 Verilator C++ 构建默认限制为 2 个并发任务、使用 `-O1` 并自动接入 ccache，避免高核心数主机并发编译大型生成文件时被 OOM killer 终止。需要最终仿真性能时再显式覆盖：

```bash
make verilator-build VERILATOR_BUILD_JOBS=8 VERILATOR_OPT_FAST=-O3
```

若内存仍紧张，保持 `VERILATOR_BUILD_JOBS=1`；热重建会继续受益于 ccache。

需要波形时，`TRACE=1` 使用单独的 FST binary：

```bash
TRACE=1 ION_TRACE_WAVE=1 make verilator-run-perf
```

`TRACE=1` 会使用独立的 `simulator/build/obj-trace*` 目录，不会覆盖普通 smoke/perf binary。FST 通常比 VCD 更小，GTKWave 可以直接打开 `simulator/build/wave.fst`。

Linux 长启动建议分两次重放。第一次使用普通 fast binary，从 `[sim-fail]` 或 watchdog 得到失败 tick；第二次只记录附近窗口：

```bash
TRACE=1 ION_TRACE_WAVE=1 \
  ION_TRACE_WAVE_START=1990000 ION_TRACE_WAVE_STOP=2010000 \
  make verilator-run-linux
```

如果已知可疑退休 PC，也可以直接触发：

```bash
TRACE=1 ION_TRACE_WAVE=1 \
  ION_TRACE_WAVE_PC=0xffffffff80001234 ION_TRACE_WAVE_LEN=20000 \
  make verilator-run-linux
```

Verilator/FST 没有失败前滚动波形缓存，因此 PC trigger 只能记录命中时刻及之后；要观察失败前状态，需要先用 fast run 定位 tick，再按 `START/STOP` 重放。`ION_NO_RETIRE_TIMEOUT` 的单位是完整上升沿 cycle，和波形窗口的半周期 tick 不同；Linux idle/WFI 可能合法地长期无退休，不应默认开启 watchdog。

## DiffTest 快速路径

DiffTest 使用运行时共享内存，DUT 与 NEMU 从同一个 ELF 镜像初始化。payload 内容不再固化进 Chisel 生成的 SRAM，因此第一次构建模拟器后，切换裸机 payload 不会重新生成 RTL 或重编 Verilator：

```bash
make difftest-run-payload PAYLOAD_SRC=simulator/payloads/basic.S
make difftest-regress
```

本机热运行 `basic.S` 的参考值约为 0.6 秒、20 MiB 峰值内存；DiffTest 编译默认限制为 2 个并发任务，可用 `DIFFTEST_BUILD_JOBS=` 显式覆盖。开发构建默认使用 `-O1` 并通过 ccache 缓存 Verilator 生成的 C++；需要测最终仿真性能时可传入 `DIFFTEST_CXX_OPT=-O3`。第一次使用新优化等级仍是冷构建，后续 RTL 重生成可复用内容未变化的编译单元。

本机 Linux DiffTest C++ 冷编译从单线程 `-O3` 的约 98--115 秒降到两线程 `-O1` 的约 25 秒；包含 Mill elaboration 和 Verilator 重新生成、且生成内容可命中 ccache 时，整条强制重建约 11 秒，其中 C++ 阶段约 1.4 秒。真实小改动耗时取决于生成 C++ 的变化范围，通常位于这两个端点之间。

Linux 使用独立的 RTL、Verilator 和 NEMU profile，不会覆盖裸机模拟器。它会把 ROM trampoline、OpenSBI、kernel 和 DTB 合并为一个带多个 `PT_LOAD` 的 ELF，并由专用 trampoline 提供 `a0/a1/a2` 启动参数：

```bash
make difftest-emu-linux
make difftest-run-linux LINUX_KERNEL_ELF=/path/to/Image.elf
```

快速缩小首个分歧时，先限制退休指令数；达到上限是正常停止，真正的差异会自动打印最近 commit、REF/DUT GPR 和 CSR：

```bash
make difftest-run-linux \
  LINUX_KERNEL_ELF=/path/to/Image.elf \
  LINUX_DIFFTEST_MAX_INSTR=500000 \
  LINUX_DIFFTEST_MAX_CYCLES=5000000
```

Linux profile 不注入 PLIC source 2 或 UART 字节，也不使用裸机的 `a7=93` 退出哨兵，避免把 Linux syscall 误判为整机退出。NEMU 的 Linux profile 使用 `0x40000000` 内存基址，并按 IonSoC 的物理地址宽度/PMP 粒度配置；PMA 检查关闭，因为上游 NEMU 的硬编码 PMA 表仍针对另一套 SoC 地址图。

NEMU 将 HPM/event counter 固定为只读零，而 IonSoC 实现了可写计数器；DiffTest 因此只对 counter/event CSR 指令使用 `skip` 同步。MMIO 和这些实现相关计数器之外的 GPR、CSR、异常与访存仍逐条比较。

当前 OpenSBI/S-mode 集成 smoke 已在严格 DiffTest 下连续通过 4,500,000 条退休指令：OpenSBI 完成平台初始化、以 `a1=0x40f00000` 传递 DTB、切入 `0x40100000` 的 S-mode payload 并打印 `IonSoC SBI smoke`，随后在 `0x40100028` 的 `j .` 自环持续退休到指令上限。该里程碑覆盖了精确异常、EBREAK、PMP/委托、UART/DTB、MRET 到 S-mode 和 SBI console 路径；它不替代真实 RV64 Linux kernel 启动测试。

```bash
make difftest-run-opensbi-smoke
```

## 性能 Smoke

`make verilator-run-perf` 会构建 `simulator/payloads/perf.S`，运行一个固定的 load/store/ALU/branch 循环，并启用 `ION_PERF=1`。当前 baseline：

```text
[perf]: cycles=37536 retired=32818 ipc=0.8743 stall_cycles=4691 stall_pct=12.50 ifetch_stall=4714 ifetch_pct=12.56 lsu_stall=4638 lsu_pct=12.36
[perf-branch]: branches=4097 branch_rate=12.48 taken=4096 taken_pct=99.98 redirects=3 redirect_pct=0.07 pred_taken=4095 pred_taken_pct=99.95 pred_correct=4094 pred_correct_pct=99.93
[perf-lsu]: load=4101 store=8250 mmio=4 atomic=0 fence=533
[perf-overlap]: ifetch_only=4179 ifetch_lsu_overlap=535
[perf-frontend]: starved=55 queue_full=532 queue_empty=81
```

这些仿真侧事件也接入了 CSR PMU：软件可通过 `mhpmevent3..31` 选择事件号，再读 `mhpmcounter3..31`。例如 `mhpmevent3=7` 统计 branch redirect，`mhpmevent4=3` 统计 I-fetch stall，`mhpmevent5=10` 统计 LSU cache-load stall。

这个 baseline 已包含 BPU target redirect 抑制、64-bit fetch beat buffer、I-cache idle 当拍发请求、顺序 next-beat ahead fetch、4-entry `FrontendQueue`、L1 hit compare-cycle response、IFetch response-cycle enqueue、load-use 当拍解除、LSU cache-load 当拍发 D-cache 请求，以及 LSU cache-load completion slot。completion slot 让 cache load 响应当拍释放 stall，并在下一拍只提交一次；旧 baseline 中约 4096 条额外 retired 来自 stall 保持期间的重复 retire 计数，不应继续作为真实 IPC 参考。IFetch 现在在已注册的 cache response 当拍向前端队列送指令，不再额外等待 release 拍。`perf.S` 还会读取多组 HPM counter，因此 retired/cycles 同纯循环版本不完全等价。结果说明分支预测已不是主瓶颈，前端 starve 已基本消除，剩余 stall 主要来自 LSU store/fence 和 I-cache/LSU overlap。当前短热循环远小于默认 2 KiB I-cache，扩容量不是优先项。后续优化顺序应优先看 store buffer drain 合并、fence 精简和总线 beat/burst，再考虑超标量。

`[perf-frontend]` 用来判断前端队列是否仍是瓶颈：`starved` 表示 decode 端没有可用指令且 IF 正在等待，`queue_full` 表示 IF 被队列背压，`queue_empty` 表示队列为空。当前 `starved=55`、`queue_empty=81`，说明前端供给已显著改善；`queue_full=532` 也说明继续加深队列不是当前优先项。

## RustSBI Jump Flow

当前 RustSBI 路径由以下文件协同：

- `simulator/firmware/rustsbi`: RustSBI source/vendor tree。
- `simulator/firmware/rustsbi/prototyper/prototyper/config/ionsoc.toml`: IonSoC prototyper 配置。
- `simulator/firmware/ionsoc.dts`: 传给 RustSBI/OS 的设备树。
- `simulator/payloads/firmware_trampoline.S`: ROM trampoline。
- `simulator/payloads/sbi_smoke.S`: S-mode smoke payload。
- `Makefile` 的 `verilator-run-rustsbi`。

启动过程：

1. Verilator loader 将 trampoline ELF 写入 ROM。
2. RustSBI ELF 写入 SRAM `0x40000000`。
3. `sbi_smoke.elf` 写入 SRAM `0x40100000`。
4. DTB 写入 SRAM `0x40f00000`。
5. harness 在 reset 后注入：
   - `a0 = hartid = 0`
   - `a1 = dtb address = 0x40f00000`
   - `a2 = payload address = 0x40100000`
6. ROM trampoline 打印 `ROM->SRAM` 并跳到 `0x40000000`。
7. RustSBI 初始化平台，patch DTB，配置 PMP，然后跳到 S-mode payload。
8. S-mode payload 用 legacy SBI console_putchar 打印 `IonSoC SBI smoke`。
9. payload 设置 `a7=93/a0=0` 作为 harness exit sentinel。

验证：

```bash
make verilator-run-rustsbi
```

预期输出包含：

```text
ROM->SRAM
[RustSBI] INFO - Hello RustSBI!
Redirecting hart 0 to 0x00000040100000 in Supervisor mode.
IonSoC SBI smoke
[rustsbi]: gp=0, a7=93, a0=0, test passed
```

## OpenSBI / Linux Flow

Linux profile 使用独立 RTL/Verilator 输出目录：

- RTL: `build/rtl-linux`
- Verilator obj: `simulator/build/obj-linux`
- SRAM: `0x40000000..0x47ffffff`
- OpenSBI `fw_jump`: `0x40000000`
- Linux `Image` ELF wrapper: `0x40200000`
- DTB: `0x47f00000`

OpenSBI `fw_jump` 会在构建时固化下一阶段和 DTB 地址。Makefile 分别为 smoke 固化
`0x40100000` / `0x40f00000`，为 Linux 固化 `0x40200000` / `0x47f00000`；修改布局后需重建
对应的 `fw_jump.elf`，否则 OpenSBI 可能因读取空 DTB 进入 `sbi_hart_hang`。

需要截取某个可疑 PC 之前的精确提交历史时，可设置 `ION_STOP_PC=0x...`；仿真器会在该
PC 首次退役时立即停止，并按 `ION_DEBUG_HISTORY` 输出进入点之前的环形历史，无需等待全局超时。

常用目标：

```bash
make sim-verilog-linux
make verilator-build-linux
make sim-dtb-linux
make linux-image-elf
make verilator-run-linux
```

默认 Linux 目标使用：

```bash
LINUX_EXPECT_UART='Initmem setup node 0'
LINUX_MAX_CYCLES=50000000
```

这只是 early boot 里程碑。继续追完整启动时使用更深预期点：

```bash
env LINUX_EXPECT_UART='Memory:' LINUX_MAX_CYCLES=120000000 make verilator-run-linux
```

截至当前记录，该命令仍会在 Linux text patch 阶段 fault：

```text
Unable to handle kernel paging request at virtual address fffffffffebfa030
Current swapper pgtable: 4K pagesize, 39-bit VAs, pgdp=0x00000000403cb000
[fffffffffebfa030] pgd=0000000000000000
epc : 0xffffffff8000771e
ra  : 0xffffffff80007888
```

对应路径是 `patch_insn_write` 通过 `FIX_TEXT_POKE0` 临时映射内核 text page 后调用 `copy_to_kernel_nofault()`；PTW 访问 `swapper_pg_dir[511]` 的物理地址 `0x403cbff8`，最终读出 0。当前 `satp` 已是 Sv39，值为 `0x80000000000403cb`。

针对该 fault 额外保留了一个高半区 fixmap 诊断 payload：

```bash
riscv64-unknown-elf-gcc -march=rv64imac_zicsr -mabi=lp64 -nostdlib -nostartfiles \
  -Tsimulator/payloads/firmware_bswap.ld \
  -o simulator/build/payload/sv39_fixmap.elf simulator/payloads/sv39_fixmap.S

ION_SRAM_BASE=0x40000000 ION_SRAM_SIZE=0x08000000 ION_MAX_CYCLES=200000 \
  ./simulator/build/obj-linux/VSoc --payload sv39_fixmap '' simulator/build/payload/sv39_fixmap.elf
```

该 payload 显式建立 Sv39 `root[511] -> l1[501] -> l0[506]`，在启用 MMU 后写入并读回 `0xfffffffffebfa000`，当前结果为 `test passed`。这说明“高半区 fixmap VA 的硬件 PTW/load/store 路径”有定向通过证据，Linux 当前失败更可能在 final fixmap 页表建立、运行时 VA layout 或相关初始化顺序上。

## UART 模拟

硬件 `UartTx` 是 16550-like register subset，DTS compatible 为 `ns16550a`。

支持：

- THR/RBR/DLL
- IER/DLM
- IIR/FCR
- LCR/MCR/LSR/MSR/SCR
- RX ready、overrun error
- THR empty interrupt
- RX data available interrupt

Verilator harness 在 `io_uart_tx` 有效时捕获 `io_uart_byte` 并打印到 stdout。`ION_UART_STDIN=1` 可把 host stdin 注入 RX。

## JTAG/OpenOCD

JTAG 配置：

```bash
make verilator-jtag
openocd -f openocd/ionsoc-rbb.cfg
```

`openocd/ionsoc-rbb.cfg` 使用：

- adapter: `remote_bitbang`
- host: `127.0.0.1`
- port: `9824`
- IR length: 5
- expected IDCODE: `0x10e31913`
- target: `riscv`
- memory access: abstract

非交互 smoke：

```bash
make openocd-smoke
```

该目标启动 Verilator remote-bitbang，验证 TAP IDCODE、OpenOCD examine、halt/resume，通过直接 DMI 操作 `sbcs/sbaddress/sbdata` 做一次 SBA SRAM 写读，并触发一次 IonSoC 私有 cache maintenance 寄存器。smoke 同时确认 OpenOCD 能看到 `progbufsize=2`，并覆盖其 fence/postexec 探测路径。

当前 JTAG TAP 是同步到 SoC clock 的第一阶段实现，通过 TCK edge detect 驱动 TAP FSM。生产级设计应替换为真实 TCK clock domain + CDC。

Debug Module 当前支持：

- `dmcontrol`
- `dmstatus`
- `hartinfo`
- `abstractcs`
- `abstractauto`，支持 `autoexecdata0/1` 与 `autoexecprogbuf0/1`
- `command`
- `data0/data1`
- `progbuf0/progbuf1` backing register
- 安全 postexec 子集解释：`nop`、`fence`、`fence.i`、`ebreak`
- `haltsum0`
- `sbcs/sbaddress0/sbaddress1/sbdata0/sbdata1`
- halt/resume request
- GPR abstract read/write
- CSR abstract read/write
- debug CSR `dcsr/dpc/dscratch0` 子集
- hart halted 时捕获 `dpc`
- SBA 通过 TileLink 作为低优先级 master 访问系统总线，当前支持单 outstanding、8/16/32/64-bit 访问、跨 beat split、`sbreadonaddr/sbreadondata`、`sbautoincrement` 和基础 error/busy 状态
- DMI 在 SBA 忙时可返回 busy op，便于 OpenOCD 重试
- IonSoC 私有 `IonCacheCtl` DMI register，地址 `0x70`，供 debugger/SBA 流程触发 D-cache clean+invalidate 和 I-cache invalidate

`IonCacheCtl` bit 定义：

| bit | 含义 |
| --- | --- |
| 0 | 写 1 请求 D-cache whole-cache clean+invalidate |
| 1 | 写 1 请求 I-cache whole-cache invalidate |
| 8 | D-cache done sticky，写 1 清除 |
| 9 | I-cache done sticky，写 1 清除 |
| 16 | D-cache error sticky，写 1 清除 |
| 17 | I-cache error sticky，写 1 清除 |

示例 DMI 流程：

```tcl
riscv dmi_write 0x70 0x00030300 ;# clear done/error sticky bits
riscv dmi_write 0x70 0x00000003 ;# request D-cache and I-cache maintenance
set ctl [riscv dmi_read 0x70]   ;# poll until bits 8 and 9 are set
```

限制：

- program buffer 当前是 DM 内部安全解释子集，不是真实 hart 指令执行入口。`abstractcs.progbufsize=2` 仅承诺 `nop/fence/fence.i/ebreak` postexec 探测可用；load/store 等 helper 序列会返回 `cmderr`，避免误改 architectural state。
- SBA 尚未实现硬件 cache 一致性；调试器直接改内存后，应使用 `IonCacheCtl`，或让 hart 侧执行 `fence`/`fence.i`。
- OpenOCD 高级功能可能仍会触发 unsupported command。
- 若 simulator 被 kill，OpenOCD 可能卡在 remote_bitbang socket 状态，需要单独终止 OpenOCD 进程。

## 推荐测试命令

快速硬件定向：

```bash
mill -i IonSoC.test.testOnly core.CSRFileSpec core.InstrFetchSpec
```

裸机回归：

```bash
make regress
```

I-cache 回归：

```bash
make regress-icache
```

RustSBI flow：

```bash
make verilator-run-rustsbi
# 等价短名
make rustsbi-smoke
```

该目标不仅检查 `IonSoC SBI smoke` UART 输出和 `a7=93/a0=0` 退出哨兵，还要求 PC 实际进入过 firmware SRAM 区间和 S-mode payload 区间。若失败，harness 会打印最终 `pc/instr/mtvec/mepc/mcause/mtval` 以及 boot-flow 判定结果。

带 boot trace：

```bash
ION_TRACE_BOOT=1 make verilator-run-rustsbi
```
