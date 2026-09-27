# UART 控制台合同与旧实现复用审计

旧 `soc.device.UartTx` 只有 TileLink 到仿真字节脉冲的转换；DLL/DLM 不驱动波特率，THRE/TEMT 常高，
FCR 报告 FIFO 模式却没有 FIFO，接收单寄存器会覆盖未读数据，未检查访问宽度和 byte mask。
保留该历史模块，不把旧测试作为正确性依据；复用其 0..7 寄存器地址布局与 DLAB 软件约定。

参考 TI PC16550D SNLS378C（2015-05）寄存器图：
https://www.mouser.com/datasheet/2/405/pc16550d-443503.pdf 。
新 `soc.ip.uart.UartConsole` 是**非 FIFO、固定8N1的16550寄存器子集**，不是完整16550实现。
提供 RBR/THR、IER(接收/发送/线路错误)、IIR、LCR、LSR、SCR、DLL/DLM；MCR只保存低4位，
MSR返回0，不支持modem/loopback。FIFO不使能，IIR高两位为0；FCR可清接收/发送holding寄存器。
LCR允许0x03、0x80、0x83；0x80用于8250软件先开启DLAB再设置8N1，其余格式返回总线错误；复位LCR=3、divisor=1。

## 端口与时序目标（实现前合同）

- CPU无关 RegisterPort，8个逐字节寄存器，平台地址0x10000000；只接受size0、byteEnable1，错误访问无副作用。
- 两项寄存响应缓冲（ready来自寄存的队列容量，不组合依赖response.ready），正常寄存访问一拍响应、可连续每拍接受一项；响应阻塞时稳定保存数据，无重复读清/发送。
- 发送holding寄存器1字节，另有10位移位器；THRE反映holding空，TEMT反映两者均空。
  holding满时THR写背压，软件可轮询THRE。发送中不允许改DLL/DLM，避免截断当前字符。
- 串行8N1，LSB先行，每bit为16*divisor个核心周期；不生成派生时钟，计数器使能移位器。
- RX双寄存器同步、起始位中点确认和数据位中点采样；一字节holding，溢出保留旧字节并置OE。
  RBR读取与新字节同拍时保留新字节；LSR读清错误，新错误优先。支持帧错误，未实现break/parity检测。
- 中断优先级：线路错误 > 接收有效 > THRE；读IIR仅清当前被识别的THRE中断。
- UART接APLIC source3（高电平模式）；平台sources位2与UART中断做OR，板级必须把该外部输入置0。原无UART启动测试可在该位注入外部源。
- 顺序标签路由器复用现有8项容量；RAM请求组合直通，不新增串行等待状态。验证RAM路径性能回归。

本阶段是FPGA启动控制台基线，单字节缓冲限制软件服务延迟；后续吞吐优化需FIFO/接收超时及更广格式支持。
双寄存器只能建立CDC结构，实际亚稳态约束、ASYNCH_REG标记、引脚、电气与Vivado时序仍待板级集成验证。

## 验证与使用

`make gsim-uart-test`：独立串行驱动按8N1线协议发送/解码，不使用DUT寄存器定义。
覆盖非法地址/宽度/掩码无副作用、响应保持、随机SCR、发送满背压、DLAB、THRE/TEMT、
IIR优先级及清除、接收溢出保留旧字节、帧错误、短毛刺起始位、多分频及divisor=0按1处理。
连续384拍RBR读与串行接收重叠，验证每拍接受一项以及读清与字节到达同拍不丢数据。
当前结果：1,090次普通事务、384次连续读、43个发送字符，25,036周期；串行负向注入通过。

`make gsim-machine-platform-test`：每种核心容量分别执行UART固件和原RAM固件。
UART固件软件设置divisor=1、LCR=3、IER=1，串行TX发出 `OK\n`；测试从外部RX线发送 `Z`，
APLIC source3配置为高电平，M处理程序读IIR/RBR后把字符写到RAM偏移16。必须得到字符0x5a、
计算结果376、中断计数1；独立指令提交模型核对软件状态，独立线解码器核对TX，增加TX负向注入。
这不是完整Linux串口驱动兼容认证；只验证明确支持的初始化与8N1控制台用法。

原RAM固件同时保留作性能对照：ROB8/PRF36三组周期3,564/4,141/4,115，
ROB32/PRF64为3,606/4,205/4,217，与未接UART之前逐项相同。
UART寄存器请求链通过两项队列的寄存容量隔离，普通访问验证II=1；串行发送本身依照波特率运行。
新平台增加地址比较和响应选择，不以周期不变推导Fmax不变；实际路径和面积尚须Vivado测量。

UART固件定向结果（包含RAM初始化、串行等待及中断处理，不等价于计算IPC）：

| 配置 | 三组提交合计 | seed0 / seed17 / seed8191 周期 | 同步异常 / 外部中断 |
| --- | ---: | --- | ---: |
| ROB8 / PRF36 | 5,938 | 3,973 / 4,560 / 4,539 | 9 / 3 |
| ROB32 / PRF64 | 6,029 | 4,005 / 4,624 / 4,602 | 9 / 3 |

生产RTL仍由 `make machine-platform-rtl` 生成，清单 `build/ip/machine-platform/filelist.f`，
默认ROM初始化文件为含UART的固件。UART闲置时RX应保持高电平；核心时钟频率决定实际波特率，
baud=fclk/(16*divisor)，不是仿真周期的墙钟时间。

最终验收：28项Scala检查、全量GSIM/NEMU及负向注入全部通过；44条原整数IPC记录逐项不变。
日志 `build/gsim/uart-final.log`，IPC对照 `build/gsim/ipc-before-uart.json`。
