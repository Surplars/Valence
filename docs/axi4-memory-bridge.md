# AXI4 外部内存桥基线

`OrderedAxi4Bridge` 把新核的有序 `DataPort` 转为 64 位、单拍 AXI4 内存事务。
它是外部内存边界的独立验证路径，不代表新 SoC 已从 TileLink 改用 AXI 内部互联；
新机器平台已有可选 TileLink→同步 RAM 通路，默认仍直连 RAM；
AXI4 桥尚未接入这两条路径。总线拓扑见[模块化 SoC 合同](modular-soc.md)。
Zynq-7000 的 PS HP 端口是 AXI3，该 AXI4 桥不能不经协议转换就直接接 HP；
项目只实现 AXI4，所需 AXI4→AXI3 转换留给 Vivado 集成 IP；
7 系列 MIG 则可选 AXI4 从端口，详见[AMD PS–PL 接口](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/PS-PL-AXI-Interfaces)
与[MIG AXI4 接口](https://docs.amd.com/r/en-US/ug586_7Series_MIS/AXI4-Slave-Interface-Block)。
AXI4 通道类型独立放在 `soc.ip.axi`；旧 `soc.bus.AXI4Master` 含 AXI3 的 WID，
不作为此路径的协议定义。信号宽度、AXI4 的 WID 缺席和同 ID 读响应顺序按
[Arm AMBA AXI and ACE Protocol Specification IHI 0022H](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)
核对。

## 本轮合同

- 每个请求生成一拍 INCR 事务（AxLEN=0，AxSIZE 来自访问宽度），使用固定 ID 0。
  数据口必须提供自然对齐的地址、精确字节 mask 和普通非原子事务；桥在握手时断言这些前提。
- 最多 8 笔同 ID 读在途；AR 每拍至多接受一笔，R 每拍至多返回一笔。
  RRESP 的 SLVERR/DECERR 转成数据口 `error`；检查 RID=0、RLAST=1。
- 默认最多 4 笔写在途。已接受的写请求按序保存在环形缓冲中，AW 和 W
  各有独立发送指针，允许不同写的两个通道并行推进；同 ID 的 B 按序确认。
  读写方向切换时等旧事务响应全部被接收，保持 `DataPort` 跨读写的请求顺序。
- 写入目标必须保证成功：现有普通 RAM store buffer 允许写在物理响应前退休，
  不能把可能有副作用的 AXI 写错误伪装成精确 `DataPort` 错误。BRESP 出错时断言失败，
  该桥当前不能接任意会返回写错误的地址空间。
- AW/AR 的 LOCK/CACHE/PROT/QOS 默认零；无 burst、多个 ID、AXI 排他事务、
  缓存一致性或跨时钟域支持。原子操作必须在独立的原子边界完成且满足外部代理的互斥条件。

请求到响应的延迟由下游决定；桥自身的读请求直通 AR，读取吞吐目标为每拍一笔，
写路径默认 4 项且可配置。ARREADY 到内部 `request.ready`、RREADY 到上游响应背压
是组合路径；写 AW/W 由寄存请求驱动。写队列和选择网络会增加资源与关键路径压力，
FPGA 面积和 Fmax 尚无 Vivado 数据。

`make gsim-axi-bridge-test` 使用独立字节内存模型，验证 105 笔混合事务、
96 次读、9 次写、5 次读错误；读峰值 8 笔、写峰值 4 笔在途。
AW/W 独立接收、AR/AW/W 背压期间载荷稳定、方向排空和故意篡改读数据的负向检查均通过。
另有 BRESP 错误注入，确认写成功承诺违反时断言。
日志为 `build/gsim/axi-bridge-focused.log`。
`make axi-bridge-rtl` 导出 `build/ip/axi-bridge/OrderedAxi4Bridge.sv` 和 `filelist.f`。
`make axi-bridge32-rtl` 另导出 32 位地址端口版本；高 32 位输入地址在请求握手时
由硬件断言为零，不能静默截断。两个版本都尚未做 Vivado 综合。

目前是可独立验证和导出的桥，不是已连接 DDR 的机器平台。下一步需定义可信的外部
RAM 窗口、DMA/原子可见性、总线地址映射与时钟域，并在真实平台集成后重跑固件/IPC
及 Vivado 时序。若新平台采用 TileLink 内部互联，此独立直连桥需放在旁路配置，
独立的 [TileLink→AXI4 适配](tilelink-axi4-bridge.md)现已验证；
正式平台仍须完成地址映射、DDR/FPGA 接入及 DMA/原子顺序验收。
独立桥的 4 笔写在途及其微基准见[TileLink→AXI4 边界](tilelink-axi4-bridge.md)；
读写并行和更多 ID 的收益与顺序代价仍待评估。
