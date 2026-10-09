# Native loader fixture export checkpoint

At combined source `20a3a06d04ccef7ae9d1136f9386f13b993a9dfc`, the new
`debug.JtagRamNativeMain` emitter was compiled and its production loader fixture
was exported successfully. The source-bound 64-cycle / 4 KiB fixture is at
`build/mac-jtag-integration-020edf8/native-loader-fixture`; its four drain-suite
cases are prepared at `build/mac-jtag-integration-020edf8/xsim-loader-drain-prepared`.
The [final binding](../../fpga/next/evidence/mac-jtag-final-binding.json) records
the source, RTL and bench-port checks. The earlier preparation receipt remains
historical. Testbench HDL compilation, xsim/UNISIM runtime, actual netlist
auditing, physical timing and board verification are still NOT RUN.
