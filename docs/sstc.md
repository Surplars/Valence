# S 定时中断与 Sstc 基线

状态核对：2026-09-30。板级时间源与可用 CSR 总表见
[OS/软件移植合同](os-software-porting.md)，MMIO 见[寄存器手册](soc-registers.md)。

依据 [RISC-V Sstc 1.0](https://docs.riscv.org/reference/isa/v20250508/priv/sstc.html)。
本阶段为单 hart RV64 实现，不含 H/VS 定时器，也不构成完整 RVA23 合规声明。

平台沿用 `MachineTimer` 的同步 64 位 `mtime`；新增只读时间输出，经机器核封装送入
`MachineSystemUnit`。独立机器核的集成方须提供同一时钟域、与平台时间一致的 64 位时间值。
`time` CSR（0xC01）读取该值。`stimecmp`（0x14D）复位为全 1；M 态始终可读写，
S 态须同时具备 `menvcfg.STCE` 与 `mcounteren.TM`，U 态不能访问。
`time` 在 S 态受 `mcounteren.TM` 控制，在 U 态还受 `scounteren.TM` 控制。
三个使能位复位为 0；未实现的计数器位读零。

STCE=1 时，64 位无符号 `time >= stimecmp` 生成 STIP。比较结果先寄存一拍，
再进入中断仲裁，避免把宽比较器直接串入 ROB 排空控制路径；规范允许待处理状态延后变化。
此时 `mip.STIP` 和 `sip.STIP` 均只读，处理程序将 `stimecmp` 推到未来以清除中断。
STCE=0 时，M 软件可写 `mip.STIP`，`sip.STIP` 仍只读。
`mideleg[5]` 控制 S/M 目标，`mie/sie[5]` 共用使能位；S 态需 SIE，U 态无需 SIE。
在现有中断集合中，MEI、MTI、SEI、SSI、STI 依次优先。精确陷阱、访存排空与返回沿用
既有单个 ROB 队首系统事务槽；没有新增系统端口或提交周期预算。

64 位比较器、时间扇出和新增 CSR 译码的 FPGA Fmax/面积尚未实测。
MachinePlatform 的定时器依赖同步 `timerTick`；当前 BoardSocTop 将其固定为 true，每个 40 MHz
SoC 时钟递增一次，因此板级 `timebase-frequency=40000000`。它不是独立 RTC，不跨时钟域。
`time`（0xC01）可用，但 `cycle/instret` 及相应机器计数 CSR 不存在。其他 GSIM 配置可能使用不同 tick。
定向测试覆盖 S/U 态 STCE/TM 访问门控、时间到期、SIE 屏蔽、Direct/Vectored 入口、
`stimecmp` 清除和 STCE=0 的软件 STIP 回退。平台固件 `machine-sstc.S` 在
`make gsim-sstc-platform-test` 下使用真实同步 `mtime`：第 5 次 tick 触发一次 STI，
S 处理程序读取 `time` CSR 为 5、把比较值改为 100，再验证 STIP 下降并 SRET 返回。
两种调度种子和两组机器平台参数均通过，原 RAM 启动镜像也以相同模型复查。
上述历史专测证明 Sstc 逻辑；当前板级 RTOS/OS 定时中断和新内存配置的物理时序仍需单独验收，
启动周期不是 IPC 或 Fmax 结果。
