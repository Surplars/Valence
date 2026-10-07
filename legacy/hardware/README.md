# 历史硬件兼容模块

本目录保存旧顺序核和旧 SoC，Mill 模块为 `LegacySoC`。
2026-10-07 从根 `src` 按原相对路径迁入 51 个硬件源码和 3 个历史测试/RTL 入口，
内容及 Scala 包名未改。旧顶层 `soc.IonSoC` 不属于当前 VL100。

```bash
make legacy-compile
make legacy-elaboration  # 配置与共享 ISA 译码的 10 项纯展开/参数检查
make legacy-rtl          # sim.TopMain，历史 RTL 导出
```

历史模块依赖当前模块的公共 ISA/TileLink 定义和旧 Scala DiffTest 库。
当前 `IonSoC` 不反向依赖本模块；`legacy/tests` 的退役 ChiselSim 用例不加入这里。
历史核存在已知问题，编译/展开成功不是其功能正确性证明，更不是新核的验证依据。
使用和迁移任何旧实现前，先独立审查并补 GSIM 验证。

公共 ISA 仍放根 `src/main/scala/isa`；旧控制表在本目录 `src/main/scala/core/pipeline/decode`。
目录和归档规则见 [仓库布局](../../docs/layout.md)。
