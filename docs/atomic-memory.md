# 原子访存：共享执行端与CPU接入

独立AtomicMemory IP现已通过AtomicDataMemory适配器接入CPU译码、LSU及机器平台共享RAM。
MachinePlatform默认开启atomicMemory；独立裸核默认关闭，开启者必须连接原子执行端，不能把原子请求当普通读写。
目前验证单hart RAM中的W/D LR/SC与九种AMO，所有aq/rl组合采取保守串行排序；不宣称完整RVA23、多hart一致性或全套A合规。
2026-09-30 核对：机器 CSR 的 `misa` 已不是零；当前 Board40 返回 `0x8000000000141105`
（RV64 I/M/A/C/S/U），但这仍不是完整 A/RVA23 一致性认证。
当前原子 RAM 范围由平台传入，Board40 为 `0x80200000` 起 1 MiB；
本文 DMA/共享访存测试属于各自的测试配置，不代表 Board40 DMA 可用——
板级 DMA 自身仍检查旧 RAM 地址，限制见 [datasheet 勘误](soc-datasheet.md)。
当前软件发现和特权合同见 [OS 适配指南](os-software-porting.md)。
依据A 2.1：https://docs.riscv.org/reference/isa/v20240411/unpriv/a-st-ext.html 。

## 实现前合同

IP不依赖core，包含一个普通/原子请求端口、一条DMA普通访存端口和一个有序下游内存端口。
普通请求采用64位对齐beat的数据/掩码约定，地址为有效字节地址；原子请求data为右对齐rs2操作数。
原子返回LR/AMO旧值（W符号扩展）或SC成功0/失败1；error独立表示访问错误，不冒充SC保留失败。
原子操作码采用funct5数值：LR2、SC3、swap1、add0、xor4、or8、and12、min16、max20、minu24、maxu28。
仅支持自然对齐W/D，原子访问限配置RAM范围，mask必须匹配完整word/doubleword；非法操作/范围/宽度不发出下游请求。

普通流轮询仲裁、8项有序归属标签，最多每拍一项请求/响应，锁住被背压的请求；目标不降低原普通流的每拍一项吞吐。
原子操作采用单项串行槽：轮到原子时先停止接受新普通请求，等待全部已接受普通响应排空，再开始。
LR需一次读，SC成功需一次写，SC保留失败不访问内存，AMO需读+计算+写；整段锁住DMA和普通流。
等待原子响应被接受才解除锁。背压可无限延长锁，首版不承诺最坏延迟；调用方必须最终接收响应。
下游可同拍返回响应，但必须按请求顺序返回，且被背压的响应必须保持有效与数据稳定。
下游request.ready不得组合依赖response.ready，避免通过归属标签旁路形成组合环；错误写必须无副作用。AMO读错误不发写，写错误返回error。
原子开始前旧事务排空是内存边界保证，不能替代CPU对尚未发出写缓冲、精确异常和MMIO的排序。

只有一个LR保留，固定64字节对齐粒度，SC要求与最近成功LR相同地址和宽度。
任一主设备被接受的同粒度普通写、同粒度AMO、任一SC、下一条LR及显式clearReservation使旧保留失效。
失败写也可保守清保留；不同粒度写和普通读不清除。clearReservation与LR完成同拍时清除优先，
在LR在途期间发生清除也会禁止该LR完成时重建保留。
清除若在SC被接受后发生，不撤销已获授权的SC。所有相关写入必须经过IP；旁路写/缓存命中写需未来集成补齐失效通知。
这是单hart+DMA边界，尚未验证多hart缓存一致性、Za64rs/Ziccrse进展要求或SMP软件。

## FPGA路径与验收

AMO旧值读取、运算结果和最终响应均有寄存器边界；64位加法/比较位于读响应到写数据寄存器路径。
普通流含轮询选择和信用检查，原子不增加普通请求的寄存级。参数范围与64字节保留集合独立检查。
面积、BRAM推断和Fmax待Vivado；串行AMO是正确性基线，不宣称最优性能。
测试必须覆盖全部W/D操作、符号/溢出、DMA竞争、LR/SC成功/失败/替换/失效、显式清除、非法请求、
零延迟/长延迟响应、读/写错误、请求/响应背压、普通流吞吐与公平性，并用独立软件内存计算结果。

## 8 KiB RAM 参数与上半区验证（2026-09-24）

机器平台把配置的 `ramBytes` 传给原子仲裁器；8 KiB 平台的原子合法范围现在与 RAM、
LSU 和可选缓存的范围一致。`make gsim-atomic-memory8-test` 用独立字节内存模型检查
上半区 AMO、LR/SC、DMA 写失效、末尾高半字 W 操作及越界拒绝，并在 0/1/12 拍
下游响应和随机背压下验证数据、请求顺序和最终内存；负向结果篡改被检出。
默认 4 KiB `make gsim-atomic-test` 也复测通过，原有事务与延迟计数保持不变。

