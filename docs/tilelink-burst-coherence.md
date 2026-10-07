# TileLink burst 与一致性推进边界

产品目标要求 64 字节缓存行传输与 TL-C 一致性；机器平台现有可选的单 CPU 写回路径，
已覆盖脏行、DMA 探测和主动逐出。独立 home 已支持多个私有 T owner 客户端，
但尚未接成多 hart SoC，也未覆盖完整 TL-C 权限协议。
依据 [TileLink 1.8.1 规范](https://sifive.cdn.prismic.io/sifive/7bef6f5c-ed3a-4712-866a-1a2e0c6b7b13_tilelink_spec_1.8.1.pdf)：
带数据的多拍消息在同一通道内不能与其他消息交错；A、D 的 beat 数分别由 opcode、size
和物理数据宽度确定。TL-C 还需 B/C/E 通道的探测、写回与 GrantAck，不能只暴露引脚。

## 已完成的传输层

`TwoMasterTileLinkArbiter` 对多拍 Put 的 A 通道锁定获选主端口，直到最后一个 beat；
对多拍 AccessAckData/GrantData 的 D 通道保留 source 所有权，直到最后一个 beat。
`TwoBankTileLinkRouter` 同样锁住 A 的目标窗口和 D 的返回窗口，未映射的多拍 Get
返回完整的 denied/corrupt D 消息。单拍流量仍按原轮转仲裁运行。

`make gsim-tilelink-crossbar-test` 现包含 64 字节 PutFullData 两主同窗口竞争、
两个窗口同时返回 64 字节 Get、A/D 背压以及未映射 64 字节 Get 的独立用例。
`make gsim-tilelink-arbiter-test gsim-tilelink-router-test` 保留单拍乱序返回和负向注入；
双主单 RAM/双 RAM 固件已重跑，RAM、DMA、原子及 FENCE.I 后 RAM 执行周期保持不变。
单 RAM `TileLinkDataRamAdapter` 现另有独立的 16/32/64 字节 Get/PutFullData/PutPartialData
burst 路径：先排空原单拍元数据队列，再将每个 64 位 beat 送入同步 RAM；
当前读 burst 返回期间可预接收一笔后续整行 Get，并在最后一个 D beat 后
直接启动排队读取；写 burst 和单拍请求仍按原顺序等待。
正常单拍请求仍走原 8 项元数据快路径。整笔写在所有 RAM 响应完成后才回一个
AccessAck；读返回对应数量的 AccessAckData。越界/未对齐请求预先拒绝，
读返回完整 denied/corrupt burst，写不产生部分副作用。
合法部分写逐 beat 转发真实 mask（允许零 mask），不再强制写满 8 字节。
访问未通过范围/对齐预检查时仍不产生写副作用；实际写响应报错则排空所有已发请求，
最终 AccessAck 标记 denied，已成功写入的字节不回滚。当前读 burst 依赖配置内 RAM
预检查通过后必成功；意外读错误仍触发断言，不能把它宣称成任意错误 slave 的通用 manager。
`make gsim-tilelink-burst-ram-test` 验证单 RAM 和双 RAM 窗口的 64 字节写后读、
单拍回退、越界写/读和数据保持。两个机器平台拓扑均已启用该 manager 配置，
原 RAM/DMA/原子固件的单拍完成周期逐项不变。
默认 CPU、DMA 和共享缓存仍发单拍请求；下述可选 CPU 私有缓存缺失时会发 64 字节请求。

独立的 `TileLinkLineFillEngine` 已提供 4 槽 64 字节 Get 主端：接收每周期至多一条
带 tag 的行请求，按接收顺序发出 A，将 D 按 source 重组为完整的 8 个 64 位字，
保存 denied/corrupt，并在结果端回压时保持 tag、数据与错误。
`make gsim-tilelink-line-fill-test` 使用独立 D 端驱动验证 4 笔在途、跨 source 乱序完成、
错误和槽位复用；同一目标还把它连到 burst RAM manager 与真实同步 RAM，
验证整行读、越界 denied 和结果回压。`make tilelink-line-fill-rtl` 可导出独立 IP RTL。
单 RAM manager 的 D beat 仍串行返回；4 槽表示请求端并发能力，
不表示单 RAM 可同时服务 4 条缓存行。独立四行读流测试的首 A 到末 D
由 40 拍降为 37 拍，并验证双 bank、背压及每个 source 的数据。

`TileLinkLineWriteEngine` 现提供对称的 4 槽 64 字节 PutFullData 主端，
每笔 A 的 8 个 beat 保持同一 source 和地址，跨笔不交错；D 的 AccessAck 可乱序完成，
写错误与调用者 tag 一同返回。`TileLinkLineTransfer` 把读、写请求端通过双主仲裁合成
一个 TL-UH 主端口，分别保留各自的 4 槽 source 空间。
`make gsim-tilelink-line-write-test` 独立检查 A 背压、burst 锁定、乱序确认与 denied，
并用生产版组合 IP 经 RAM manager 完成整行写后读回、读写并发竞争和越界错误。
`make tilelink-line-write-rtl tilelink-line-transfer-rtl` 导出相应 RTL。
同一地址的读写顺序由调用者约束：依赖写入结果的读必须等待写确认。

## 端到端 burst 与剩余工作

默认 CPU、DMA 与可选共享读缓存仍发单拍 8 字节 Get/PutPartialData。
64 字节 Get/PutFullData 主端与单 RAM manager 已能通过可复用 IP 连接并通过 GSIM 验证；
可选单 CPU 写回缓存现已通过 TL-C Acquire/Grant/E 与探测接入单 RAM 和双 RAM 平台，
DMA 读写会先探测 CPU 持有的行，脏数据写回后才访问 RAM。独立双客户端 home
已验证独占行在 hart 间迁移；下一阶段仍需接入多 hart CPU 平台并完成权限状态转换，
随后将 DMA 线性拷贝接入更高并发的完整平台，
补交叉窗口、同时多笔 burst、响应重排及读写错误/背压检查，
按固件完成周期而非总线空载 beat 数判断收益。双 RAM 路由现在可传输整行，
但各 bank 内的 manager 仍串行处理多拍事务；单 RAM 的性能结果不能直接外推。
`make gsim-tilelink-dual-split-coherent-test` 验证 CPU 经 TL-C home 对两个 RAM bank
分别发出 64 字节整行 Get，并覆盖 DMA 脏行探测和原子操作。相同双 bank RAM 启动固件的
三个种子，直连为 2317/2720/2690 拍，写回 L1 为 3113/3315/3355 拍；
零附加延迟模型下该路径更慢，故仍为显式配置，不能把 burst 接通当作 IPC 收益。
当前整行 Get 用于 L1 缺失填充；脏 ProbeAckData 与 ReleaseData 通过 home 的
整行写引擎发出一笔 64 字节 PutFullData，收到 RAM 确认后才继续探测请求或确认逐出。
双客户端定向 GSIM 记录了 48 个 PutFullData A beat（6 条脏行），两次脏行迁移
均从 50 降到 39 周期。双 bank 启动、DMA 探测与原子固件均通过；
各 bank 内的 manager 仍串行处理多拍事务。

## TL-C 架构约束

两个可复用的 64 字节 TL-C 事务端点：`TileLinkLineAcquireEngine` 支持
4 笔在途的 AcquireBlock/AcquirePerm，按 source 重组 8 拍 GrantData，处理乱序 Grant，
并在 E 通道 GrantAck 成功握手后才向调用者交付结果；`TileLinkLineProbeEngine`
支持 4 笔在途 ProbeBlock，将乱序 ProbeAck 或 8 拍 ProbeAckData 转为完整行结果。
两者均支持通道背压，并断言同一 D/C 多拍消息不得穿插其他 source。
`make gsim-tilelink-line-acquire-test gsim-tilelink-line-probe-test` 验证这些事务端点，
`make tilelink-line-acquire-rtl tilelink-line-probe-rtl` 导出独立 IP RTL。
可选 `MachinePlatform(coherentLineCache = true)` 已将两者接入单 CPU 写回 L1 与逐行所有权 home：
CPU 普通读写缺失发 nToT AcquireBlock，home 通过 `TileLinkLineFillEngine` 从 burst RAM 获取整行，
GrantAck 后 CPU 安装数据；写命中仅更新 L1。DMA 读写先经 ProbeBlock 失效所有者，
脏 ProbeAckData 写回 RAM 后才执行 DMA 请求；CPU 原子操作先用 ReleaseData 逐出目标行，
随后绕过缓存。替换旧行时使用 Release/ReleaseData，home 写回后发 ReleaseAck。
4KiB RAM 默认配置 64 行、8KiB CoreMark 默认配置 128 行直接映射；
`coherentLineCacheLines` 可设置更小的行数以覆盖冲突逐出。
缺失与 home 的写事务目前各串行处理一笔；L1 可在一笔 Acquire/fill 等待期间
受理其他索引的两个读命中，保序响应仍排在较老缺失之后。同索引及写请求被阻塞，
并非多 MSHR。独立双客户端验证覆盖 T 权限在 hart 间迁移，
但平台尚无多 hart CPU 集成，不支持共享只读 B 权限、AcquirePerm 升级或多 MSHR，
不能宣称通用完整 TL-C。
单 hart、直接映射 L1 的 home 可用与 L1 行数相同的带物理标签 owner 槽位，
64 MiB Linux 仿真 RAM 配 128 个槽位；索引冲突时 L1 必须先 Release 旧行，
home 会检查该约束。多 hart home 仍采用按 RAM 行分配的 owner 状态；
大容量多 hart 目录的面积、布线与 Fmax 尚未验证，仍需可扩展组织。
`CoherentLineHome(nClients = 2)` 按行记录 owner、将 Probe 和 GrantAck 路由到对应客户端，
同时请求以轮转次序受理。`make gsim-tilelink-two-hart-coherent-test` 把两个独立写回 L1
接到同一 home，并用无缓存端验证两个 owner 的脏行、主动 ReleaseData 和同一行竞争。
脏行迁移在写回 RAM 后直接从 home 已缓冲的 ProbeAckData 发 GrantData，省去冗余的
8 拍 RAM 重读；随后将写回接成 64 字节 PutFullData burst，相同 GSIM 用例两个方向
又从 50 降至 39 周期。数据仍先写回 RAM，
所以新 owner 日后干净逐出不会丢失脏内容。
`make gsim-tilelink-coherent-platform-test` 使用 UART、DMA 脏行探测与原子固件各 3 个种子；
`make gsim-tilelink-coherent-evict-test` 用 16 行配置额外检查脏 ReleaseData 逐出。
带 MMU 的配置使用物理地址作为 L1 标签；页表遍历和 PBMT=NC/IO 数据请求
从一致性 home 进入，必要时探测或逐出 CPU 的脏行。
`make gsim-vm-data-coherent-platform-test gsim-vm-instruction-coherent-platform-test`
覆盖该组合；用例结果见[虚拟内存合同](virtual-memory.md)。
`make coherent-platform-rtl` 导出组合 RTL。

同一 CoreMark 二进制、CRC 错误 0、32 项 ROB/64 个物理寄存器的 GSIM 结果：

| RAM 附加响应延迟 | 直连周期 / IPC | 可选写回 L1 周期 / IPC |
| --- | ---: | ---: |
| 0 拍 | 305,375 / 1.0570 | 302,809 / 1.0660 |
| 12 拍 | 600,412 / 0.5376 | 303,337 / 1.0641 |

12 拍模型减少 297,075 周期；零附加延迟模型减少 2,566 周期。
缓存仍为显式可选配置，尚未取得 Vivado 资源和 Fmax 数据。
这是模型中的单次迭代对照，非正式 CoreMark 分数，也不代表 FPGA Fmax。

2026-09-27 对当前固定 CoreMark 固件的定向复测：L1 数据阵列使用字节写使能后，
部分写命中不再读取旧字再合并，写确认与读命中共用保序响应队列。相同 GSIM 配置
从 239,685 拍、IPC 1.3466842 降至 239,058 拍、IPC 1.3502163；
两次均退休 322,780 条，CRC 错误 0。改善 627 拍（约 0.26%），
说明写命中路径不是当前 CoreMark 的主要瓶颈。双 bank 启动/DMA/原子及双客户端脏行
迁移的定向验证通过；字节写使能的 FPGA 资源与 Fmax 仍待 Vivado 测量。
同轮直连配置为 253,576 拍、IPC 1.2729123；优化后的 L1 配置比它少
14,518 拍（约 5.7%）。这是两种访存配置的对照，不能把全部差值归因于本轮写命中改动。
脏行写回改为整行 burst 后，同一 CoreMark 仍是 239,058 拍、IPC 1.3502163；
该负载的收益不能从脏行迁移微基准外推。

默认 CPU 与 DMA 在 `AtomicDataMemory` 中合并后，只有一个数据 TileLink 主端口；
可选 `SharedReadCache` 位于合并点之后，并非 CPU 私有缓存。
DMA 能独立发访存请求，不等于已经存在可被探测的第二个缓存代理。
仓库中的旧 `TLCoherenceHub` 只做单个 8 字节目录项和阻塞式冲突处理，
没有新核 64 字节缓存行、完整 transient 状态、E 通道确认或现平台 RAM 支持，
不能直接作为新 SoC 的 TL-C 验收结果。

当前 TL-C 路径以 64 字节行为目录粒度，将 CPU 私有缓存作为 TL-C client；
DMA 保持无缓存请求端，其 Get/Put 经过一致性 home agent，
由 home agent 在需要时探测、写回或失效 CPU 缓存。现有多客户端目录只有独占 owner，
未来增加共享 B 状态时仍需扩展 sharer 位图和权限状态机。至少验证 Acquire/Grant/GrantAck、
Probe/ProbeAck[Data]、Release[Data]/ReleaseAck、并发缺失与背压、脏数据归属、
DMA 写后 CPU 读、CPU 写后 DMA 读及原子排序。指令侧取指主端目前不经过数据 home；
`FENCE.I` 因此先等待本 hart 私有 D-cache 的脏行逐行 `ReleaseData/ReleaseAck`，
再失效本 hart 的取指缓存并重取。它不是多 hart 的广播同步；远端 hart 的代码更新
仍需要软件协调和远端执行 `FENCE.I`。定向验证入口为
`make gsim-tilelink-coherent-fencei-test`。

2026-10-04 新增可选网络 DMA，`DmaRegisterDataAdapter` 将右对齐 RegisterPort
字节转成 DataPort beat lane，经既有 atomic/coherent home→TL→RAM/AXI 路径访问内存。
短验收 `simulator/gsim/ethernet_dma.py` 使用独立字节内存 oracle，三个随机种子均检查
CPU 脏 TX 数据被探测后送出，以及 RX 写入失效 CPU 旧缓存且保留尾字外的字节；
不借此宣称多 hart、完整 TL-C 或标准 Linux DMAengine 驱动已实现。

性能验收要同时记录命中率、未命中并行度、总线有效字节/拍、CPU/DMA 完成周期，
以及 Vivado 可用后目标器件的资源与布线后 Fmax。当前 GSIM CoreMark IPC
加速已测得；实际 FPGA 频率和综合后的每秒性能仍待验证。
