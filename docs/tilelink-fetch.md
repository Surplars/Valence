# TileLink 取指路径

可选 `tileLinkFetch` 配置将 `SynchronousFetch` 接到 `InstructionTileLinkBridge`，
再通过双主双窗口 TileLink 互联访问片上 ROM；默认机器平台仍使用直接 ROM 端口。
数据主设备仍由 CPU、DMA 经 `AtomicDataMemory` 合并，原子排序边界未移动。
窗口 0 为 `0x80000000..0x8000ffff`，窗口 1 为 `0x80010000..0x8001ffff`；
ROM 实际容量由 `romWords` 指定，越界的32/64位 Get 返回 denied 和零数据。
窗口 1 可直连 4 KiB RAM，或接已有的两个 2 KiB RAM 路由。
窗口外请求由路由器返回 denied。B/C/E 一致性通道不支持。
原有 8 字节桥的 `InstructionPort.responseError` 给返回的两个 32 位 word 各带一个错误位；
4-issue 宽接口则对四个 word 各保留一个错误位。
桥遇到 denied/corrupt 时把对应 beat 置零并标错；直接 ROM 越界的 word 也标错。
同步前端按 PC 保存错误位，乱序核把取指访问错误分配进 ROB，在队首报告
instruction access fault（`mcause=1`，`mtval=出错指令 PC`）。
正常与出错 word 混在一个取指包时，正常 word 仍可按序提交。

以下为原有 8 字节桥的事务规则：每次返回从 4 字节对齐 PC 开始的两个 32 位字。
启用PMP的机器平台对两个指令字分别检查执行权限；两字均允许时沿用下述64位快速路径。
仅一字允许时发一笔对齐的32位Get，另一字在取指包中标错；两字均不允许时桥直接返回
双字错误包，不向TileLink发送Get。ROM manager相应接受32/64位Get，只读取获准的bank。
PC 按 8 字节对齐时发一笔 64 位 Get；PC 位 2 为 1 时向前后两个对齐 beat
各发一笔 Get，再把第一笔高 32 位和第二笔低 32 位拼成原取指包。
两个 Get 使用不同 source，D 可乱序返回；每个取指包最多两笔在途，
前端仍限制为一个包在途。最后一笔 D 可直接旁路给前端，响应背压时保存在寄存器中。
桥保留上一正常64位取指包最后一个**有效 ROM beat**；部分字请求不填充该缓存。
若新包从它的高 32 位开始，
直接复用该 beat，只对后一个 beat 发 Get。缓存仅覆盖配置的只读 ROM 容量；
denied/corrupt 不入缓存，RAM 取指不复用，平台编程 hold/reset 会清空有效位。
同拍旧 D 与新请求相遇时可旁路刚完成的 beat；新 A 被背压时锁住命中决定和数据，
使 TileLink A 负载在等待期间保持稳定。这是单 beat 重用，不是带失效协议的 I-cache。
桥在接收取指请求的同拍发首笔 Get，并在连续取指包之间轮换两组 source
（0/1 与 2/3），允许旧包最后一笔 D 与新包首笔 A 同拍握手。
理想单拍 ROM、无背压时，8 字节对齐包最早下一拍返回，跨 beat 包最早两拍返回。
顺序的对齐包理论上可每拍接收一包；跨 beat、仲裁和背压会降低吞吐。
ROM manager 使用四项 source 元数据队列与原有同步双 bank ROM，接受 Get 后按原顺序返回。

`TwoMasterTwoBankTileLinkCrossbar` 对每个主端口先做地址路由，再在两个窗口分别轮转仲裁。
因此不同窗口理论上每拍各能接受一笔 A、各返回一笔 D；同一窗口仍只有一笔 A/D
通道容量。两主各有 3 位本地 source，manager 侧增加一位主设备编号。
取指 PC→TileLink A→地址译码/仲裁→ROM request.ready，
以及旧包 D→新包 A.valid 现为组合路径，
source 记分板和返回旁路也会影响关键路径；尚无 Vivado 综合、布线或 Fmax 数据。

