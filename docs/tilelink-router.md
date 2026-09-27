# 片上 TileLink 双 RAM 窗口路由

`TwoBankTileLinkRouter` 是新平台的 TL-UL A/D 地址路由 IP，不复用旧 `TLXbar`。
一个主端口按地址选择两个相邻的 RAM manager：默认 `0x80010000..0x800107ff`
与 `0x80010800..0x80010fff`，各 2 KiB。未映射请求在路由器内部返回 denied，
不进入任何 RAM。取指和 MMIO 暂不经过此模块。

每个握手的 A 请求占用一个 source ID；路由器记录 source 所属窗口，
两个下游 D 由轮转仲裁汇入主端口，并检查响应来自原窗口。
不同窗口可乱序完成，`OrderedTileLinkBridge` 再按 `DataPort` 请求顺序交付。
默认 3 位 source 可有 8 项在途；每拍最多发一笔 A、收一笔 D。
未映射错误暂为单项寄存槽，连续未映射访问之间可能停顿。
桥到路由器和 D 仲裁均有组合路径，实际频率尚未测量。

这个配置关闭跨 manager 的 `orderedWrites`：不同 manager 的 Put 不保证按 A 顺序生效。
桥按窗口组成写队列，同一 RAM bank 可流水化连续写；切换 bank 前必须等旧写的 D
全部由上游接收。未映射写也保持单笔，避免跨窗口可见性顺序被破坏。
两 bank 各自经 `TileLinkDataRamAdapter` 接同步 RAM；CPU 与 DMA 的原子共享边界
仍位于 TileLink 之前。B/C/E 一致性通道不支持，不能将它用作 TL-C 互联。

`make gsim-tilelink-router-test` 用独立响应模型检查 16 笔事务：bank0 四笔、
bank1 八笔、范围上下两侧未映射共四笔，包含 6 次乱序 D、A/D 背压，以及数据篡改和
错误 source 所属窗口的负向注入。
`make gsim-tilelink-split-platform-test` 运行跨两个 bank 的 RAM 启动镜像，
以及原 DMA、原子启动镜像；结果保存于 `build/gsim/tilelink-split-platform.json`。
`make tilelink-router-rtl tilelink-split-platform-rtl` 导出独立路由 IP 与组合平台 RTL。
双窗口整机 DMA 种子 0 在同 bank 写流水化后为 5904 拍，仍慢于单窗口配置的
5644 拍；路由配置暂为可选验证路径，不能把双 bank 数量直接当作性能提升。
此配置仍是单主端口、双 RAM manager。另有可选的[双主取指路径](tilelink-fetch.md)，
在 ROM/RAM 两窗口分别仲裁，并可在 RAM 窗口内再接本路由器。
MMIO 原生 TL 适配仍未接入；独立 [TileLink→AXI4 边界](tilelink-axi4-bridge.md)
已验证，但尚未接入此路由配置。
