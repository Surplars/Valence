# CPU 数据口到 APLIC 的映射合同

本阶段新增 CoreRegisterRouter 和 MappedMachineCore。路由器属于核心数据口的协议适配层，
独立 APLIC 保持 RegisterPort，不依赖核心。旧 WiredMachineCore 保留外部配置口用于独立组合验收。

两个路由器分别按16KiB APLIC 窗口分流：M 根域默认0x0c000000，S 子域
默认0x0c004000；其他地址透传到外部 DataPort。
CPU 的64位 beat 内数据/字节掩码按地址低3位右移后交给寄存器端口；读响应按原偏移左移回对应字节通道。
请求的大小和完整字节掩码由 APLIC 检查，错误响应转换为原 DataResponse.error，让核心产生精确访问异常。
不拆分64位访问，不把窄写扩成32位写，不吞掉错误。APLIC 地址必须与可投机/缓冲写的 RAM 区域分离。

最多8项在途事务；每项记录目标和字节偏移，两端响应必须各自有序。统一按 CPU 发出顺序返回，
快 MMIO 响应不能越过慢 RAM 响应。标签 FIFO 注册、ready 只看信用；请求路径不增加流水级，
响应最早下一拍，同一目标或交替目标均以持续 II=1 为目标。信用耗尽时允许恢复一拍气泡。
两端必须在 response.ready=0 时保持响应，包括同拍返回的目标；无事务ID、重排或自动重试。
路由比较/字节移位到端口、响应选择到 LSU 是需 Vivado 检查的组合路径；频率与面积未实测。

MappedMachineCore 将 CPU 数据口连接 M/S 两域 APLIC；两个 MSI 主端通过保序仲裁接 IMSIC。
MachinePlatform 已连接 UART source3，固件可将其委托到 S 域。外部仍需提供指令、
普通存储器和同步中断线；设备树、DDR 和 VS 域尚未完成。

## 验收入口与范围

- `make gsim-router-test`：独立协议适配、响应保序与信用检查。
- `make gsim-mapped-machine-test`：上述路由检查加 ROB8/PRF36、ROB32/PRF64 的程序配置中断测试。
- `make mapped-machine-rtl`：导出 `build/ip/mapped-machine/filelist.f` 列出的独立顶层与依赖。
- `make test`：Scala 检查及全部 GSIM 回归。

定向路由测试通过15,234项事务，最大在途8项，交替目标连续282拍每拍收单；覆盖随机请求/
响应背压、地址窗口边界、八个字节偏移、数据/掩码/大小透传、快寄存器响应被慢 RAM 阻挡、
错误响应透传和保序数据错误注入。独立软件队列按发出顺序核对响应，不读取 DUT 内部标签。

两种机器核配置各通过3个程序（3种供指/退休/存储器背压种子）、1,074条退休、9次同步访问异常、
3次外部中断。程序以 SW 初始化 sourcecfg/target/setienum/domaincfg，以 LW/LWU 读回，包括地址
偏移4的寄存器和符号扩展；错误路径 SW 不得关闭中断，LB/LD/SB 访问被拒绝，RAM store/load 仍正常。
随后由程序配置 IMSIC CSR 和 CPU 使能；测试台仅注入一拍源3中断线。处理程序读取并屏蔽 APLIC、
claim IMSIC，MRET 后继续执行。对这些 MMIO/AIA 事件使用独立软件状态模型，未声称 NEMU 外设差分；
原有标准指令/CSR 的 NEMU 验收保留。MMIO 返回值篡改被测试拒绝。

日志 `build/gsim/mapped-focused.log`；RTL 导出通过，日志 `build/gsim/mapped-export.log`。
组合配置新增开销、CPU IPC 和 FPGA 综合/时序尚未测量。

最终 `make test` 通过：26项 Scala 检查、新路由器/两组映射核心、全部旧 GSIM/NEMU 和负向注入。
日志 `build/gsim/mapped-final.log`。原整数配置44条IPC记录与 `build/gsim/ipc-before-mapped.json`
完全一致；这不是新增映射组合配置的性能测量。