验证入口：`make gsim-tilelink-fetch-test gsim-tilelink-crossbar-test` 检查奇数 PC 拼包、
乱序 D、双 bank 同拍 A/D、争用、背压、逐 word 错误位及PMP部分允许掩码；
`make gsim-pmp-fetch-platform-test` 使用M→S→U整机固件检查锁定PMP后无禁执行字Get，
跨界允许字只发32位Get，并核对精确取指异常；
`make gsim-tilelink-dual-platform-test gsim-tilelink-dual-split-platform-test`
用 RAM、DMA、原子固件各三个种子做 GSIM 整机验收，提交由独立 C++ 体系结构模型核对；
这组同步平台测试不调用 NEMU。
双主整机还执行 ROM 上、下边界越界跳转，核对一个正常提交后得到精确访问异常；
下边界用例的另一个半包是有效 ROM 指令，也不得越过故障指令提交。
独立取指测试还核对实际 Get 数量：13 包中有 4 次 ROM beat 复用，
并确认 RAM 仍发原本的两笔 Get、复位后旧 ROM beat 不再命中。
同步整机日志的 `FETCH_WAIT` 行统计第一条指令无效的周期；`duringDma` 是其中 DMA 活跃的周期，
`enabled` 只计允许提交的周期。对应的 `fetch_wait_*_cycles` 字段也写入平台 JSON 报告。
这是前端可见空等计数，不能直接当作后端停顿或 IPC 损失。
`make tilelink-fetch-rtl tilelink-rom-adapter-rtl tilelink-crossbar-rtl`
分别导出桥、ROM 适配器和双窗口互联的独立 SystemVerilog；这不是 Vivado IP 封装。
对照数据在 `build/gsim/tilelink-*.json`。下述数字是混合读写优化前的取指开销对照：
单 RAM 的种子 0，原数据侧 TL 路径 RAM/DMA/原子分别为 3615/5644/6855 拍，
双主取指路径为 3613/5766/6848 拍。当前单 RAM 桥允许有序读写混合在途后，
启用PMP取指屏障后双主路径分别为3614/5560/6695拍；不同版本间的差值不能单独归因于取指路径。
这些是整个固件运行拍数，不是 IPC 或频率；DMA 路径仍有取指开销，
组合请求路径的 Fmax 变化尚未测量。
种子 0 的 DMA 固件，直接 ROM 与双主 TileLink 取指的 `FETCH_WAIT total` 分别为
1262 和 1584，`duringDma` 分别为 65 和 71；取指空等增加 322 拍，
整机仅增加 122 拍，因此不能把前端空等增量直接当作总延迟增量。
曾用独立回跳取指用例验证保留两个 ROM beat 的命中，但整机 DMA 固件三个种子的运行拍数
均未改善，因此保持单 beat 缓存，避免在尚无收益证据时增加 FPGA 寄存器和命中比较路径。
上述桥及周期记录是禁用整行缓存时的基线。现在 `MachinePlatform(tileLinkFetch=true)`
默认在物理取指侧接入 `InstructionLineCache`：16 条 64 字节行、两路八组，数据使用
同步 SRAM，RAM 行缺失发一笔 `size=6` 的 TL-UH Get，接收八个 64 位 D beat。
同行后续完整对齐取指包由缓存返回，不再访问 RAM。压缩指令前端还保留两路、
默认 2-issue 为 64 组、4-issue 为 128 组的 8 字节取指包缓存；
4-issue 在当前包和三个后继包中预取第一个缺失包；无压缩指令配置的前端保留两个包槽。
压缩指令 4-issue 配置的前端到物理 I-cache 接口每次返回对齐的 16 字节，
在一次同步 SRAM 命中中填充相邻两个前端包；2-issue 仍取 8 字节。
ROM 和不适合整行填充的地址通过适配器依次发两笔 8 字节请求，故这些路径不具备
原生 16 字节读带宽。仅当完整取指包、整条 64 字节行都位于 RAM 且 PMP
允许整行执行时才突发填充。
ROM、部分字、非对齐取指包和 PMP 边界仍走原逐包桥；整行返回错误时再取原包，
保留逐字错误精度。64 字节行天然处于同一个 4 KiB 翻译页内，指令 MMU 在桥上游
先翻译请求包；物理侧仍重新检查整行 PMP。同步 SRAM 命中响应与下一包请求可同拍握手，
独立 GSIM 用例连续 8 个命中包用 9 拍完成，稳态每拍一包，且验证了响应背压后的续传。
当前 I-cache 一次只处理一个前端取指请求。4-issue 配置在 RAM 整行缺失时，
最多同时保留一条需求行和两条顺序预取行；预取 Get 发出时即可继续寻找
下一行，前瞻窗口最多覆盖相对最近需求行的四行。需求行与预取行的 TileLink source 分离，ROM/逐包
回退另用独立 source 区间。预取不跨 4 KiB 页或 RAM/PMP 边界，`FENCE.I`
丢弃未完成的旧预取。独立 `make gsim-instruction-prefetch-test` 验证三笔 Get
在第一笔返回前同时在途、预取命中、失效后重新读取代码，以及预取 A 通道
受背压时切换 ROM 请求仍保持原请求稳定。
机器核的 `FENCE.I` 在 ROB 队首等待 LSU/写缓冲排空；写回式私有 D-cache 配置
还逐项扫描脏行，通过 TL-C `ReleaseData/ReleaseAck` 写回到取指可见 RAM 后，
才同时失效前端包缓存和物理侧整行缓存，并从后继 PC 重取。已锁定且受背压的旧取指请求仍保持 TileLink A 稳定，
其返回被丢弃。独立前端 GSIM 测试覆盖此情况。
双主单 RAM 与双 RAM 路由配置均已运行写入两条 RAM 指令、执行 `FENCE.I`、
跳转到 RAM 的整机用例：9 条提交、43 拍，RAM 中的 `addi` 正确执行，随后 `ecall`
在 RAM PC 精确陷入。新增 `make gsim-instruction-line-cache-test` 独立验证多行、
同组两路、64 字节突发、失效、PMP 边界和整行错误时的精确单包重试；
`make gsim-tilelink-coherent-fencei-test` 验证写回 D-cache、整行 I-cache、
`FENCE.I` 串接后的 RAM 代码执行（9 条提交、99 拍）。

