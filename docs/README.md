# 开发文档

当前工作是独立新乱序核，GSIM 是唯一受支持的仿真后端。

- [目录与依赖边界](layout.md)：源码、验证、历史资料和生成文件的位置。
- [OoO Core 设计与验收规划](ooo-core-plan.md)：产品线、接口、不变量和实现阶段。
- [机器核 CSR 与同步陷阱](machine-core.md)：队首授权、异常处理程序、MRET 和 IMSIC CSR 桥接。
- [OpenSBI v1.9 启动验证](opensbi-bringup.md)：GSIM 中的固件、设备树、S 态交接与当前边界。
- [Linux 启动实验](linux-bringup.md)：本地内核源码、64 MiB GSIM 平台、启动验证与用户态里程碑。
- [PMP 物理内存保护](pmp.md)：机器平台的16条目权限检查、CSR、MPRV与GSIM验证边界。
- [模块化 SoC / AIA IP](modular-soc.md)：IMSIC、可替换 PLIC 路线、CSR 提交边界和独立总线接口。
- [TileLink 内存桥](tilelink-memory-bridge.md)：新核数据口的并发读、source 重排和集成限制。
- [TileLink 双 RAM 路由](tilelink-router.md)：两窗口分流、source 归属、乱序 D 仲裁与片上验证。
- [双主 TileLink 仲裁](tilelink-arbiter.md)：两主 source 隔离、轮转仲裁与乱序 D 返回。
- [TileLink 取指路径](tilelink-fetch.md)：双主 ROM/RAM 互联、取指拼包及整机性能对照。
- [AXI4 外部内存桥](axi4-memory-bridge.md)：独立边界实验及 Zynq-7000 AXI3 的转换要求。
- [TileLink→AXI4 内存边界](tilelink-axi4-bridge.md)：独立 TL-UL/AXI4 适配与验证范围。
- [RVA23 架构目标与差距](rva23.md)：必选能力、实现顺序及合规边界。
- [RV64B 执行合同](rv64b.md)：Zba/Zbb/Zbs、组合路径、依赖与差分验证。
- [RV64C 与 CoreMark](rv64c-coremark.md)：混合长度取指、GSIM 工作负载与性能口径。
- [RV64M 执行合同](rv64m.md)：多周期乘除、完成仲裁、取消和吞吐基线。
- [裸核接口与 IPC](bare-core-ipc.md)：LSU 基线、验证范围、测量口径及结果。
- [公共 ISA 与复用边界](isa-reuse.md)：共享标准编码、新旧核心控制适配和验证范围。
- [GSIM 验证说明](../simulator/gsim/README.md)：依赖、运行命令、支持范围与回归结果。
- [历史资料索引](../legacy/README.md)：旧 SoC、流水线、固件和故障记录；其中旧仿真命令已退役。

- [APLIC MSI IP](aplic.md)：外设中断线、发送队列与机器核组合边界。

- [CPU 数据口到 APLIC 映射](core-mmio.md)：并发路由、响应保序及程序初始化中断验收。

- [FENCE、共享 RAM 与 DMA](dma.md)：四项在途拷贝 IP、CPU/DMA 公平仲裁、source4 完成中断及 SMT 边界。

- [机器定时器](machine-timer.md)：独立mtime/mtimecmp、同步时基、MTIP及精确中断优先级。
- [S 定时中断与 Sstc](sstc.md)：`stimecmp`、时间源、STCE/TM 门控及 STI 精确入口。

- [原子共享内存IP](atomic-memory.md)：W/D LR/SC、AMO、队首授权与DMA排他；机器平台已接入。
- [当前性能与证据边界](performance-status.md)：裸核IPC、同步平台及FPGA频率的测量范围。

- [可选共享读缓存](shared-read-cache.md)：扇区填充、DMA写失效及开关对照；阻塞基线默认关闭。
