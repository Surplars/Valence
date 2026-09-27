# 新核 TileLink 内存桥

`OrderedTileLinkBridge` 将新核的有序 `DataPort` 转为 64 位 TileLink A/D 请求与响应。
它是新 SoC 内部 TileLink 互联的桥接基线。`MachinePlatform(tileLinkMemory = true)`
现将它接入普通 RAM 数据路径，默认平台仍直连同步 RAM。
旧 `IonSoC` 中的 TileLink 互联不代表新平台已有多主设备互联。
平台关系见[模块化 SoC 合同](modular-soc.md)。

## 协议与顺序合同

- 默认 8 个 source ID，每个在途请求独占一个 ID。TL D 可按 source 任意次序返回，
  桥将结果暂存并按 `DataPort` 请求顺序交付。source 直到上游接收响应才释放。
- 每拍最多发出一笔单拍 TL A 请求。读可有 8 笔在途；通用桥默认只有一笔写在途，
  因为 TileLink 本身不保证不同 source 的写按 A 顺序生效。平台中的单 RAM adapter
  按 A 顺序交给有序 `DataPort` RAM，因而启用 `orderedWrites`，允许最多 8 笔连续写在途。
  单 RAM 配置还启用 `orderedMixedAccesses`：读和写可同时在途，RAM 按 A 顺序执行，
  桥仍按原 `DataPort` 请求顺序返回结果。这个开关不能用于只保证写顺序、
  不保证读写相对顺序的通用 TL manager。
  双窗口配置改用 `orderedWriteBankBytes`，仅同 bank 的连续写可并行；换 bank 先排空。
  通用桥及双窗口配置在读写方向切换时等待旧响应全部被上游接收。
  满槽释放与重新分配之间目前可能有一拍间隔，
  因此“一拍一请求”只是有空闲信用时的上限，不是持续吞吐保证。
  A 通道被背压后会锁定选中的 source；即使其他 D 响应在此期间释放更小的 source，
  已呈现的 A 负载仍保持稳定。
  写顺序约束依据 [TileLink 1.8.1 §6.5](https://starfivetech.com/uploads/tilelink_spec_1.8.1.pdf)。
- 普通自然对齐读为 Get；写为 PutPartialData。地址、访问大小、64 位数据与 byte mask
  按 TileLink beat 字节 lane 编码。只接受非原子请求；请求握手时检查对齐、精确 mask，
  32 位地址参数时还检查高位不可截断。
- D 响应检查 source、opcode、param 和 size。读的 denied/corrupt 转为 `DataPort.error`。
  通用桥默认断言写目标保证成功。机器平台设置 `allowWriteErrors`，把普通写错误返回上游；
  可能提前退休的 RAM 写仍由 `StoreBuffer` 断言保证成功，不能把 MMIO 接到缓冲写窗口。
- 这是 TL-UL 风格的非一致性主设备，只使用 A/D；B 探测不接收且出现时断言，C/E 不发出，
  不能接需要探测响应、缓存权限或原子事务的 TL-C 路径。MMIO、原子操作与 DMA 的共享可见性
  仍需在平台边界单独定义。

`make gsim-tilelink-bridge-test` 用独立字节内存模型验证通用、同 bank、有序写及混合读写
四种桥配置，各有 105/105/106/106 笔事务：96 读、9/9/10/10 写，读峰值 8 笔在途，
34 次乱序 D 返回，
9 次读错误（denied 或 corrupt）；有序写配置达到 5 笔、同 bank 配置达到 4 笔写在途，
并验证无副作用的写拒绝。
各配置都覆盖 A 与上游响应背压；混合配置实际观察到读写同时在途，
同一独立模型的 106 笔事务由有序写配置的 409 拍降至 383 拍。
另有定向用例检查背压期间释放更小的 source 后，
A 的 source 不改变。
故意篡改首个读结果的负向测试也通过。
`make tilelink-bridge-rtl` 导出 `build/ip/tilelink-bridge/OrderedTileLinkBridge.sv`
与 `filelist.f`。这只是 RTL 导出，尚无 Vivado 综合或板上 Fmax、LUT、BRAM 数据。

可选平台路径为 LSU/StoreBuffer 的 `DataPort`→MMIO 路由→CPU/DMA 原子共享边界→
可选共享读缓存→TileLink 桥→RAM adapter→同步 RAM。RAM adapter 通过 8 项 FIFO
保存 A 的 source/size/操作，再按下游有序响应返回 D；现有 RAM 最多只接两项在途，
不能把桥的 8 项容量当作整机 8 项 RAM 并发。此单主配置的取指 ROM 仍为独立同步接口；
另有可选的[双主 TileLink 取指路径](tilelink-fetch.md)。
`make gsim-tilelink-platform-test` 覆盖 RAM、DMA、原子整机启动；
`make tilelink-machine-platform-rtl` 导出该配置。当前路径只有单个 RAM manager，
未覆盖跨从设备路由、外部 DDR、TL-C 一致性和 Vivado 时序。
三个调度种子的启动结果均正确。单 RAM 混合读写后，双主 TileLink 平台种子 0 的
RAM/DMA/原子固件分别由 3613/5766/6848 降到 3611/5559/6694 拍；
与此前直连 RAM 的 DMA 5440 拍相比，TileLink 路径仍有延迟开销。
上述固件完成时间不是 CPU IPC，也没有频率或资源结论。
本次可选平台逐种子结果保存在 `build/gsim/tilelink-platform.json`。

`make gsim-tilelink-dual-latency-test` 在取指和数据都走 TileLink 的路径上运行 40 拍
有序 RAM 响应模型。4 槽 LSU 的三个种子为 9413/9530/9513 拍，8 槽为
7965/8075/8080 拍，减少 1433～1455 拍；两组各提交 6925 条指令。
8 槽还运行 DMA 和原子固件，各三个种子通过。结果保存在
`build/gsim/tilelink-dual-latency.json`。混合读写优化对此延迟固件的完成周期
无变化，因此不能把独立桥的收益外推到所有软件。

另有 `splitTileLinkMemory = true` 的片上双 RAM 窗口配置，使用
[TileLink 路由 IP](tilelink-router.md)和两个独立 RAM manager。跨窗口 D 可乱序返回；
不同 manager 不保证写顺序，因此此配置只允许同一窗口连续写流水化，换窗口先排空。
两个 RAM manager 均接受 16/32/64 字节 Get/PutFullData；每笔 burst 必须完整落在一个窗口内。

下一步是扩展多主设备互联、MMIO 地址范围与设备侧 TL 适配，保留原子共享语义。
独立的 [TileLink→AXI4 适配](tilelink-axi4-bridge.md)已经 GSIM 验证和 RTL 导出，
尚未接入本机器平台或外部 DDR。Zynq-7000 若使用原生 AXI3 的 PS HP，
协议转换留给 Vivado 集成 IP，不在项目中实现 AXI3。