`make gsim-instruction-ipc ISSUE_WIDTH=4 INSTRUCTION_CACHE_LINES=32
INSTRUCTION_IPC_OPTIONS="--compressed-body --ram-delay 12"` 运行 RAM 中的 1536 字节循环，
核对每条 RAM 指令的退休、最终寄存器值与精确 `ecall` 陷入。循环共 30 轮，
每轮 768 条压缩 `c.addi` 加 2 条 32 位控制指令，代码超过前端 8 字节包缓存容量，
但可容纳于 32 行整行缓存。`warmIpc` 只统计第一轮结束后的 29 轮：

| 4-issue 压缩循环 | RAM 响应延迟 | 全程 IPC | 稳态 IPC | RAM 取指 Get |
| --- | ---: | ---: | ---: | ---: |
| 32 行缓存 | 0 | 3.778 | 3.966 | 27 次整行 |
| 无整行缓存 | 0 | 3.964 | 3.966 | 5837 次逐包 |
| 32 行缓存 | 12 | 3.608 | 3.966 | 27 次整行 |
| 无整行缓存 | 12 | 0.305 | 0.305 | 5830 次逐包 |

零延迟仿真中，两条路径的稳态吞吐相同；整行缓存的冷填充使全程多 288 拍。
12 拍响应延迟是参数化 RAM 模型，不是 FPGA 或外部 DDR 的实测时序，
但显示缓存可消除重复逐包取指的等待。另一个纯 32 位指令循环中，
2-issue 全程 IPC 在关闭/启用整行缓存时分别为 1.988/1.894；
4-issue 为 1.987/1.894，因为每个 8 字节取指包最多容纳两条 32 位指令。
上表为扩大物理取指接口前的历史对照。当前 4-issue、128 组前端缓存、64 行
物理 I-cache 的 3 KiB 纯 32 位循环超过 2 KiB 前端包缓存容量；30 轮共退休
23,100 条、6072 拍，整段 IPC 3.804，首轮之后 22,330 条/5632 拍，
稳态 IPC 3.965，后 29 轮 RAM 取指 Get 为 1。故已验证 **I-cache 命中**
时持续供给四条 32 位指令；这个结果不证明 I-cache 冷缺失时也能持续四发射。
复现命令：`make gsim-instruction-ipc ISSUE_WIDTH=4 INSTRUCTION_CACHE_LINES=64 INSTRUCTION_IPC_OPTIONS=--long-body`。
将物理 I-cache 缩到 16 行（1 KiB）后，3 KiB 循环每轮都出现整行缺失：
相同镜像在顺序预取前为 22,330 条/22,678 拍、稳态 IPC 0.985、
整段 1474 笔 RAM 取指 Get；启用两条并发预取和 RAM manager 的一笔排队 Get 后，
稳态为 22,330 条/18,197 拍、IPC 1.227，整段 1522 笔 Get。
相对无预取基线，稳态周期减少 19.8%，Get 增加 3.3%。进一步增至三条并发预取时
稳态反而为 18,332 拍、IPC 1.218，故保留两条。RAM manager 可提前接收一笔后续
整行 Get，但仍在 64 位 D 通道上逐 beat 返回；冷流尚不能持续四发射，
也没有 FPGA 时序证据。
冷流复现命令：`make gsim-instruction-ipc ISSUE_WIDTH=4 INSTRUCTION_CACHE_LINES=16 INSTRUCTION_IPC_OPTIONS=--long-body`。
这些用例仅覆盖独立整数加法吞吐与 RAM 取指，不能代表 CoreMark、Linux 或实际 Fmax。