`make gsim-atomic8-platform-test` 用实际 CPU→原子边界→TileLink RAM 跑一段
RV64IMAC 程序：上半区 AMO.D 旧值 41、LR.D 值 82、SC.D 成功 0，末尾高半字
AMO.W 旧值 41、读回 82；越过 `0x80012000` 的 AMO 在原 PC 报 cause 7、
`tval=0x80012000`，没有发出第 9 笔 CPU 内存请求。19 条退休、8 笔有效请求、
72 周期，独立寄存器预期与故障地址检查通过。这验证单 hart 的参数范围接线，
不扩展为多 hart 一致性或完整 A 合规声明。


## 第一阶段IP定向结果（2026-09-22）

独立C++字节内存模型验证实际写入、每次返回以及原子下游读写序列；人工篡改结果必须被检出。
覆盖W低/高半字及D、全部九种AMO、LR/SC成功和失败、CPU/DMA写失效、地址/宽度不匹配、
保留替换、LR在途/完成清除、SC接受后清除、读写错误、非法请求及随机竞争/背压。
同拍响应另用强制请求停顿后同拍返回的模型验证，返回若未被接受必须缓存，不能撤回。

| 下游响应模式 | 原子事务 | SC成功/失败 | 普通事务 | 最大下游在途 |
| --- | ---: | ---: | ---: | ---: |
| 1拍，随机背压 | 1766 | 6 / 167 | 3227 | 5 |
| 12拍，随机背压 | 660 | 6 / 53 | 1215 | 8 |
| 同拍，随机背压 | 1856 | 6 / 168 | 3084 | 1 |

1拍普通流连续501拍每拍接受一笔；12拍模式验证8笔在途。它是IP端口吞吐，不是CPU双访存发射。
同拍模式分别在两个延迟参数下复跑；该模式覆盖请求/响应同拍处理，参数不影响返回时间，不能当作不同延迟性能样本。

无竞争、无背压时，从请求接受到响应接受（包含首尾拍）：

| 下游延迟 | LR | SC成功 | SC失败 | AMO |
| --- | ---: | ---: | ---: | ---: |
| 1拍 | 4 | 4 | 2 | 6 |
| 12拍 | 15 | 15 | 2 | 28 |

这些延迟是串行执行基线；下一项原子操作须等前一项响应接受后才可进入。
`make gsim-atomic-test`包含上述行为和负向注入；`make atomic-rtl`导出独立IP。
定向日志：`build/gsim/atomic-dev.log`。该阶段尚未包含整核译码/LSU/精确异常、aq/rl与CPU写缓冲；当前接入结果见下文。

独立RTL已成功导出到`build/ip/atomic/filelist.f`，日志`build/gsim/atomic-rtl-export.log`；未进行Vivado综合或布局布线。

最终`make test`通过31项Scala与完整GSIM/NEMU、16项负向注入；日志`build/gsim/atomic-final.log`。
44条IPC测量及24次平台启动记录与本轮前逐项一致。NEMU回归覆盖现有CPU；新增原子IP使用上述独立内存模型，当时尚非CPU原子指令差分。

## CPU接入合同（第二阶段，实现前）

通过显式atomicMemory参数启用译码；未连接执行端的裸核保持禁用。机器平台连接AtomicDataMemory后默认启用。
22种W/D编码（LR/SC与九种AMO），LR要求rs2=0，aq/rl四种组合均接受；非法宽度/操作仍为非法指令。
原子指令占用普通访存发射的一项预算，仅ROB队首、操作数就绪、LSU与写缓冲全部排空后启动。
任何尚未退休的更老原子指令都阻止年轻访存；不投机执行、不可取消，保护持续到退休/精确异常。
所有aq/rl组合采用同一更强串行排序，涵盖当前单hart有序内存与MMIO；不因此宣称多hart一致性或完整RVA23。
DataPort增加atomic/atomicOp：普通请求保持beat数据，原子rs2右对齐，原子响应直接为架构结果，不能再次移位或符号扩展。
原子不得进入提前确认的写缓冲或普通load转发。IP在共享RAM边界与DMA仲裁，陷阱入口清除LR保留。
LSU先检查自然对齐，再检查完整RAM范围：LR报告load misaligned/access fault，SC/AMO报告store/AMO对应异常，tval为地址。
错误原子请求不发送普通MMIO事务；下游读/写错误精确回到原子指令，年轻store无副作用。
独立集成测试须覆盖两种ROB配置、全部操作/aqrl、rd=x0、依赖、普通写/原子/读排序、错误路径、DMA保留失效与请求锁定。
普通流吞吐目标不变；串行原子的整核周期代价单列，频率/资源仍待Vivado。


