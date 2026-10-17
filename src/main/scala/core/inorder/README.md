# Orbital-I1 源码边界

独立参数化单发射顺序核；与 core/ooo/ 的 Orbital-A1、legacy/hardware/ 的旧核分开。
保留类名与包名，不为目录美观改变已验证的源码和展开结果。

- FiveStageConfig、FiveStageCore：ISA/流水配置、执行与精确提交。
- FiveStageAddressTranslation、FiveStagePmp、FiveStageMachineState：特权级、权限、翻译、异常/中断。
- FiveStageBranchPredictor、FiveStageFetchAligner、SynchronousRegisterFile：前端和 RAM 寄存器堆。
- I1FloatingPoint*：可选 F/D，复用固定 HardFloat 算术源，不改写上游。
- I1Coherent*、I1TileLink*：TL-C 私有缓存/Home、顺序返回、DDR 桥。
- FiveStageSoc、I1*FpgaShell：独立 SoC 与板级边界。
- I1*Jtag*、I1BscanRamTransport：共享 USER2 下载。

构建模块 OrbitalI1 显式复用必要 ISA/总线/IP/桥辅助文件，不实例化 Orbital-A1 乱序 CPU；
默认 IonSoC 不因此自动替换 CPU。开关支持范围以配置约束与定向验收为准；
默认关闭的实验选项不是板级默认值。

详见 [架构与验收记录](../../../../../docs/orbital-i1.md)。
