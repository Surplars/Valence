# FPGA 启动：当前板级配置与早期实验

## DDR50 candidate (2026-09-30)

An independent `soc_top_ddr` / `BoardSocTop(externalDdr=true)` profile now
uses a 512 MiB AXI DDR window at `0x80200000..0xA01FFFFF`, a 50 MHz CPU
and 1.5 Mbaud UART. The existing UltraRAM bitstream is the board-validated
baseline. DDR electrical calibration remains unverified. The retained repaired/
post-route optimized checkpoint meets 50 MHz (WNS +0.001 ns, WHS +0.008 ns),
but only has 1 ps setup margin; no DDR bitstream/on-board test was performed.
The original candidate impl_1 still records the first failed route; use the
separate optimized_routed.dcp documented below. DDR firmware reserves
`0xA01FC000..0xA01FFFFF`; host
`--memory ddr` allows 512 MiB minus 16 KiB per download. The new ROM COE
must be included in the bitstream; the default URAM limit stays 1008 KiB.
Details and build commands:
[PL DDR4 integration](../fpga/zu15eg/pl-ddr4-integration.md).

## 当前入口：ZU15EG Board40（2026-09-30）

当前上板顶层为 `soc_top` → `BoardSocTop`，不是下面的早期 `FpgaRomTop/FpgaPlatformTop`，
也不是用于旧 OOC 筛选的 `CurrentSocTimingTop/CompactSocTimingTop`。
完整器件已确定为 `xczu15eg-ffvb1156-2-i`，Windows Vivado 2025.1 环境已经可用。
板级 XDC 和 200 MHz 差分时钟输入已接好；`clk_wiz_0` 配置输出 40 MHz。
这是 PL RISC-V SoC，不使用 PS Cortex-A53/DDR，也不以 PS 标称频率推断本核 Fmax。

- ROM：`0x80000000` 起 128 KiB，BMG 双读端口、1 周期读，用 `bootrom.coe` 初始化。
- RAM：`0x80200000` 起 1 MiB，XPM UltraRAM、3 周期读；顶部 16 KiB 由 ROM monitor 使用。
- 启动：ROM monitor 保留 RAM/ALU/TMR/ECHO，增加 UART 下载/运行；应用下载到 RAM，CRC 通过后跳转。
- 入口：`make fpga-board-firmware`、`make fpga-board-rtl`、`make gsim-board-boot-test`。
- 当前工程：`D:\TOOLS\projects\vivadoProjects\ZU15EG\ZU15EG.xpr`；唯一活动板级 RTL 目录为
  `E:\VM\Share\Valence-rtl\board-40m`，板级 top/镜像/下载器在工程 `src\board40`。

操作说明、串口命令、链接脚本与 ROM 协议见 [板级工程说明](../fpga/zu15eg/README.md) 和
[固件说明](../fpga/firmware/README.md)。软件必须按 [Board40 datasheet](soc-datasheet.md)
使用新地址；其中 DMA 仍有旧地址校验的板级勘误，不应作为当前可用复制设备。

已通过端到端 GSIM 下载/执行/重复下载、ROM/RAM 定向检查；Vivado 确认 1 MiB RAM 使用
32 个 URAM，并通过两个小 IP 构建和整板 RTL elaboration。**新板级 40 MHz 尚未完成
post-route 签核或本版上板回归**。首次切换这版硬件/ROM 需重新生成 bitstream，
之后仅改 RAM 应用可只编译并串口下载。报告口径见 [Windows 时序验证](fpga-timing-windows.md)。

## 历史范围：独立同步 ROM/RAM 启动实验

下文保留 `FpgaRomTop/FpgaPlatformTop` 的实现合同、旧命令与测量记录；其中“当前”“尚无”
描述该实验阶段，不覆盖上面的 Board40 或 Linux GSIM。小容量、旧 RAM 地址和测试结果
不得直接用作当前板级软件合同。历史数据不删除，也不把未测量项目补写为已通过。

