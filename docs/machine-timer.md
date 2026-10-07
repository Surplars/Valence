# 机器定时器合同

当前板级口径（2026-09-30）：BoardSocTop 的 timerTick 恒为1，核心时钟目标40 MHz，
因此软件 timebase 为40,000,000 Hz。仅 `mtimecmp=0x02004000` 与 `mtime=0x0200bff8`
及其 +4 的32位高半别名有效；整个64 KiB译码窗口不代表完整CLINT/ACLINT，尤其无MSIP寄存器。
访问掩码、复位值、别名与Sstc CSR见 [MMIO 寄存器表](soc-registers.md#machine-timer0x02000000-窗口)，
平台配置见 [SoC datasheet](soc-datasheet.md)。

独立单hart定时器与MTIP集成最初按以下合同实现；随后已加入 `time` CSR 与
[Sstc 基线](sstc.md)。本页保留2026-09-22初版验收，不宣称完整ACLINT/CLINT、Zicntr或RVA23合规。
依据项目已引用的特权ISA 1.13：
https://docs.riscv.org/reference/isa/v20250508/priv/machine.html

## 实现前协议与性能约束

独立RegisterPort IP，无CPU类型依赖。默认mtimecmp=0x02004000，mtime=0x0200bff8，两个64位寄存器。
支持自然对齐64位整体和32位高/低半访问，要求size/strobe匹配；其他地址/宽度/掩码返回error且无副作用。
mtime复位0，mtimecmp复位全1；每个同步tick使mtime加1，溢出回绕；mtime写优先于同拍tick。
读返回请求握手前快照，不因响应背压变化；写在请求握手时生效，不重复执行。
寄存器两项响应FIFO，请求接受后下一拍可见，可持续每拍接受/返回一项；满队列恢复允许一拍气泡。
中断由64位无符号mtime>=mtimecmp比较后寄存，一拍更新，符合规范允许MTIP延迟变化的要求。
比较器不直接贯穿CPU的陷阱组合路径；64位加法/比较、MMIO译码的实际Fmax和资源仍待Vivado测量。

tick必须来自核心时钟域内的固定频率脉冲，独立于提交使能、CPU暂停及访存背压。
通用MachinePlatform暴露timerTick输入；BoardSocTop已按上述40 MHz时基固定连接，异步RTC不能直接连接。
当前未接板级RTC/CDC，已实现time CSR与CSR形式的SSIP，但没有MSIP MMIO或多hart compare阵列。

## 核心与平台集成

机器核新增timerInterrupt输入，mie.MTIE和只读mip.MTIP位7；MTIP独立于MTIE与全局MIE可读。
可同时处理MEI与MTI，MEI优先；mcause分别为interrupt|11、interrupt|7。
mtvec向量入口计算BASE+4*cause，不能固定为外部中断的44字节偏移。
沿用ROB精确中断边界：先排空已发起访存/不可撤销系统操作，同步异常优先，保存下一条未退休PC。
mtimecmp写在MMIO队首授权后发出；新MMIO窗口不能成为投机RAM或写缓冲区域。
定时中断直接进入CPU，不经APLIC/IMSIC；原外部中断与DMA路由保持其语义。

## 验证要求

独立每拍软件模型验证计数、溢出、32/64位访问、写/tick冲突、非法访问、背压快照、持续吞吐和比较边界。
核心验证MTIE/MIE屏蔽、mip只读、定时/外部中断优先级、Direct/Vectored、MRET、访存排空与退休背压。
平台固件用CPU配置定时器、接收两次定时中断并重装compare，返回后检查计数，软件模型不从DUT读取预期值。
原UART/RAM/DMA固件和44条裸核IPC作为对照。全流程仅GSIM，MMIO定时模型独立于NEMU已有整数差分。

## 2026-09-22 验收

`make gsim-timer-test`：13,587项请求、6,491拍响应背压、连续486拍每拍接收一项，446次IRQ边沿，
逐拍独立模型及负向响应注入通过。
机器核两种配置及WiredMachineCore各增加18个定时相关程序，包含18次MTI、3次MEI和3次同步异常；
验证MTIE/MIE、U态抢占、只读MTIP、MEI优先、同步异常优先、向量偏移28、空ROB和80拍延迟访存排空。
原34个机器核程序继续通过，新增用例使用独立中断模型，不将未启用的NEMU设备功能当成参考。

| 定时固件配置 | seed0周期 | seed17周期 | seed8191周期 | 三次总提交 |
| --- | ---: | ---: | ---: | ---: |
| ROB8 / PRF36 | 4,348 | 4,911 | 4,899 | 7,421 |
| ROB32 / PRF64 | 4,339 | 4,939 | 4,930 | 7,491 |

每次启动包含3次预期MMIO异常、2次MTI，读回中断计数2及C结果376。
周期不含ROM装载/复位，包含RAM初始化、C工作、定时等待和处理程序，不能当作纯计算IPC。
平台模型按软件提交维护compare状态；动态mtime快照、精确比较更新与tick/写碰撞在独立IP层逐拍验证。

`make test`通过30项Scala和全部GSIM/NEMU/负向注入。原44条裸核IPC记录、18组UART/RAM/DMA启动周期逐项一致，
仅IPC报告模型源码哈希更新。新增timerTick、MTIP和MMIO路由未造成已测基准周期退步，不代表Fmax已验证。
日志 `build/gsim/timer-final.log`，对照 `build/gsim/ipc-before-timer.json`。
`make timer-rtl machine-platform-rtl`成功；清单为 `build/ip/timer/filelist.f` 和 `build/ip/machine-platform/filelist.f`，
导出日志 `build/gsim/timer-rtl-export.log`。生产平台有timerTick输入，不含仿真ROM编程口。

上述记录只覆盖初版M定时器；后续原子访存、特权态、缓存和MMU的当前集成状态以
[SoC datasheet](soc-datasheet.md)为准，S定时器另见[Sstc](sstc.md)。
