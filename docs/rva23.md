# RVA23 SoC 架构目标

当前板级合同核对日期：2026-09-30。软件可用范围以[OS/软件移植合同](os-software-porting.md)为准；
本页保留目标 profile、缺口与历史功能验收，不是芯片合规 datasheet。

用户指定新应用 SoC 按 RVA23 实现；目标为 RVA23S64，并覆盖其继承的 RVA23U64 必选能力。
依据 [RVA23 v1.0 正式规范](https://docs.riscv.org/reference/rva23/v1.0/rva23-profiles.html)，
核对日期 2026-09-24。这是目标，不是当前合规声明；当前为 RV64I 子集加 Zicond / M / B、
可选 RV64C 整数路径，以及机器平台接入的单 hart A 路径的双发射开发核。
RVA23 是架构 profile，不规定发射宽度、总线、外设或频率；2/4/6 发射应用核沿用同一架构目标。
MCU 产品的 ISA 另行定义，不把应用级 profile 强加给 MCU。

## 必选项与差距

以下清单按正式规范分组；组合扩展的子项、版本、PMA 和执行环境条件必须一起验收，
不能只检查指令名或 misa。没有列为已验证的项目均不对软件宣称支持。

| 范围 | 必选能力 | 当前状态 / 验收方向 |
| --- | --- | --- |
| 基础 | RV64I，小端 | 整数基准 49 种编码；机器核另接 ECALL/EBREAK、同步陷阱与完整排空式 FENCE；仍非完整 RV64I 合规验收 |
| 标量计算 | M、B、Zicond | Zicond / M / B（Zba/Zbb/Zbs）已通过 GSIM/NEMU；不代表整个 profile 已合规 |
| 原子 | A、Za64rs、Ziccrse、Ziccamoa、Zawrs | 机器平台已接W/D LR/SC及AMO，aq/rl采用强串行排序；多hart一致性、完整进展/合规及Zawrs等仍待验证 |
| 浮点 | F、D、Zfhmin、Zfa | 基础 F/D 可配置功能候选已接入（2026-10-03，默认关闭），完整状态见 OoO 阶段记录；Linux FP/新 FPGA 签核、Zfhmin/Zfa 待完成，不代表 profile 合规 |
| 压缩 / MOP | C、Zcb、Zimop、Zcmop | 可选 RV64C 整数路径已支持混合 16/32 位取指、跨包/跨页指令及主要整数压缩编码，并运行 CoreMark；仍缺完整编码穷尽与合规验收，Zcb/Zimop/Zcmop 待实现 |
| 向量 | V、Zvfhmin、Zvbb、Zvkt | 必须实现；不是可选性能增强，需向量状态及精确恢复设计 |
| CSR / 计数 | Zicsr、Zicntr、Zihpm | 机器核已接六种 Zicsr、有限 M/S CSR 和 time；cycle/instret/HPM 不存在，不能声明 Zicntr/Zihpm |
| 内存 / 缓存 | Ziccif、Zicclsm、Zic64b、Zicbom、Zicbop、Zicboz | 已有 64 字节行写回 D-cache 与 RAM I-cache；CMO/非对齐及完整 PMA 仍待实现，板级为 ROM+可执行 RAM |
| 提示 / 时序 | Zihintpause、Zihintntl、Zkt | 未验收；不得用忽略所有保留指令替代精确识别 |
| 用户指针掩码 | Supm | 待实现及执行环境支持 |
| 取指同步 | Zifencei | 机器核已实现队首排空、前端及整行 I-cache 失效与重取；定向 GSIM 已验证脏 D-cache 写回后执行 RAM 代码，尚未完成多 hart 软件同步与合规验收 |
| 特权基础 | Ss1p13、Svbare、Sstvecd、Sstvala、Sscounterenw、Ssu64xl | 机器平台已接16条目PMP和MPRV，机器核已接 MRET/SRET、同步异常委托、少量 S CSR、M/S 外部中断、SSI 及 STI；完整 M/S/U 特权语义与 VS 中断仍待补 |
| 地址转换 | Sv39、Svade、Ssccptr、Svpbmt、Svinval、Svnapot | 参数化 Sv39/Sv48/Sv57 遍历、双路 TLB、SoC TileLink 页表读取及机器核 satp/SFENCE 全局失效已通过 GSIM；可选 I/D 译址、MPRV=S 数据访问和 S-mode 跨页取指故障已有固件验证；完整 PMA/PBMT、吞吐与扩展合规仍待实现，不能宣称虚拟内存已合规，见[虚拟内存合同](virtual-memory.md) |
| 定时 / 计数过滤 | Sstc、Sscofpmf | 已接机器 mtime/mtimecmp、MTIP 及单 hart RV64 的 Sstc M/S 路径；Sscofpmf、VS 定时及完整合规验证仍待完成 |
| 监督指针掩码 | Ssnpm | 待实现 |
| 虚拟化 | Sha | 待实现；包含 H、Ssstateen、Shcounterenw、Shvstvala、Shtvala、Shvstvecd、Shvsatpa、Shgatpa |

正式规范的可选项不自动纳入首个合规目标。Sv48/Sv57、额外密码学、BF16 等须另立需求。
支持向量和虚拟化不能替代其余细项；通过少数差分程序也不能替代 profile 合规验收。

## 实施顺序与 FPGA 约束

1. 标量执行与前端：Zicond、M、B 和可选 C 整数路径已接入；继续补完整 RV64I/C 验收及 Zcb/MOP。
2. 提交与特权：CSR、精确陷阱、M/S/U 权限、计数与定时中断；原子和内存排序同步推进。
3. 可写主存与缓存：64 字节块、PMA、非对齐访问、CMO、FENCE.I；Sv39/TLB/PTW 及必选分页能力。
4. 浮点及向量：独立规划寄存器状态、多周期执行端口和提交；先模块验证，再核级及系统软件验证。
5. H/Sha、指针掩码及其执行环境，最后完成全部必选项和软件发现接口的联合验收。

上述是开发依赖次序，非删减标准。FPGA 执行单元可按面积预算复用、分周期实现，
但不能通过省略 V/H/F/D 等能力宣称符合 RVA23。目标器件已定为 XCZU15EG，
当前 BoardSocTop 配置 128 KiB BRAM ROM、1 MiB UltraRAM 和 40 MHz 单时钟目标；
4 KiB RAM 裸核只是保留的开发配置。资源与频率结论必须对应具体 RTL 和 Vivado 报告，
见 [SoC datasheet](soc-datasheet.md)。

## 本轮 Zicond 实现合同

依据 [Zicond 1.0.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/zicond.html)。
czero.eqz 在 rs2 为零时写零，否则写 rs1；czero.nez 的条件相反。操作宽度 XLEN=64，
不存在本轮支持的 W 变体。两源均保留重命名依赖，rd=x0 丢弃写回，错误路径结果按已有 ROB token 撤销。

复用每路 IntegerAlu，无新队列和端口，每路每拍至多一条，依赖者按已有写回后下一拍唤醒。
零检测与数据选择为组合逻辑，不因操作数值插入不同周期数；不据此声明整个 Zkt 已通过。
与其他整数操作共享两条发射预算；关键路径、资源及 Fmax 尚待综合。

验收要求：全 funct/opcode 合法性扫描、rs1/rs2/rd 别名和 x0、64 位高位条件、相关/独立流、
提交背压与恢复、独立软件语义及 NEMU 逐条比较；非法 W/邻近 funct 编码仍须拒绝。
NEMU 只在独立参考配置启用 Zicond，保留固定上游版本与原 ABI；不改变厂商参考源。


### Zicond 定向验收记录

`make gsim-integer-test gsim-core-test` 通过，两组 ROB8/PRF36、ROB32/PRF64 各运行 79 个程序，
66,238 条正常提交及 136,072 个译码输入。新增五个 Zicond 程序：128 组 rd/rs1/rs2 别名组合
分别无背压与随机背压执行，512 条独立流，以及两个种子合计 4,096 条混合随机指令。
默认配置新增 251 个持续双宽检查周期；小 PRF 配置仅作功能/背压检查，不宣称持续双宽。
后端算术边界集及随机恢复也覆盖新操作。原理想供指 IPC 测量不变。
定向日志：`build/gsim/zicond-focused.log`。仅这一扩展已接入，完整 RV64I 和 RVA23 合规仍未完成。

最终 `make test` 通过 Scala 19 项、完整 GSIM/NEMU 回归和负向注入。
同步 ROM/RAM C 程序仍为 1,310 条 / 1,529 周期（无提交背压）。
日志：`build/gsim/zicond-final.log`。

RV64M 的实现、恢复合同与性能记录见 [乘除执行单元](rv64m.md)。

## B 位操作实现

40 条 RV64 Zba/Zbb/Zbs 编码已接入每路整数 ALU，默认仍为双发射。
译码、执行、NEMU 配置、边界/随机/恢复覆盖与 IPC 记录见 [RV64B](rv64b.md)。
此 B 扩展里程碑后的机器配置已接 CSR、精确陷阱及 I/D 分页；裸核仍可保留有序停止模式。
它们的行为边界应分别读取 [机器核](machine-core.md) 与[软件移植合同](os-software-porting.md)。

## 中断平台选择

应用 SoC 选择 AIA（APLIC + IMSIC），并保留独立 PLIC 兼容平台路线。这是本项目平台选择，
不是把完整 AIA 控制器组合表述为 RVA23 profile 的强制平台布局。IMSIC IP 的实现和整核连接状态见
[模块化 SoC](modular-soc.md)。guest 文件不替代 H/Sha、委托、虚拟中断注入及精确陷阱语义的后续实现。
