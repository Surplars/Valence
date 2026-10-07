# TileLink 到 AXI4 边界

`TileLinkAxi4Bridge` 是独立的 64 位 TL-UL→AXI4 主端口，供后续 DDR 或 AXI4
外设集成，板级外部 DDR 路径已接入该桥。默认启用直接的 INCR burst 路径；原先的
`TileLinkDataRamAdapter`＋`OrderedAxi4Bridge` 单拍高并发路径仍可用
`burstEnabled = false` 选择，供旧设计和微基准回归。新网络 DMA 是显式候选，
不修改已部署的 bit 或默认 ISA/profile。

## 默认 burst 路径

- TL A 支持自然对齐的 Get、PutFullData，以及单拍/多拍 PutPartialData；不支持原子、
  TL-C 一致性、交错写消息或损坏的 A 数据。单拍宽度为 1/2/4/8 字节，
  大于 8 字节的 Get/PutFullData/PutPartialData 以 64 位数据拍组成一笔 TL 消息。
  PutFullData 和 Get 要求完整的对应字节 mask；PutPartialData 的 mask
  可以是访问范围内的任意子集，包含稀疏与全零 mask。
  多拍部分写可逐拍改变 data/mask，其余 opcode/param/source/size/address/corrupt
  必须保持不变；按原有非交错消息规则收齐，不能与其他写消息穿插。
- 一个 TL 消息对应一个 AXI4 INCR 事务：`AxLEN = 拍数 - 1`，
  多拍时 `AxSIZE = 3`，单拍时 `AxSIZE = TL size`。`WSTRB` 来自 TL mask，
  只有末拍置 `WLAST`，严格核对 `RID/BID=0` 和 `RLAST`。
  4 KiB 边界、自然对齐、地址宽度超出配置等合同在请求握手时断言。
- 默认 `maxBurstBeats=16`，TL `sizeBits=3`，最大 128 字节；
  可配置到 256 拍（2 KiB），此时 TL `sizeBits` 至少 4。
  256 拍会实例化 256×64 位读/写缓冲，FPGA 资源与时序代价很高；
  DDR 缓存行建议继续使用默认 16 拍或更小配置。
- 桥一次保有一笔完整 TL 事务，固定 AXI ID 0。写消息先收齐再发 AW、W，
  AW 握手后发 W，收到 B 才发单拍 TL `AccessAck`；读消息先发 AR，
  收齐 R 后发 TL `AccessAckData` 各拍。这保证 R 任意一拍出错时，
  整条 TL D 数据消息均稳定标记 `denied/corrupt`，且跨读写保持请求顺序。
  AXI `SLVERR/DECERR` 的 RRESP/BRESP 转成 TL `denied`；被拒读数据清零。
  上游仍须处理 denied，尤其不能让可能失败的 MMIO 写提前退休。
- `AxCACHE/PROT/QOS` 默认为零，可在实例化时指定；`AxLOCK=0`。
  AXI A/W 和 TL D 在背压期间保持载荷稳定。同一时钟/复位域，
  无 CDC、多个 AXI ID、乱序响应、独占访问或缓存一致性。
  一次仅一笔在途使它优先保证功能正确，尚不能代表 DDR 峰值带宽。

AXI4-Lite 外设不能把这个完整 AXI4 端口直接按同名信号硬接；应在 Vivado
[SmartConnect](https://docs.amd.com/r/en-US/pg247-smartconnect/Conversion-to-AXI4-Lite)
或 AXI Protocol Converter 中做 AXI4→AXI4-Lite 协议适配，
并把寄存器访问限制为单拍。多时钟域还需 AXI Clock Converter。
现有板级 DDR 已有地址译码和 MIG 校准/跨域连接；新 MAC 候选在此之上复用
一致性 home 与 DDR 路径，不是直接绕过 CPU 缓存写 MIG。新的网卡上板仍需
PHY 管脚/时序、MDIO、MAC 初始化、驱动与授权验收。
AXI burst 不得跨 4 KiB、INCR 长度可达 256 拍，依据
[Arm AMBA AXI 协议规范 IHI 0022H](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)。

## 验证与导出

`GSIM_CXX=clang++-19 make gsim-tilelink-axi4-burst-test` 验证 9 笔定向事务，
包括 16/64/128 字节读写、页尾 16 字节、窄访问/字节使能、各通道背压、
读写错误及坏 `RLAST` 断言。`gsim-tilelink-axi4-burst256-test` 另验收完整
256 拍写回读（2 KiB）；`gsim-tilelink-axi4-burst32-test` 验证 32 位地址配置
及高位地址拒绝。原 `gsim-tilelink-axi4-bridge-test` 仍验证旧路径的
105 笔混合事务、32 位地址拒绝与单拍流水写吞吐；不要把旧路径性能
误认为新 burst 路径性能。

`make tilelink-axi4-bridge-rtl` 和 `make tilelink-axi4-bridge32-rtl`
分别导出默认 burst 路径的 64/32 位 AXI 地址 SystemVerilog。
若需 256 拍，使用
`mill -i IonSoC.test.runMain ooo.TileLinkAxi4BridgeRtlMain build/ip/tilelink-axi4-bridge256 64 256`。
这些是独立 IP 的协议验证，不是新网卡的整机验收或 Vivado Fmax 结果。

## 2026-10-04 网络 DMA / 部分写短验收

```sh
cd /home/openion/Valence
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/ethernet_dma.py --tag fresh-tag
```

此入口在一次批处理中检查真实整机 RTL 导出、DMA/一致性内存链及 TL→RAM/AXI。
RAM 部分写覆盖 256 种 mask、2048 个 beat，独立字节 oracle 验证未选中字节保持；
AXI 部分写覆盖 521 笔事务、16/32/64/128 字节稀疏/零掩码 burst、WSTRB/WLAST、
背压与 B 错误确认；旧单拍路径另有 512 笔事务。故障注入必须被 oracle 或协议断言拒绝。
CPU-only 的 `OrderedTileLinkBridge`/`SynchronousDataRam` 仍默认严格检查原请求 mask；
`ethernetDma=true` 才为新 DMA 开启子集 mask 合同；通用 `TileLinkAxi4Bridge` 两种实现
均支持合法部分写。部分写功能完成不等于完整 TL-C、多 AXI ID 或千兆线速已完成。
