# 双主 TileLink 仲裁 IP

`TwoMasterTileLinkArbiter` 将两个独立 TL-UL A/D 主端口接到一个 manager。
轮转仲裁 A；manager 背压时锁定选中端口，保持请求不变。
每个主端口保留自己的 source 空间，下游 source 高位追加主端口编号，
返回 D 时检查在途归属、去掉编号后送回原主端口。
同一主端口重复使用尚未完成的 source 会被阻塞；不同主端口可同时使用相同 source。
允许不同 source 的 D 乱序返回；B/C/E 一致性通道不支持。

上游默认参数为 64 位地址、64 位数据、3 位 source，下游因此为 4 位 source。
接现有 `TwoBankTileLinkRouter` 时必须用 **下游** 参数实例化路由器与 RAM adapter，
不能沿用它们默认的 3 位 source。Scala 展开检查已覆盖仲裁器到双 bank 路由器的
4 位 source 接线。仲裁器每拍最多发一笔 A、接一笔 D；
两主竞争同一 manager 时不会提高该 manager 的带宽。

`make gsim-tilelink-arbiter-test` 用独立 manager 模型检查两主各 12 笔请求、
相同本地 source ID 并发使用、A/D 背压、A 负载稳定、乱序 D 与错误注入。
`make tilelink-arbiter-rtl` 导出独立 IP 的 SystemVerilog。
这些检查没有测量 FPGA Fmax、LUT 或 BRAM。

当前机器平台的 CPU 和 DMA 在 `AtomicDataMemory` 中统一排序，然后进入一个数据
TileLink 主端口；这个边界必须保留，直到有新的跨主设备原子与保留语义方案。
可选 `tileLinkFetch` 平台已将取指接为第二主端口；
`TwoMasterTwoBankTileLinkCrossbar` 使用两个地址路由器和两个独立仲裁器，
使 ROM 与 RAM 窗口能并行传输。具体转换、整机验证和性能限制见
[TileLink 取指路径](tilelink-fetch.md)。