## 初始实施合同（后续顺序预取扩展见下文）

新核使用独立 Chisel 双存储体同步 ROM，不修改旧 SoC 的 BlackBox ROM。
每个存储体为 32 位 SyncReadMem，偶/奇 word 分银行，一个请求可从任意 4 字节对齐 PC 读取两条指令。
请求握手后一周期响应，允许响应背压；响应停顿时锁存数据和逐 word 错误位保持稳定。
没有组合读，也不复位整块存储器。
ROM 初始化文件由 RTL 导出器拆为两个十六进制文件。GSIM 通过仅测试构建具有的编程端口装入相同格式数据。
越出 ROM 地址窗的 word 返回 0 且附带逐 word 错误位；前端将其转换为 ROB 中按序发生的
取指访问异常（cause 1、`tval=出错指令 PC`）。尚无指令 MMU。

取指适配器单在途，保存请求 PC，缓存一组响应；仅当当前 PC 命中响应中的对应 word 才向核心供指，
部分接受后保留未消费 word。请求被背压时地址稳定，跳转不撤回已呈现请求；旧响应收回后再处理目标 PC。
此处的裸核 `FpgaIntegerCore` 不支持执行 FENCE.I；机器核通过前端失效支持 TileLink RAM 中的代码执行，见[TileLink 取指路径](tilelink-fetch.md)。
本阶段优先确认同步存储与恢复的接口正确性，没有顺序预取，不能保证每周期双发射。
理想供指 IPC 基准保持独立，FPGA 版本必须单独报告性能。

目标是支持两条/次 ROM 读取，并明确所有寄存器边界；PRF、SQ 与选择网络尚未按 BRAM/LUTRAM 重构。

## 入口与移交

- `make gsim-fpga-fetch-test`：同步 ROM、独立取指握手、小 ROB 核连接 ROM 的 NEMU 差分，
  以及 ROM 上、下边界逐 word 取指访问异常。
- `make fpga-rtl FPGA_IMAGE=build/gsim/bare-program.bin`：导出 `build/fpga` 中的 SV 与两个 ROM 初始化文件。
  镜像必须是当前已支持指令子集、链接到 0x80000000 的纯指令二进制，容量默认 4096 words。
  `FPGA_ROM_WORDS` 与 `FPGA_OUT` 可调整；不足部分填 0，超容量或非 word 对齐镜像拒绝导出。
- 在安装 Vivado 的机器上，复制整个导出目录和 `fpga/vivado-ooc.tcl`，运行：

```sh
vivado -mode batch -source fpga/vivado-ooc.tcl -tclargs build/fpga FULL_PART 10
```

`FULL_PART` 必须替换为包括封装和速度等级的完整器件名，脚本检查是否被本机 Vivado 精确识别。
`10` 是实验时钟周期（ns），不是达到 100 MHz 的证明。脚本运行独立 IP 综合、布局布线，
输出资源、时序、未约束路径和 routed checkpoint；不生成 bitstream，不配置板级引脚。
外部数据口/提交口的 I/O 延迟尚未约束，因此仅评估内部寄存器路径，不构成板级时序签核。
脚本在当前无 Vivado 环境中未执行，最终选板后仍须补时钟、复位、I/O 和外部存储平台。

导出的是 `FpgaRomTop`（双发射核＋同步 ROM），数据内存仍需外部有序响应端口。
不是完整 SoC：没有 Zynq PS/DDR、MIG、UART 或下载启动平台。默认不启用提前 RAM 写确认。
旧 SoC 的 ROM 保留在历史接入路径中，新核没有引用它。

## 本机验证记录

RTL 已通过 CIRCT/firtool 导出；两个初始化文件交错重组与输入二进制逐字节一致，剩余容量填零。
生成代码使用 `ENABLE_INITIAL_MEM_` 宏包裹 `$readmemh`，Vivado 脚本显式开启该宏；自行接入工程时也必须开启。
导出 ROM 默认没有编程写口，GSIM 专用构建才有；编程口仅用于模拟配置时初始化存储，不在运行期间使用。
默认导出未声明普通 RAM 窗口，数据 load/store 使用保守的队首许可路径，平台接入后再配置 RAM 属性。

