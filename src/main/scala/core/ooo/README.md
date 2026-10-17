# OoO core and current platform source layout

This tree contains both Orbital-A1 pipeline code and the current SoC assemblies,
cache/memory services, and bus adapters. Being below `ooo` does **not** make every
module OoO-specific. The 2026-10-17 move is physical organization only: all 149
Scala files retain their bytes, `soc.core.ooo` package, class names, imports,
package-private visibility, defaults, and interfaces.

| Directory | Responsibility |
| --- | --- |
| `frontend` | Fetch packets/windows, prediction, redirect qualification, fetch PMP glue, prediction retirement feedback |
| `decode` | Integer/bit/FP decode and instruction legality |
| `rename` | Rename candidates/capacity, physical-register storage/readiness |
| `issue` | Issue payload/selection, operand readiness/read, issue-execute staging |
| `execute`, `execute/fp` | Integer/branch/multiply/divide and FP arithmetic datapaths |
| `retire` | ROB storage/completion/head selection, retirement/recovery; `RenameRob` retains its coupled rename/ROB implementation |
| `lsu` | Load/store ordering, replay, preparation, store ownership/proofs and FP memory requests |
| `system` | Privileged/system execution and architectural FP state/retirement bridge |
| `integration` | OoO backend (including existing dispatch wiring), complete core and machine-core wrappers |
| `interfaces` | Existing backend request/completion/retirement bundles |
| `config` | Existing core, cache, memory, FPGA and bridge configuration types |
| `cache` | Instruction/data caches, coherence home and cache-port services |
| `mmu` | Translation, page-table walking, PMP and core-facing permission adapters |
| `platform` | Board/Ethernet/FPGA/SoC assemblies |
| `platform/bus` | Register routers, request/response buffering, arbitration and TL/AXI adapters |
| `platform/memory` | RAM/ROM, atomic memory and FPGA memory implementations |
| `util` | Existing arithmetic, banked read and aperture helpers |

`cache`, `mmu`, `platform/bus`, `platform/memory`, some `config` types and `util`
are candidates for future SoC reuse, **not** certified core-independent IP.
Some still depend on current core bundles/configuration or instantiate the OoO
core. A future in-order integration must audit those interfaces and ownership
boundaries first. This change does not move them to `shared`, prescribe an
in-order API, copy legacy logic, or change `legacy/` dependencies.

For this compatibility migration, directory names are responsibility labels,
not new Scala packages. A future package/API split is a separate reviewed change.
Pipeline feedback remains in its owner subsystem (for example prediction/RAS
feedback in `frontend`); cross-stage files are not split just for appearance.

See [migration notes](../../../../../docs/ooo-layout.md), including the complete
old-path → new-path SHA256 manifest and frozen-evidence limitations.
