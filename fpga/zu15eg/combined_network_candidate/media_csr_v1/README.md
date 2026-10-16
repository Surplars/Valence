# Exact same-domain CSR merge compatibility

External diagnostic collector amendment; no RTL/package/constraint changes.
Source after audit_mac_netlist.tcl, before collection. Original three CDC chains
remain mandatory, with every original launch/clock/reset/ASYNC_REG/interstage/
timing test. Only the unique known expected-load comparison is patched. The
loads query is unchanged and does not hide the extra CSR sink.

Current complete parent source SHA
4d0ce0c29a083cced6754ee4d6cb9ed8d2d0aec77a8aba289687601b5c5dba2f
contains mediaOpen and previousLink with identical positive sourceClock,
positive cpuRelease async reset0 and unconditional D=media.io.linkUp.
Existing Yosys complete-parent lowering gives both ADFF CLK2/ARST871/D404/reset0.
Equality holds after reset/one clock, without an unreset power-up claim.
previousLink supplies CSR event5=linkUp XOR previousLink. Synthesis may merge
these equal registers and retain mediaOpen's name, adding the CSR event sink.

Parent's actual probe report at12:43:47 identified the three first-stage D
loads plus csr_i_3/I0; LUT2 INIT4'h6, I0mediaOpen/Q, I1media/io_linkUp_INST_0/O,
O→csr/io_ports_0_events[5], unique endpoint csr/pending_reg[5]/D FDCE; both
launch/capture clocks CPU100. The raw probe file/hash is pending transfer;
these runtime facts are explicitly parent-reported, not a claimed local run.

Installer admits only that exact extra sink after checking the full diagnostic
source identity a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615,
all listed mapped links, unique endpoint and noninverted same CPU100 clock.
Any missing CDC sink, arbitrary extra sink, changed XOR or other endpoint/domain
fails. Unknown/repeated collector gate also fails instead of broadening scope.
No false path, route repair, or same-clock blanket allowance is added.

Accepted installer SHA256:
6f9d957f2febddd16060ac7bd1871078e1c54393d3adc1759c851d5e7fb6950d.
Three synthetic test methods cover exact3/exact4 positives and12 negative
source/load/cone/clock changes. Independent review accepted final bytes before
local handoff. Full mapped collector must still run; this is no physical pass.