定向 GSIM：2,796 次 ROM 事务（含 1,345 次奇 word PC）、8,209 个响应停顿周期；
取指适配器验证 323 次有效供指、1,510 次返回时 PC 已改变的响应、4,893 次请求背压。
同步 ROM＋ROB8/PRF36 核运行循环、直接跳转、跨 word 对齐的 AUIPC/JALR 和精确非法停止，
208 条正常提交经独立求值与 NEMU 比对，随机提交背压下 160 周期至停止。
该小循环可复用一组缓存指令，不能用这项周期数推断直线程序吞吐、FPGA MHz 或完整 SoC 性能。

日志：`build/gsim/fpga-fetch.log`、`build/gsim/fpga-export.log`。Vivado Tcl 仅检查了语法完整性，
实际 Vivado 命令尚未执行；存储体是否映射为 BRAM，须以综合资源报告为准。

最终 `make test` 通过：Scala 18 项、完整 GSIM/NEMU 回归及负向注入；新增 FPGA 同步取指测试纳入默认验收。
原两组裸核各 74 个程序、60,350 条提交，理想供指 IPC 报告与修改前完全一致。日志：`build/gsim/fpga-final.log`。

## 顺序预取优化合同

保持最多一个未返回请求，允许旧响应返回与下一请求同周期握手；两个带 PC 的 packet 缓存保留当前及下一组。
缓存/返回响应命中当前 PC 时供指，同时仅预取其顺序后继组；后端停顿时不继续向前无限预取。
新响应替换非当前组，跳转后的旧响应只能作为带地址的缓存项保存，不能按旧路径供指。
请求背压仍锁定地址；复位以外不撤回已呈现请求。支持响应到供指旁路，ROM 数据可直接进入译码，
请求地址计算仅使用 PC/请求元数据，不依赖译码结果或同周期 accepted，避免组合反馈。
目标为一周期 ROM 下顺序流稳定供给两条/周期；随机延迟仍受单在途限制。
旁路增加 ROM 输出至译码的组合路径，实际 Fmax 尚未验证，不能只按 IPC 声称实机更快。


### 顺序预取实测

同一 ROM、ROB8/PRF36、相同指令与参考模型，基线先用旧前端测量。
240 条 `ADDI x0,x0,1`（不写架构寄存器、无提交背压）从启动到最后退休由 **362 降至 123 周期**，
吞吐从 0.663 提升至 1.951 指令/周期。这是取指吞吐测试，不包含寄存器分配压力、访存或真实程序混合。
原循环/跳转程序 208 条提交在相同随机提交背压下由 159 降至 158 个退休周期，收益仅一周期；
不得将直线吞吐收益推广到所有程序。

独立驱动验证一周期存储器下连续 128 周期双供指，同时检查完整停止、部分消费及缓存填满后不继续预取。
随机请求背压、1～9 周期响应和 PC 改变测试检查 687 次有效供指、1,723 次非当前 PC 的返回响应、
5,424 次请求背压。旧响应带原 PC 安装，不会作为新 PC 的指令使用；重叠请求更新所有权经过检查。
这段历史裸核预取验收使用只读 ROM；机器核后续已接 FENCE.I 与前端失效，见[TileLink 取指路径](tilelink-fetch.md)。

定向日志：`build/gsim/prefetch-before.log`、`build/gsim/prefetch-focused.log`。
继续保留最多一个未返回请求；高延迟取指、多请求在途仍是后续优化项；跨 packet 拼接现已补充，见下文。

顺序预取最终验收：`make test` 通过 Scala 18 项、完整 GSIM/NEMU 回归与负向注入；
两组原裸核各 74 个程序、60,350 条正常提交，理想供指 IPC 结果与修改前完全一致。
同步核另验证循环 208 条及直线 240 条提交。日志：`build/gsim/prefetch-final.log`。

