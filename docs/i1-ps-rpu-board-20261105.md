# ZU15EG：PS DDR、RPU 裸机加载与 PS GEM3

## 2026-11-06 当前检查点

R8 CPU/VPU/system 均为 300 MHz，已完成真实板卡冷启动：`PASS_RPU_LOADED_RV_REAL_DDR_SELFTEST`。RPU phase=5/status=0，PL started=1，RV state=3/error=0；镜像 CRC=0x708d26b9，运算校验=0x5b380cab，实读 misa=0x80000000003411ad（H=1、V=1）。当前使用 PLIC M/S 两个上下文、机器定时器和 MSIP；UART 源 3、CMU 源 7，没有接入 APLIC/IMSIC。PL UART 是 460800 8N1，本次短自检通过 DDR/XSDB 回报。

复位修复：`proc_sys_reset` 的辅助输入为低有效，未使用时必须接 1。原 R8 接 0 导致一直保持复位。`fpga/inorder/create_board.tcl` 是修正后的源码入口；`fpga/inorder/r8_reset_eco.tcl` 对冻结 R8 checkpoint 的辅助同步器 D 脚作一处常量 ECO，只重连物理常量网络，保留原 CPU/VPU 布局。旧版 checkpoint/包保留，不应再用旧 bit 上板。

`software/ps-rpu/run_soc.tcl` 按数值读取 XSDB `mrd -value`，先停止 RPU 组再开放 PL，重新下载 ELF 后清除旧完成码，再启动并检查 phase/status。干净冷启动脚本也已实际 PASS，不能用旧 DDR 结果代替本次运行。

资源为 53,710 LUT、38,594 FF、16 BRAM36、35 DSP。CPU/VPU/system setup WNS 分别为 -0.323/+0.071/+0.107 ns，hold、bus-skew、bitstream DRC 和完整布线检查通过。CPU 300 MHz 尚未通过 setup 时序；短上板 PASS 不等于压力测试或 H/V 完整合规验收。GSIM 的四个板级启动用例和频率负控制通过，CoreMark 原始周期/退休数保持已冻结对比结果。

证据摘要与 bit/checkpoint 哈希在 `fpga/inorder/board-checkpoint-20261106.json`。本地交付目录为 `E:/VM/Share/Valence-rtl/Valence-InOrder/board-soc-cpu300-20261106-r8/bringup-debug-cpu300-resetfix`。后续 OpenSBI/kernel 准备与本次已验证硬件检查点分开记录。

以下保留早期接入记录；涉及“未上板”“misa.V=0”等状态均属于当时阶段。

## 已核对的板卡连接

用户提供的核心板原理图第 8、12–15 页：PS DDR4 为四颗 MT40A512M16LY-062E，合计 4GB、64bit；PL 侧另有独立 DDR，不用于本方案。核心板第 3 页和底板第 6、8 页：PHY1 为 RTL8211F-CG，PHY 地址 1，RGMII 经 PS MIO64–75，MDIO/MDC 经 MIO76/77，IO 为 1.8V。PHY1 的 25MHz 参考来自 AD9523 OUT12，复位接 PS_POR_B。用户已确认时钟配置烧录完成；本流程不重写 AD9523。

原始 PDF 仅读，提取文本、图片和源 SHA 在 Windows board-ps-rpu-20261105/。这不是在板读取寄存器或网络实测。

## 内存与启动契约

| 使用者 | 地址范围 | 用途 |
|---|---|---|
| RPU/PS DDR | 0x40000000–0x4fffffff | 预留 256MiB RV 程序、数据和共享区 |
| RISC-V CPU/VPU | 0x80000000–0x8fffffff | 同一 DDR 窗口的 RV 物理地址 |
| 原生 fabric AXI | 0x00000000–0x0fffffff | DDR 窗口 offset，32bit 地址、4bit ID |
| PS S_AXI_HP0_FPD | 0x0000000040000000–0x000000004fffffff | 49bit 地址、6bit ID、64bit 数据 |

4GB DDR 并不意味着 RPU 可用一个平坦的 32bit 地址空间访问全部容量。首版只使用低 2GB 内的上述窗口。RPU 链接脚本、堆栈、网络缓冲区和其他 PS 使用者必须将整段窗口留给 RV；暂不把完整 4GB 暴露给 RV。

```mermaid
flowchart LR
  ETH[PS GEM3 / RTL8211F] --> RPU[RPU 裸机 / lwIP]
  RPU --> DDR[PS DDR / 预留 256MiB]
  RV[CPU + VPU] --> F[总线 + CMU]
  F --> W[窗口地址接线]
  W --> HP[S_AXI_HP0_FPD / 64bit]
  HP --> DDR
  RPU --> GPIO[EMIO 启动电平]
  GPIO --> BOOT[同步 / 一次冷启动]
  BOOT --> RV
```

PS 硬 DDR 控制器承担 DDR4，不实例化 MIG；以太网使用 PS GEM3，不添加 PL MAC。PL 使用现成 I1SpinorPsFpga 汇合 H、原生 Spinor、fabric、CMU 和窗口，CPU/VPU 独立时钟不变。misa.H 为 1；原生 Spinor 路径可用，但 misa.V 仍为 0，尚不是完整 RVV 合规声明。专用 CPU monitor 未启用。

