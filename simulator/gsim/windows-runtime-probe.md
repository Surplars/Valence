# Windows 原生运行 GSIM 生成模型：第一阶段验证

此 ZIP 用于验证 **GSIM 生成的 C++ 模型** 能否编译成 Windows `.exe` 并运行；
它不包含 GSIM 的 FIRRTL 编译器，也不运行 Linux/NEMU 差分测试。

在 Linux 项目目录运行：

```sh
make gsim-smoke
python3 simulator/gsim/package_windows_runtime_probe.py
```

把 `build/gsim-windows-runtime-probe.zip` 复制到 Windows 并解压。Windows 需要
Clang 19+ 和配套 C++ 标准库；建议从 **MSYS2 CLANG64** 终端运行：

```sh
pacman -S mingw-w64-clang-x86_64-clang mingw-w64-clang-x86_64-libc++
cmd //c run_windows_runtime_probe.bat
```

脚本运行小规模存储器/算术 smoke 检查。
出现 `Windows native GSIM-generated model runtime probe passed.` 才表示这一步通过。
若失败，请保留完整编译器输出；不能仅凭编译通过认定仿真语义正确。

这一步通过后，完整 Windows 原生流程仍需移植 GSIM 工具自身的 POSIX 文件映射、
线程亲和性、栈回溯和构建脚本。NEMU 的 Linux `.so` 无法直接在 Windows 加载，
交互 UART 还需 Windows 控制台输入适配。当前 Linux GSIM 主流程不受本试验影响。