## 同步数据 RAM 合同

新建 64 位、8 个字节写使能的 Chisel SyncReadMem RAM，默认 0x80010000 起 4 KiB。
每周期最多一个读或写请求，请求握手后一周期返回响应，按序；响应阻塞时保持数据与 error，
用两个寄存的响应额度覆盖读流水级及弹性响应队列，最多保留两个未消费结果。
request.ready 不组合依赖 response.ready，避免与 LSU 的零延迟兼容路径形成组合环；
无背压时每拍接受请求，额度用尽后停发，释放额度的下一拍恢复。每拍只选读或写，消除同拍读写同地址的不确定语义；
前一拍写入对后一拍读取可见。返回读数据为对齐 64 位 beat，写数据和 mask 使用实际字节通道。
完整地址范围、自然对齐、size/mask 必须一致，不满足时返回 error，错误写无任何副作用。
写成功只在握手时真正执行写入后确认；这个固定 RAM 满足 store buffer 的无错误区域承诺。

内存内容不通过 reset 清零，测试由真实数据口初始化；RTL 导出使用初始化文件。
目标单拍请求吞吐、单拍响应延迟，存储能否映射到 BRAM 与实际 Fmax 仍须 Vivado 验证。
本轮以同步 ROM＋CPU＋同步 RAM 为执行平台，普通 RAM 属性显式配置，支持已验证的 store buffer。
不包含外设、中断、MMU、DDR 或完整 SoC 地址映射。


### 同步执行平台入口与实测

- `make gsim-platform-test`：RAM 独立验证及同步 ROM＋ROB32/PRF64 双发射核＋4 KiB RAM 的 NEMU 差分。
- `make fpga-platform-rtl FPGA_IMAGE=build/gsim/bare-program.bin`：导出 `build/fpga-platform`，
  顶层 `FpgaPlatformTop` 已内部连接数据 RAM，显式开启普通 RAM 属性与四项 store buffer。
  `FPGA_PLATFORM_OUT` 和 `FPGA_ROM_WORDS` 可调整；RAM 初始化为零，测试初始化通过真实数据口完成。
  旧 `make fpga-rtl` 仍导出外接数据口的 `FpgaRomTop`。
- 集成平台的 Vivado 入口（仍需真实环境验证）：

```sh
vivado -mode batch -source fpga/vivado-ooc.tcl -tclargs build/fpga-platform FULL_PART 10 FpgaPlatformTop
```

复制整个导出目录，包括两个 ROM 文件和 `ram_zero.hex`。完整器件名、时钟和 I/O 约束的限制同上。
本平台仍无 UART、DDR、CSR、中断或 MMU，不是完整 SoC。

C 栈/数组程序返回 `a0=42`，每次正常退休 1,310 条；独立 ISA/字节 RAM 模型与 NEMU 逐条比较，
结束后通过真实 RAM 端口扫描全部 4 KiB，并验证 197 次外部 store 的数据和顺序。

| 提交背压 | 周期 | IPC |
| --- | ---: | ---: |
| 无 | 1,529 | 0.856769130 |
| 随机，种子 17 | 1,885 | 0.694960212 |
| 随机，种子 8191 | 1,880 | 0.696808511 |

窗口从 CPU 解除复位到最后正常退休，排除初始化和最终 RAM 扫描。
报告单独保存为 `build/gsim/platform-ipc.json`；原 `ipc.json` 仍是理想供指基准，不能混用。
无背压运行中 fetchWait=260、memoryBusy=883；这些是可重叠的状态周期，不能相加当作性能损失。
原理想供指同一 C 程序为 1,507 周期；平台同时改变了取指和数据存储实现，22 周期差值不能全部归因于取指。