I1PsDdrWindow 不增加周期或 outstanding 槽。INCR burst、ID、WSTRB、LAST、响应错误和反压逐通道透传；窗口基址对齐，用高位拼接而非地址加法。PS 端配置专用 64bit HP0 口，ACLK 接始终运行的 systemClock，AxUSER 接 0（物理地址），可选 REGION 接 0。PS AFI 的复位必须与 common cold reset 属于同一事务 epoch。

## RPU 冷启动

| PS GPIO 编号 | EMIO | 方向 | PL 信号 |
|---:|---:|---|---|
| 78 | 0 | PS → PL | start |
| 79 | 1 | PS → PL | ddrReady |
| 80 | 2 | PL → PS | started |

在板卡 BSP/FSBL 初始化 PS DDR、GPIO、GEM3 和所需时钟后，调用 software/ps-rpu/i1_ps_loader.c 的 I1PsLoadAndStart。输入是链接到 RV 0x80000000 的 flat binary，暂存在预留窗口外。入口代码负责 RV 的栈、BSS 等运行环境。

加载器检查窗口长度及已有 started owner，先设置 GPIO 输出锁存器，再使能输出；复制 image 后调用 AMD Xil_DCacheFlushRange，并执行 DSB，再拉高 ddrReady/start。PL 双级同步两个持久电平，随后一次性释放整套 CPU/VPU/fabric 的冷复位。返回成功表示启动请求已发出，RPU 可读 GPIO80 确认 started；没有无限 busy poll。

HP 为非一致性接口。后续共享数据也需明确 cache flush/invalidate 和消息所有权；首版没有后台网络共享环或热重载。started 只由 board cold reset 清除；RPU GPIO 变低或 RPU 应用重启不会清除运行中的 AXI owner。重新装载需先设计并完成整套 drain/reset，包括 PS AFI，而不是只复位 CPU。

## Vivado 与软件接入文件

先使用板卡原厂 PS preset/现有工程，再 source fpga/inorder/board_ps_interfaces.tcl，调用 i1_configure_ps_interfaces <PS单元名>。该片段只配置 HP0、三路 EMIO 和与原理图一致的 GEM3/MDIO；不猜测或覆盖 DDR 延迟、训练、PS PLL 和启动介质设置。

本次已获得：

- PS DDR 适配器 GSIM：20,000 轮五通道随机数据/反压，窗口首尾、全部属性/ID/错误响应、两种 GPIO 启动顺序、启动保持、异步冷复位以及独立地址负例通过。
- 导出真实 H/V+总线+CMU 的 I1SpinorPsFpga SystemVerilog 成功。尚无板卡 PS BD/XSA 和连通后的实现结果。
- RPU 加载器通过 Cortex-R5 freestanding 编译，产生 ARM 对象。真实 API 来自 AMD gpiops_v3_14/standalone_v9_4。SDK 自带 R5 示例的生成头文件只用于声明/类型检查，未链接其运行库；这不是本板 BSP 链接或可直接烧录的 ELF。
- PS 参数由本地 Vivado 2025.2 实例验证，结果保存在 ps-interface-contract.txt；配置查询也使用 8 线程。

网络传输层后续接现成 lwIP/emacps，使用 GEM3/PHY1；目前没有声称收包、程序下载或板级启动已经实测。现有 PPA 是 PL CPU/VPU/fabric/CMU 测试上下文，不包含新增 PS board BD 或网络软件。

CPU/VPU 的 300MHz 仍是优化目标。R5 完整集成 routed setup 为 -0.622/-0.003ns，system +0.069ns；约 253MHz 是按 CPU slack 估算值，不是板级验证频率。R6 针对 Icache → H 返回 → C 长度 → PC 和 VPU completion → vtype CE 作结构批次，保持原时钟约束和 IPC 基准。

## PS/PL 引脚与 BD 连接核对完成

实际 I1SpinorPsFpga 导出 RTL 已经由 I1PsPlBoundary.v 纯连线顶层接到 PS HP0，Vivado 对接口推断和连接检查通过。AXI 为 49bit 地址、64bit 数据、6bit ID，ARUSER/AWUSER 为 1bit 常量 0。PS GPIO_0 与 PL PS_GPIO 整体相连，参数传播后双方真实 HDL 宽度均为 3bit；interface_nets 在保存的 BD 中再次独立核对。CPU/VPU 时钟独立，systemClock 同时连接 PL fabric 和 PS HP0 ACLK。证据 ps-pl-integration-receipt.json 和 ps-pl-pin-contract.bd。

board_ps_interfaces.tcl 的 i1_attach_ps_pl 过程接受已有时钟/冷复位 BD 对象并完成上述连接。Vivado 模块引用的最外层使用纯 Verilog .v，内部保留 Chisel SystemVerilog；工程 source_mgmt_mode 需为 All。PS 配置同时指定 GPIO configurator count 和 HDL count，避免传播回默认宽度。PS GPIO 的 T 是引脚三态控制，内部持久电平连接不使用它。

该 BD 是接口契约 fixture，当前连入冻结 R5 加 PS 适配器的导出；不能作为未经配置的本板 DDR 工程使用。板级实现下一步在现有 PS DDR/启动工程或 XSA 的基础上复用此过程，并链接对应 RPU BSP；已烧录的 AD9523 时钟配置保持使用。
