# 目录与依赖边界

2026-10-07 已将旧顺序核从活动源码树移至独立历史模块。源码路径不是 Scala 包名；
迁移保留文件内容及包名，例如公共 ISA 仍属于 `soc.isa`，历史顶层仍是 `soc.IonSoC`。
软件开发先查 [datasheet](soc-datasheet.md)、[寄存器](soc-registers.md) 和 [OS 移植指南](os-software-porting.md)。

```text
Valence/
├── build.mill               唯一受支持的 Scala 构建入口
├── src/
│   ├── main/scala/core/ooo/  Orbital-A1、VL100 组装与核心侧适配
│   ├── main/scala/ip/        可复用总线、时钟、UART、DMA、GMAC 等 IP
│   ├── main/scala/isa/       公共 ISA 编码/架构常量
│   ├── main/scala/bus/tilelink/TileLink.scala  公共 TL 类型
│   └── test/scala/           当前配置/展开检查与 GSIM 模型入口
├── third_party/berkeley-hardfloat/  固定来源的浮点算术模块与许可
├── simulator/gsim/
│   ├── run.py, targets.mk    GSIM 流程与 Make 入口
│   ├── harness/             独立 C++ 检查/参考及模型驱动
│   ├── payloads/            当前验证程序、链接脚本
│   └── config/              工具版本锁及参考模型配置
├── fpga/
│   ├── firmware/            BootROM、下载工具、软件/BSP 构建源码
│   ├── zu15eg/              板级 RTL、XDC、集成/签核脚本及说明
│   └── *.tcl, *.py, *.bat   可复用模块时序、CDC 和审计工具
├── docs/                    当前合同及按日期保留的研究/验收记录
├── legacy/
│   ├── hardware/src/main/scala/  旧核、旧配置/外设/缓存/SoC
│   ├── hardware/src/test/scala/  旧配置/译码展开检查、历史 RTL 入口
│   ├── tests/scala/         退役 ChiselSim 用例，未启用
│   ├── simulator/           历史汇编程序及两份 NEMU 配置
│   └── docs/                旧设计及故障记录
├── NEMU/, difftest/, riscv-tests/   Git 子模块，保留元数据及版本
├── build/                   可再生模型/固件/RTL/日志，Git 忽略
├── simulator/build/         GSIM/Linux/OpenSBI 等源码和构建缓存，Git 忽略
└── out/                     Mill 增量缓存，Git 忽略
```

## 构建依赖

`IonSoC` 从根目录 `src` 编译当前硬件，依赖 `HardFloatLib`，不依赖旧核或 Scala `DifftestLib`。
GSIM 的 NEMU 差分流程保留独立来源，不因移除旧 Scala 依赖而移除。
`LegacySoC` 从 `legacy/hardware/src` 编译，依赖 `IonSoC` 中的公共定义以及旧 `DifftestLib`；
方向为历史模块依赖当前公共定义，不存在当前模块反向依赖历史硬件。

| 模块 | 硬件源码 | 测试源码 | 使用范围 |
| --- | ---: | ---: | --- |
| `IonSoC` / `.test` | 146 | 152 | 当前默认构建与定向 GSIM |
| `LegacySoC` / `.test` | 51 | 3 | 显式历史兼容构建/纯展开检查 |

上表是整理当日的快照，不是固定容量或测试用例数。两模块源码集合完全不重叠，
退役 `legacy/tests` 不加入任何模块。
共享定义由依赖复用，不复制源码、建立软链接或维持两份 TileLink/ISA 定义。

## 放置规则

- 新独立 IP 放 `src/main/scala/ip`，通过明确接口连接，不依赖旧全局配置。
- 核心和当前平台放 `core/ooo`；CPU、SoC 组装及适配器暂以类名区分，不为目录美观批量改包名。
- ISA 标准常量放 `isa`，旧核控制表位于 `legacy/hardware/src/main/scala/core/pipeline/decode`。
- 当前 GSIM 驱动、程序、锁定配置分别放 `harness`、`payloads`、`config`。
- 当前板级固件、驱动/设备树模板及下载器保留在 `fpga/firmware`，不是历史资产。
- `docs` 按索引区分当前合同与阶段证据；日期化历史不删除，也不能当成最新签核。
- 编译缓存、rootfs、镜像、DCP、bit、波形、报告不放进源码提交；有用发布证据归档到仓库外。
- 旧顺序核、旧测试和故障记录保留供审查，不能当作 Orbital-A1 的正确性依据。

## 验证入口

当前入口为 `make compile`、`make test-scala`、`make gsim-smoke` 和按改动选择的 GSIM 定向目标。
`make test` / `make regress` 是全量回归，目录整理不默认执行。
历史入口为 `make legacy-compile`、`make legacy-elaboration`、`make legacy-rtl`；
`sim-verilog` 仅是后者的兼容别名，不启动退役仿真器。
生产板级配置、RTL 导出、Vivado 集成和静态签核是不同步骤，见
[ZU15EG](../fpga/zu15eg/README.md) 和 [时序记录](fpga-timing-windows.md)。

## 缓存与归档

本次仅清空根目录 `build`，保留 `simulator/build` 的源码缓存及 `out` 增量编译缓存。
当前 Linux 源码缓存为 `simulator/build/linux`，OpenSBI 为 `simulator/build/opensbi-v1.9`，
GSIM 为 `simulator/build/gsim-src`；过去 `build/gsim/linux-source` 等路径是历史构建快照。
`build.sbt`、`.orig`、已完成的本机恢复作业和未使用旧助手已移出仓库并可从外部归档恢复。
清理明细、校验和恢复约束见 [整理与提交清单](repository-maintenance.md)。
