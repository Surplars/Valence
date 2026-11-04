# I1 H/V 接入进展（2026-11-04）

用户已授权与顺序核性能优化同步推进 H/V；V 扩展复用用户提供的现成 VPU，不开发新的向量执行数据通路。用户已选择提供仓库或本地路径，具体来源尚待给出。开发/GSIM 继续在 `/home/openion/Valence-InOrder`，Windows 交付与 Vivado 在 `E:/VM/Share/Valence-rtl/Valence-InOrder`。

## 已完成的 H 基础组件

`I1HypervisorDecode` 独立识别 H 1.0 新增的 HLV/HLVX/HSV、HFENCE.VVMA/GVMA；核对 U/HS/M、VS/VU、HU/TVM 权限，区分 illegal 与 virtual-instruction trap。组合逻辑，无 owner、寄存器、执行副作用或新增流水级；接口吞吐 II=1。32 位保留 HLVX.WU，拒绝 RV64 专属编码。未知编码交由 CPU 基础译码处理。

参考 [RISC-V 20240411 H 1.0](https://docs.riscv.org/reference/isa/v20240411/priv/hypervisor.html)。编码事实独立核对官方 [rv_h](https://github.com/riscv/riscv-opcodes/blob/master/extensions/rv_h)、[rv64_h](https://github.com/riscv/riscv-opcodes/blob/master/extensions/rv64_h)；Git blob SHA1 分别为 `84a361d4090eabff26cba6a96c9e99e922ec9a06` 和 `75589e1ab2965e1829c27e91d82a0c8c57121e5a`，记录在 `simulator/gsim/config/hypervisor-h10-decode.json`。

GSIM + ASAN/UBSAN：RV32、RV64 各 913800 检查，共 1827600；完整寄存器组合、固定编码位翻转、30000 个随机指令和五种架构模式，HU/TVM 各两种取值。两档错误预期异常码均被独立 mask/value oracle 拒绝。证据 `build/i1-hv-foundation-20261104-r1/decode/receipt.json` 绑定源码、模型、可执行文件、正负日志和命令。未把 DUT 的位域函数或控制表作为软件 oracle。

```sh
source /home/openion/Valence-InOrder/.local-dev/env.sh
mill -i OrbitalI1.test.compile
python3 simulator/gsim/inorder/hypervisor_decode_assessment.py --output build/FRESH_H_DECODE
```

## 后续 CPU 接入顺序

| 工作 | 当前状态 | 验证重点 |
|---|---|---|
| H 新指令编码与权限 | 独立硬件 GSIM 通过；尚未接入 CPU | 非法编码、权限与异常分类 |
| H/VS CSR、V 模式、trap/xRET | 待接入现有 MachineState | CSR 权限、委托、中断、精确恢复 |
| VS/G 两阶段地址转换 | 待扩展现有 Sv39/MMU | 上下文身份、页故障、失效、PMP/PMA |
| VPU 实体适配 | 待用户提供现成 VPU 来源 | 实际端口、版本、VLEN/ELEN、目标 V 子集 |
| V CPU 侧 CSR/串行入口 | 已审查既有预留契约，待实际接口适配 | scalar/FP 交互、vstart、精确前缀与退休 |
| V 元素内存接入 | 待实际 VPU 接口确定 | 翻译、权限、反压、mask、fault restart、drain |

现有 `soc.ip.vector` 仍为 M0 接入契约，只有禁用端点，没有 VPU 实体。后续以提供的真实 VPU 协议为准，不为预留接口另造向量执行器。CPU decode/CSR、标量操作数、内存及精确退休是本项目的适配工作。

当前 CPU 尚未宣告 H/V，也未完成 guest OS、向量程序、H/V 全指令合规或其面积/时序评估。当前 300MHz 实现输入仍是已冻结的 RV64IMAFDC 单发射 CPU；H 组件的独立通过不能替代 CPU 接入验证。完成实际接入后单独列出 H/V 的 LUT/FF/BRAM/DSP、频率与程序指标。
