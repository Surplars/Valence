# Arcilator Windows 原生试验

Arcilator 属于 CIRCT。上游[Windows 构建说明](https://github.com/llvm/circt/blob/main/docs/GettingStarted.md#windows-notes-on-setting-up-with-ninja)
使用 Visual Studio 的 MSVC、Ninja、CMake 和 Python，**不要求 MSYS2**。
说明针对从源码构建 CIRCT/LLVM；Vivado 的安装不包含这些工具。

在 Linux 项目根目录运行：

```sh
python3 simulator/arcilator/package_windows_smoke.py
```

这一步经 `firtool --ir-hw` 验证现有 Chisel CHIRRTL 可转为 Arcilator 的输入，
生成 `build/arcilator-windows-smoke.zip`。在 Windows 解压 ZIP 后，使用
Visual Studio Developer PowerShell，确保 `firtool`、`arcilator`、`opt`、`llc`、`cl.exe`
和 Python 在 PATH 中。安装 Python 模板依赖后运行：

```powershell
python -m pip install jinja2
.\compile-smoke.ps1
```

脚本编译并运行一个算术、寄存器和同步存储器 smoke 模型。若失败，保留完整输出；
Linux 环境暂未安装 Arcilator，也无法执行 Windows `.exe`，因此该 Windows
阶段仍待实测。它通过后，再将新的后端接入 CPU、SoC 和独立差分测试；
在此之前保留现有 GSIM 验证入口，避免失去已知的正确性基线。
