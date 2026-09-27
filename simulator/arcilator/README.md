# Arcilator Windows 原生试验

Arcilator 属于 CIRCT。上游[Windows 构建说明](https://github.com/llvm/circt/blob/main/docs/GettingStarted.md#windows-notes-on-setting-up-with-ninja)
使用 Visual Studio 的 MSVC、Ninja、CMake 和 Python，**不要求 MSYS2**。
说明针对从源码构建 CIRCT/LLVM；Vivado 的安装不包含这些工具。

在 Linux 项目根目录运行：

```sh
make arcilator-smoke-export
```

这一步导出 Chisel CHIRRTL 到 `build/arcilator/smoke/`。把整个目录复制到
Windows 后，使用 Visual Studio Developer PowerShell，确保 `firtool`、`arcilator`、`opt`、`llc`、`cl.exe`
和 Python 在 PATH 中。`firtool` 与 `arcilator` 应来自同一 CIRCT 构建，以避免
MLIR 版本不匹配。项目中的 `firtool-resolver` 可供 Chisel 导出 SystemVerilog；
本命令仅导出 CHIRRTL，不依赖本机 `firtool`。安装 Python 模板依赖后运行：

```powershell
python -m pip install jinja2
.\compile-smoke.ps1
```

脚本使用 Windows 上的 `firtool --ir-hw` 转换 CHIRRTL，随后编译并运行一个
算术、寄存器和同步存储器 smoke 模型。若失败，保留完整输出；
Linux 环境暂未安装 Arcilator，也无法执行 Windows `.exe`，因此该 Windows
阶段仍待实测。它通过后，再将新的后端接入 CPU、SoC 和独立差分测试；
在此之前保留现有 GSIM 验证入口，避免失去已知的正确性基线。
