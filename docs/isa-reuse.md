# 公共 ISA 定义与核心适配

ISA 仍采用 RISC-V。此轮复用标准编码和异常编号，不扩大新核支持范围，也不改变微架构吞吐目标。
新核仍为 38 种整数/控制流编码，组合译码每路每周期接受一条，延迟与执行端口不变；综合时序未验证。

## 依赖方向

```text
soc.isa                         标准编码、扩展标识、CSR/异常编号、压缩展开候选
  ↑                  ↑
core.pipeline.decode            core.ooo.IntegerDecode / IntegerBackend
旧顺序核控制适配                 新乱序核译码与完成接口
```

`soc.isa` 不引用 `soc.core` 或 `soc.config`。ISA 文件中的常量存在，不代表任一核心已经实现对应扩展。
`Extension` 继续保留已有名称与枚举顺序；平台默认 ISAProfiles 仍只描述旧平台，不能套用到新核能力声明。

- `src/main/scala/isa/Instruction.scala` 保留 Common、Extension、Opcode、Funct3/5/6/7。
- `src/main/scala/isa/CSR.scala` 保留 CSR、特权级、异常和中断编号，不包含提交控制。
- `InstrProvider`、`InstrEntry`、`InstrTable` 与 `InstrSet*` 移至 `core/pipeline/decode`，明确属于旧控制适配。
- 新核消费公共 opcode、相关 funct 字段和原因 0/2 常量，仍自行生成 IntegerRequest；ALU/分支内部操作编号不是 ISA 编码，继续由新核维护。
- `Compressed` 已由新核的可选 RV64C 取指路径调用，并经过混合长度固件与 CoreMark 工作负载检查；
  CSRFile、LSU、Cache 和外设没有因本次拆分自动获得复用验收。

## 审查与验证范围

本轮核对新核使用的整数/分支 opcode、funct 字段，依据固定
[20250508 指令编码表](https://docs.riscv.org/reference/isa/v20250508/unpriv/rv-32-64g.html)。
原因 0/2 分别复用原有指令地址未对齐/非法指令常量，并通过已有独立异常用例检查。
新核 JALR 保留 funct3=000 检查，移位仍区分 RV64 的 funct6 与 W 指令的 funct7。

这不是对整个旧 ISA 实现的认证。例如旧 InstrSetI 的 JALR 表项只匹配 opcode；
本次保持该历史适配器原行为，不将它用于新核合法性判断。

验证使用活动 Scala 配置/展开检查、旧译码适配器的纯展开检查及 GSIM 回归。
GSIM C++ 指令匹配/求值表和 NEMU 不从公共 Scala 定义生成，保留独立检查来源。
旧译码展开成功只证明移动后的连接可构建，不证明旧核功能正确。全过程不使用 Verilator。

2026-09-18 验收：`make test` 通过，Scala 14 项全部通过；GSIM smoke、三组账本、两组整数后端、
两组程序差分和故障注入全部通过。每组程序配置检查 136,072 个译码输入和 28,618 条提交，
默认配置的整数流与不跳转分支流各连续 251 周期保持双宽接受/提交。日志为
`build/gsim/isa-reuse-tests.log`。旧控制表除包名、导入和格式外未改变，公共 ISA 源码无核心/配置反向引用。

后续按模块审查压缩展开、TileLink/RAM/外设；CSR 与缓存接入还需分别解决提交副作用和请求并发标识。

## B 扩展边界

RV64 Zba/Zbb/Zbs 的核心控制位于 `core/ooo/IntegerBitDecode.scala` 和 `IntegerBitManip.scala`，
按 B 1.0.0 及官方 riscv-opcodes 审核，不复用旧流水线控制表。`soc.isa` 的依赖方向不变。
C++ 掩码/语义表与 NEMU 独立于 DUT；详见 [RV64B 合同与验证](rv64b.md)。