独立 RAM 验证连续 256 拍请求/响应，以及 5,196 次随机事务（其中 2,037 次错误请求）、
9,816 个响应停顿周期，覆盖所有访问宽度、字节掩码、边界、地址溢出及读写相邻依赖。
平台另检查真实 RAM 返回的 load/store 访问错误：精确停在故障指令，年轻 store 不得写入；
异常检查使用独立预期，不驱动 NEMU 进入尚未支持的特权陷阱路径。
人为篡改寄存器的负向用例确认 NEMU 能检出差异。

最终 `make test` 通过 Scala 19 项和完整 GSIM/NEMU 回归；新增平台 5 个程序、3,934 条正常提交、
2 个访问错误停止。原两组裸核各 74 个程序、60,350 条提交，理想供指 IPC 测量完全不变。
日志：`build/gsim/platform-final.log`；RTL 导出日志：`build/gsim/platform-export.log`。
RAM 地址检查到写使能、ROM 响应旁路到译码仍有组合路径；BRAM 推断、资源和实际频率尚无 Vivado 实测。
当前 RAM 单端口每拍最多一笔访存，不能因后端扩大到 4/6 发射就声称访存带宽同比提高。

## 跨 packet 双路供指合同

当前 PC 位于缓存 packet 的第二个 word 时，允许从另一缓存项或本周期带原 PC 的响应中
查找 PC+4，拼成第二路指令；仅第一路也有效且 enable 时第二路有效。每路独立校验地址，
重定向后的旧响应不得按新地址使用，重复缓存项按固定优先级选择（ROM 内容不可变）。
不增加缓存容量或在途请求，不改变请求锁定、响应排空和顺序预取策略；缺失第二路时继续单路供指。
这消除已到达数据的跨组气泡，但不保证错位流在现有预取策略下每拍双供指。
新增的是第二路地址匹配和选择路径，Fmax/面积尚未测量。验收包括缓存拼接、响应旁路拼接、
停顿、部分消费、重定向及默认同步 C 平台的 NEMU 差分与周期测量。


### 跨 packet 供指验收

新增定向检查：PC 停在第一组的第二条指令，分别在后继组当拍返回及已缓存时要求双路有效；
响应额外延迟 3 周期时第二路必须保持无效，禁止凭空补指令。停止消费时仅请求两组，
关闭 enable 时两路都无效。原随机 PC/背压测试继续检查每个有效 lane 的地址和数据。

同步 C 平台最新结果（同一镜像和配置）：

| 提交背压 | 修改前周期 | 修改后周期 | 修改后 IPC |
| --- | ---: | ---: | ---: |
| 无 | 1,529 | 1,529 | 0.856769130 |
| 随机，种子 17 | 1,885 | 1,923 | 0.681227249 |
| 随机，种子 8191 | 1,880 | 1,879 | 0.697179351 |

无背压负载无收益；随机背压用例有改善也有退化，供指改变会影响动态调度、访存转发及背压相位，
这组结果不能作为普遍加速证据。连续双供指 128 拍、直线程序 240 条 / 123 退休周期保持不变。
本次补齐跨组供指能力，没有改变预取深度，也尚未解决错位顺序流的持续吞吐限制。
最新报告仍为 `build/gsim/platform-ipc.json`，修改前快照为 `build/gsim/platform-before-stitch.json`。
定向日志：`build/gsim/stitch-focused.log`；集成 RTL 导出成功：`build/gsim/stitch-export.log`。

跨 packet 最终 `make test`：Scala 19 项、完整 GSIM/NEMU 回归和负向注入均通过；
两组原裸核各 74 个程序 / 60,350 条提交，理想供指 IPC 完全不变。
日志：`build/gsim/stitch-final.log`。

集成核心现已接 RV64M 六周期流水乘法、独立迭代除法及 B（Zba/Zbb/Zbs）组合执行；原同步 C 基准仍按 RV64I 编译。
时序与验证口径见 [RV64M](rv64m.md) 和 [RV64B](rv64b.md)，不依据 GSIM 周期数宣称 FPGA MHz 或 DSP 资源映射。
