# TileLink 到 AXI4 内存边界

独立的 TileLinkAxi4Bridge 把 TL-UL A/D 的普通内存事务转换为 64 位 AXI4。
其外部端口不含 CPU DataPort；内部组合已经单独验收的
TileLinkDataRamAdapter 和 OrderedAxi4Bridge。这为保持 SoC 内部 TileLink、
外部只使用 AXI4 提供可复用的边界，但尚未接入机器平台、DDR 或 FPGA 接口。

## 协议合同

- TL 侧只接受 Get 和 PutPartialData，size 为 0..3，param 为 0，A 不带 corrupt；
  地址必须按访问宽度自然对齐，mask 必须精确覆盖目标字节。B/C/E 一致性事务不支持。
- 每笔 TL A 保留 source、size 和读写类别，AXI 响应按接受顺序转换成 TL D。
  读返回 AccessAckData，写返回 AccessAck；AXI RRESP 的 SLVERR/DECERR 变为 TL denied。
  写目标必须保证 BRESP 成功；写错误触发断言，不能当作可恢复的精确写异常。
- AXI 使用固定 ID 0、单拍 INCR 事务。最多 8 笔读、默认最多 4 笔写在途；
  AW/W 各自按写请求顺序推进，读写方向切换时排空旧响应。
  AXI 从端须保持同 ID 的读、写响应顺序。
  TL source 可以各不相同，但 TL D 按 A 顺序返回；桥不提供乱序 D 吞吐优化。
- TL 默认 64 位地址；AXI 地址可选 64 或 32 位。32 位版本在请求握手时断言
  TL 地址高 32 位为零，禁止静默截断；同一时钟和复位域。
  不含 burst、多个 AXI ID、AXI 独占访问、缓存一致性、原子事务或跨时钟域。
  平台仍须负责地址译码、外部代理互斥、DMA 可见性和 FENCE 顺序。

make gsim-tilelink-axi4-bridge-test 使用独立字节内存模型验收 105 笔事务：
64/32 位 AXI 配置各执行 96 读、9 写、5 次被拒读，AXI 侧达到
8 笔读和 4 笔写在途。
32 位配置另检查高位地址被拒绝。测试覆盖 TL A/D 与
AXI AR/AW/W/R/B 的独立背压、窄写 byte strobe、读写排空、source/size 保留，
并故意篡改读数据检查参考模型能报错。
另以同一内存模型运行 256 笔连续写，1 写槽为 1379 拍、4 写槽为 378 拍；
两组均核对最终内存内容。约 3.65 倍完成速率仅适用于该独立桥微基准，
不代表 CPU IPC 或 DDR 实测带宽。
make tilelink-axi4-bridge-rtl 和 make tilelink-axi4-bridge32-rtl
分别导出 64/32 位 AXI 地址版本的独立 SystemVerilog。
这些结果不构成外部 DDR 性能、Vivado Fmax 或完整 SoC 启动验收。