## 第二阶段定向验收（2026-09-23）

`make gsim-atomic-core-test`在ROB8/PRF36与ROB32/PRF64各运行80个程序、1656条提交、356次原子请求。
每组覆盖3072个funct5/funct3/aqrl/rs2译码组合、52次精确错误停止、4次外部DMA写及LR在途清除。
包括全部九种AMO与W/D、W高半字、rd=x0、rs2/地址依赖、旧写排空、年轻load顺序、错路径AMO/SC、
非法编码、错位、MMIO地址拒绝及LR/AMO/SC下游读写错误。结果篡改负向检查必须失败。

无外部干扰的AMO、LR/SC和错路径程序使用现有固定版本NEMU逐提交/最终内存差分；
CPU写导致保留失效、DMA干扰、显式清除与故障注入使用独立模型，不强迫NEMU的保留粒度/设备行为与DUT相同。
NEMU从不因差异重同步。独立CPU模型在原子请求发生时检查它是下一条退休指令，旧普通内存已排空，并验证原子结果及最终字节内存。

同步MachinePlatform增加独立原子/DMA启动镜像：普通store→AMO→load、W高半字、LR/SC、
三个原子错位/访问错误经mtvec处理并MRET，DMA拷贝期间循环执行AMO，DMA/中断之后SC失败。
两组配置各三种提交背压，六次启动通过；每次DMA为1KiB/256笔总线事务，且CPU/DMA均有进展。
该平台使用独立系统模型，不能把设备测试说成NEMU覆盖。

| 核配置 | 原子启动无背压周期 | 随机背压种子17 | 随机背压种子8191 |
| --- | ---: | ---: | ---: |
| ROB8/PRF36 | 6548 | 7472 | 7454 |
| ROB32/PRF64 | 6494 | 7402 | 7409 |

指令级压力程序含72次AMO及关联store/load/ALU，共362条退休指令；默认配置无背压时，
下游1拍/12拍分别为1372/4468拍。该程序包含依赖、队首授权和写缓冲排空，不能把总周期当成单次AMO延迟。
原子DMA启动负载中拷贝活跃402～437拍；与原普通流启动镜像负载不同，不报告通用加速/退化百分比。
本阶段以正确性为基线，尚未优化不带aq/rl指令的并行性，未测布局布线频率或资源。

硬件新增原子标识、年龄阻挡和LSU结果选择路径；普通流每拍一笔的共享边界不增加流水级，
但组合延迟需Vivado评估，GSIM周期不代表Fmax。后续缓存若绕过此边界，必须补保留失效及一致性协议。
日志：`build/gsim/atomic-core-dev.log`、`build/gsim/atomic-platform-dev.log`。

## 2026-10-01：板级普通响应 owner 切分

`AtomicMemory` 和 `AtomicDataMemory` 新增 `registerResponseOwners`，通用 IP 默认
`false`，保留原有空队列同拍直通。板级 `MachinePlatform.registerPhysicalResponseOwners`
同时配置原子/DMA普通响应队列与物理系统仲裁队列；要求 translation service +
ordered TileLink memory，`BoardSocTop` 启用。不得只切其中一处：实际 SoC 报告证实
另一处空 owner 直通会保留 request grant→response valid→LSU 的长反馈路径。

仅普通 CPU/DMA 请求的 owner metadata 改为非 flow；仍为8项、每拍最多一笔，
数据通路、LR/SC/AMO状态机、保留失效和原子排空规则不变。
至少一拍返回的下游不增加响应拍数；零拍下游必须保持响应直到 ready，普通响应
最早下一拍接受。两级 owner 同时登记请求，不是串联两个数据流水级。

定向命令：`make gsim-atomic-registered-owners-test`。同源码原始/注册模式均通过
独立字节内存、随机背压、CPU/DMA公平性、零拍返回和负向错误注入（ASan/UBSan）。
1拍/12拍模型的事务数和总周期逐项相同；LR/SC成功/SC失败/AMO仍为
4/4/2/6和15/15/2/28拍。零拍普通响应有预期新增等待，因此该模式随机轨迹不相同，
不宣称对任意下游均零周期成本。无全量 GSIM 或板卡频率资格声明。


第二阶段最终`make test`通过32项Scala、完整GSIM/NEMU与17项负向注入。
新增两种配置各80个原子集成程序及六次原子/DMA平台启动；原44条IPC测量字段与24次启动记录逐项不变。
对照快照`build/gsim/ipc-before-atomic-core.json`，完整日志`build/gsim/atomic-core-final.log`。
`make machine-platform-rtl`导出通过，`build/ip/machine-platform/filelist.f`包含AtomicMemory与AtomicDataMemory；
导出日志`build/gsim/atomic-core-rtl.log`，未运行Vivado。
