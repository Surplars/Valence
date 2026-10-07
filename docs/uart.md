# UART 控制台合同与验证

当前源码（2026-10-01）使用升级后的 soc.ip.uart.UartConsole：
16550A 风格的 8 个逐字节寄存器、16 字节 RX/TX FIFO、16x 接收多数采样、
接收超时、逐字符 PE/FE/BI 错误记录及可编程字符格式。
不是完整芯片级 ns16550a 合规认证：板外没有 RTS/CTS/DTR/DSR/RI/DCD 引脚，
没有自动硬件流控；OUT2 不门控 SoC IRQ，外部 modem 状态恒零，内部 loopback 可测试状态。

MMIO 为 0x10000000–0x10000007，reg-shift=0、io-width=1，
仅接受 size=0 / byteEnable=1；IRQ 为 APLIC source 3，高电平模式。
非法地址/宽度/掩码返回总线错误且无副作用；完整位表见 [寄存器附录](soc-registers.md#uart0x10000000)。

## 时钟、波特率和两个板级配置

当前 VL100 管理时钟配置：CPU 为 100 MHz，UART 在独立的 50 MHz raw 域，
16550 虚拟参考为 **7,372,800 Hz**，DLL/DLM=1/0 才是 **460800 baud**。
CPU 频率、UART raw 时钟、baud-generator 参考不能混用。
r5 ROM 的 DLL=7 勘误实际约 65828.57 baud；r6 修复与机器码校验记录见
[时序台账](fpga-timing-windows.md#当前批次2026-10-06-r6uart-修复取指发射访存裕量)。
本节下方 DDR45/DDR50 表格是历史单域配置，不是当前 VL100 的物理时钟结构。

只有一个物理核心时钟。referenceClockHz 通过相位累加器生成时钟使能，不创建额外时钟域：
baud = referenceClockHz / (16 * max(DLL_DLM, 1))。
所有 divisor 使用同一公式，不再只有 DLL=1 特殊而其他 divisor 使用核心频率。

| 配置 | 物理 CPU 时钟 / timebase | UART 参考频率 | DLL/DLM | 主机 |
| --- | ---: | ---: | --- | --- |
| DDR45 / UART1500000 | 45000000 Hz | 24000000 Hz | 1 / 0 | 1500000、8N1、无流控 |
| DDR50 / UART115200 | 50000000 Hz | 1843200 Hz | 1 / 0 | 115200、8N1、无流控 |

两个频率为精确的平均速率，不依赖四舍五入的整数分频。
板级 UART 软件或设备树 clock-frequency 应填写上表 UART 参考频率，
而 timebase-frequency 应填写 CPU 频率；二者不能混用。
BoardSocMain 和 BoardSocGsimMain 最后一个可选参数是 uart-baud，默认 1500000。
通用 UartConsole 默认参考核心时钟；保留 fastDivisorOne=true 的旧构造参数，
但现在它选择统一的 24 MHz 虚拟参考频率，不再表示 DLL=1 特例。

旧 bit 不会因更新 Scala 或 GUI 时钟而改变。已有 DDR50 1.5 Mbaud / 无 FIFO bit
与本次新 DDR50 115200 / FIFO 候选不同，必须明确选对 bit 和主机参数。
时序/bit 发布状态见 [Windows 时序记录](fpga-timing-windows.md)，未签核候选不能用于交付。

## 容量、延迟、背压与寄存器语义

- RX/TX 各 16 字节 FIFO；硬件复位禁用 FIFO，禁用时容量为一字节。
  BootROM 使用 FCR=0x07：bit0 使能、bit1/2 清 RX/TX；0x06 会禁用 FIFO。
  FIFO 模式切换清空两个队列；清 TX 不截断正在移位发送的字符。
- RX 触发阈值为 1/4/8/14（FCR[7:6]）。FIFO 未空且四个字符时间没有
  接收或 RBR 读取时产生接收超时中断；收到字符或读 RBR 会重新计时。
- IIR 原因：线路错误 0x6 > 接收阈值 0x4 > 超时 0xc > THRE 0x2 > modem 0x0；
  无中断为 0x1。FIFO 启用时 IIR[7:6]=11，所以实际可读到 0xc6/0xc4/0xcc/0xc2 等。
  读 IIR 仅确认当前 THRE 中断，不确认 RX/线路错误/modem。
- LSR DR 表示 RX 非空，THRE 表示 TX FIFO 空（不是“尚有空间”），TEMT 表示
  FIFO 与移位器都空。THR 满时写背压；接受写清 THRE pending。
  FIFO 最后一字节进入移位器、清 TX 或打开空 FIFO 的 THRE 使能时置 pending。
- RX 满且同拍不读 RBR 时置 OE、保留已排队字节、丢弃新字节。
  同拍 RBR pop / RX push 不丢新字节。PE/FE/BI 与每个接收字节关联；
  LSR 读清 OE 与当前队头错误，后续字节错误不会被提前清除。
  FIFO-error bit7 汇总队列内尚未确认的字符错误，不包含单独 OE。
- LCR 支持 5/6/7/8 位、无/奇/偶/mark/space parity、1/2 stop（5 位时 1.5 stop）、
  break 和 DLAB。RX 检查第一停止位，多数采样在每 bit 的中间三个 16x 采样点。
  持续 break 只发布一个错误字符，待线路回高再重新接收。
- MCR 低 5 位保存，loopback 将内部 TX 接到 RX，外部 TX 保持空闲高；
  loopback modem 映射和 MSR delta/read-clear 可用。无板外 modem/自动流控。
- MMIO 两项非直通响应缓冲，正常访问一拍响应、连续 II=1；
  响应阻塞时稳定保持数据，不重复读清或发送。
  写 DLL/DLM 忙时背压；更改波特率/格式前应等 TEMT 并确保 RX 空闲。

16 字节在 1.5 Mbaud / 8N1 下提供约 106.7 µs 的短时接收容量，
在 115200 下约 1.389 ms；FIFO 不保证持续处理吞吐，也不能修复物理位错误。
两级 rxMeta/rxSync 标记 ASYNC_REG；不能将级间路径剪掉。

## 必要功能验证（不是实体板验收）

make gsim-uart-test / python3 simulator/gsim/run.py uart 运行两组独立线协议测试，
不引用 DUT 寄存器或格式表来生成预期结果：

- 基础 MMIO、响应保持、连续每拍读 RBR、随机 SCR、TX 背压、所有 divisor/零值策略；
  FIFO 阈值、满溢保序、四字符超时、LSR 错误关联与读清、break、RX 字长/校验位。
  PASS：1339 事务、83 发送字符、73885 周期。
- 40 组独立 TX 线格式（5–8 位、五种 parity、两种 stop 配置）；
  modem 状态、MSR delta/read-clear、内部 loopback 和 break。
  PASS。两组刻意错误预期注入均被拒绝，ASan/UBSan 开启。
- mill -i IonSoC.test.testOnly ip.UartParamsSpec：2 项通过，包括参考频率范围和两个目标配置。
- 45 MHz / 1.5 Mbaud 和 50 MHz / 115200 连续 8N1 BootROM 下载均通过：
  头/分块/整镜像 CRC、重传、范围和未校验跳转拒绝、DDR 执行/返回、重写指令 fence.i。
  分别 5677739 / 18387432 cycles，936 UART bytes；
  同为 1098 read bursts / 554 write bursts。周期包含串口等待，不是计算 IPC。
- 12 项主机协议测试及 uart_probe.py --self-test 通过，没有打开串口。

上述 GSIM 不模拟真实 MIG PHY、USB-UART、电气或亚稳态。
用户此前在 50 MHz 无 FIFO版仍遇到 invalid header，故障原因尚未单独证明；
新 FIFO 与多数采样是容错改进，不宣称已经解决实体板故障。
不运行全量 GSIM，保留旧 CPU 和 bit，板上须重复下载 CRC/DDR 压力验证。

## 参考与历史边界

参考 [TI TL16C550D 数据手册](https://www.ti.com/lit/ds/symlink/tl16c550d.pdf) 的寄存器/FIFO语义。
旧 soc.device.UartTx 只是仿真字节脉冲设备，不能作为当前硬件正确性模型。
此前非 FIFO 8N1 子集、旧 4 KiB 平台/默认核心频率的记录是历史验证，
不代表当前 DDR45/DDR50 的软件时钟合同或实体板稳定性证明。
