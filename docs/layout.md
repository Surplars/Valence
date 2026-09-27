# 目录与依赖边界

```text
Valence/
├── src/
│   ├── main/scala/core/ooo/   新乱序核
│   ├── main/scala/ip/         独立可复用 IP（总线事务接口、IMSIC）
│   ├── main/scala/isa/        公共 ISA 编码与架构常量
│   ├── main/scala/core/pipeline/decode/  旧顺序核的译码控制适配
│   ├── main/scala/…          旧核心及现有 SoC 模块（复用前需独立审查）
│   └── test/scala/           活动 Scala 检查与 GSIM 模型生成入口
├── simulator/gsim/
│   ├── run.py               仿真流程入口
│   ├── reference.py         独立 NEMU 参考构建
│   ├── targets.mk           Make 目标
│   ├── harness/             C++ 驱动和独立验证模型
│   ├── payloads/            当前新核可运行的汇编程序与链接脚本
│   └── config/              GSIM/NEMU 版本锁与参考配置
├── docs/                    当前设计与开发文档
├── legacy/
│   ├── tests/scala/         退役 ChiselSim 用例，退出默认测试发现
│   ├── simulator/           历史 payload 与 DiffTest 配置
│   └── docs/                旧 SoC 架构、仿真与问题记录
├── NEMU/                    固定版本的参考模型子模块
├── difftest/                现有 Scala 构建依赖的上游子模块
├── riscv-tests/             上游测试资源子模块
├── build/gsim/              生成模型、程序、日志及隔离 NEMU 构建（忽略）
├── simulator/build/         已有工具链缓存与旧生成产物（忽略）
└── out/                     Mill 缓存（忽略）
```

## 放置规则

- 新 IP 放 `src/main/scala/ip`，不依赖 `soc.core` 或全局配置；核心/平台通过明确接口组装。见 [模块化合同](modular-soc.md)。
- 新核硬件放 `src/main/scala/core/ooo`，保持 Scala 包名及标准源目录，不把历史测试放回活动目录。
- `soc.isa` 不依赖核心或平台配置；标准编码可共享，核心控制表留在各自核心包。见 [复用边界](isa-reuse.md)。
- GSIM C++ 验证、程序、配置分别放 `harness`、`payloads`、`config`。`run.py` 统一解析相对路径。
- 当前设计文档放 `docs`，旧实现和退役工具的记录放 `legacy/docs`。
- `legacy` 中的源码用于审查和迁移，不能当作当前新核的正确性依据。退役的硬件测试没有自动执行入口。
- `make payload` 仍可组装历史程序；这不表示当前新核能执行它。`make sim-verilog` 仅导出历史 SoC RTL。
- 顶层 `NEMU`、`difftest`、`riscv-tests` 是 Git 子模块，不是项目自产源码。保留路径以维护子模块元数据和现有构建依赖。
- 旧硬件仍有相互依赖，继续位于标准源码树。目录整理不等于已经完成旧平台与新核的构建模块解耦。
- 退役的本地 firmware 检出、Verilator harness、辅助 RTL、rootfs 工具和 OpenOCD 配置已移除；历史文档提到的旧路径不再是可执行入口。
- GSIM 源码缓存位于 `simulator/build/gsim-src`，运行产物位于 `build/gsim`；它们是当前验证流程的生成文件。

## 验证入口

`make test-scala` 运行配置/展开检查；`make gsim-smoke` 检查基础仿真链路。
开发按改动范围选 `make gsim-backend-test`、`make gsim-integer-test` 或 `make gsim-core-test`；
`make test` / `make regress` 执行活动 Scala 检查与完整 GSIM 回归。所有入口均不调用 Verilator。
