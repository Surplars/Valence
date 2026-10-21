# Common I1/A1 native-Windows board handoff

This directory contains the shared `soc_top_common_ddr` wrapper, explicit local
simulation/synthesis/implementation producers, and fail-closed final-DCP checks.
It does **not** contain a frozen production package or physical qualification.
The incomplete template deliberately fails before Vivado. Actual selected RTL,
firmware, a matching affected functional PASS receipt, and board MIG XCI are
required; historical no-MAC/PLIC/4 KiB I1 packages cannot substitute for them.

No Windows PowerShell, Vivado, xsim, full vendor-IP elaboration, synthesis,
place/route, physical timing, bitstream or board run has qualified this entry.
Cloud checks cover Python contracts, Tcl helpers, actual emitted port binding,
and a short behavioral pad oracle. Unknown installed-tool report formats or
mapped structures stop the run rather than manufacturing PASS evidence.

## Hardware boundary

- I1 CPU300 or A1 CPU100; fabric/timebase/DDR UI250; UART/AON50, in MHz.
  Fabric and AXI use the **same MIG ui_clk net**. CPU uses its own clock and
  the common Held-response CDC boundary. Equal frequencies never remove a CDC.
  Firmware `rdtime`/DTB use timebase250, not the selected CPU frequency.
- Full public `TriSpeedManagedGmac`, two TX frame slots, managed MDIO, and
  public quarter-clock RGMII for 10/100/1000. No private MAC candidate or
  fixed-1G fallback. PHY reset waits for IDELAY calibration plus 10 ms;
  stopped RXC does not reset packet owners. No raw ready path bypasses CDC.
- Public BSCANE2 USER2, 65-clock two-TAP frame, common `JtagRamLoader` DMI7.
  Both TAP orders and the deliberately wrong 64-clock frame are local tests.
- Production ROM is 128 KiB, fixed 32768x32 dual-port `blk_mem_gen_0`.
  A programmable simulation ROM cannot enter the board package.

The wrapper and complete emitted MAC encoder/parent source forms are reviewed
and hash-bound. The control-bit equality lemma applies only to those exact full
forms; mapped endpoint/transition/pad-only proofs still run after synthesis and
optimization and again on the final DCP. Changing those source forms requires
review, rather than toggling a manifest boolean to bypass the proof.

## Explicit static low-clock candidate (not dynamic frequency support)

The default `production` profile is unchanged. Export with
`--clock-profile=boot50-static` to select CPU50/fabric50, fixed MIG UI250,
fixed TIME/debug250, AON/UART50 and unchanged network clocks. Both I1 and A1
retain their full CPU/cache/peripheral geometry. CPU50/fabric250 is not this
candidate. The profile is a timing target, not routed timing or board evidence.

The exporter enables the DDR AXI, TIME and DMI CDC boundaries. The shell is
compiled with `VALENCE_BOOT50_STATIC` only for that frozen profile. The producer
creates a fresh Clocking Wizard 6.0 with three static BUFG outputs (50/50/50 MHz)
from MIG UI250; it does not reuse a CPU300 clock XCI/DCP. Runtime DRP remains
unsupported: reconfiguring this shared CPU/fabric/AON source would disturb AON
and the common reset epoch. Do not run old recovery_link_ip.tcl or its frozen
CPU300 clock inputs against this candidate.

Local handoff order, after one combined compile and affected functional checks:

1. Emit fresh production-Vivado RTL with the normal CommonMachinePlatformMain
   invocation, CPU `i1` (or `a1`), `--vivado-memories`, the real
   `--compile-receipt=...`, and `--clock-profile=boot50-static`.
2. Populate a new package and freeze with the command below. Firmware contract
   must honestly bind fabric50/TIME250 and CPU50 (or actual CMU runtime source).
   Old fabric250 firmware receipts cannot be relabeled. Functional receipt
   must match the new configuration hash; never manufacture PASS evidence.
3. In native Windows PowerShell run:
   `./fpga/common/run-local.ps1 -Manifest C:\PACKAGE\manifest.json -Vivado C:\AMD\Vivado\VERSION\bin\vivado.bat -Python C:\Python\python.exe`
   using actual installed tool paths. This runs simulation then fresh IP/core
   synthesis then implementation/signoff, preserving failed-stage evidence.
4. Only after all fail-closed signoff gates pass may a fresh run request
   `-GenerateBit`. CDC/reset21 and DCIRST44 remain unresolved until actual
   mapped/physical evidence closes them. No waiver or cloud board claim.

## Freeze real inputs

Populate a new package directory with the selected production emitter output,
source trees, public dependencies, these tools, ROM binary/COE, and actual MIG
XCI. `freeze.py` inventories an **already populated** package; it does not copy
private candidates, compile RTL, generate acceptance receipts, or fetch IP.
All arguments below except `--root` are package-relative examples:

```sh
python fpga/common/freeze.py --root PACKAGE \
  --emission rtl/emission-profile.json \
  --rom firmware/bootrom.bin --coe firmware/bootrom.coe \
  --firmware-contract firmware/clock-contract.json \
  --functional-receipt evidence/affected-functional.json \
  --mig ip/ddr4_0.xci --threads 8
```

The real emission must have `programmableRom=false`, `vivadoMemories=true`,
`hardwareClocks=true`, matching CPU/clock/MAC metadata, complete source/artifact
hashes, and compatible actual ports. Every source, blackbox resource, common
test, oracle/helper, RTL file, constraint, IP input and runner is SHA256-bound.
The separate firmware clock contract contains `abi`, `cpu_hz`, `fabric_hz`,
`timebase_hz`, and `rom_sha256`. A legacy static contract retains its actual
build-time CPU frequency and must match the selected profile. A shared ROM must
retain `cpu_hz: null`; never replace it with a fabricated build-time frequency.
Its clock contract additionally requires:

- `runtime_cpu_hz_source: "CMU resource 1 nominalHz"`,
  `runtime_cpu_hz_resource_index: 1`, and `runtime_cpu_hz_address: 268960072`
  (`0x10080000 + 0x108 + 1 * 0x40 = 0x10080148`, the real CMU CPU nominalHz register).
- `profile_cpu_hz`: the separately selected hardware nominal frequency,
  300000000 for I1 or 100000000 for A1. This is neither a ROM build constant nor
  a measured frequency. CPU frequency is never the timebase source.
- `build_contract: {"path": "firmware/bootrom-contract.json", "sha256": "..."}`:
  the unchanged original build contract. Its schema must be 1, `cpu_hz` null,
  `cpu_clock_source` the same CMU source, `cmu_clock_metadata` true, fabric and
  timebase matching the profile, and `timebase_source` exactly
  `MachineTimer.timeValue -> TIME CSR; ticks in configured timebase domain`.
- `unpadded_rom: {"path": "firmware/bootrom.bin", "sha256": "...", "bytes": N}`:
  the original build binary, whose SHA256 also matches the original build
  contract's `bootrom_sha256`. The byte count must match the actual file.

For the shared-ROM form, pass `--rom firmware/bootrom-128k.bin` to `freeze.py`.
`rom_sha256` binds this separate 128 KiB board image. The gate verifies every
original byte and that the entire remaining tail is zero. `freeze.py` adds both
referenced original files to the frozen inventory and rejects missing or unsafe
paths; the gate checks their inventory hashes and explicit reference hashes.
Mixed static/runtime metadata, a stale source/profile, a substituted original
ROM, or nonzero padding is rejected. Both profiles reuse the same original ROM
and original build contract. ROM binary and COE must agree byte for byte.
The actual MIG must be `ddr4_0` for the reviewed board and
its DDR/data/AXI parameters are checked after import into an isolated project.

The functional receipt must contain `status: PASS`,
`scope: common-platform-affected-short`, `physical_qualified: false`,
`profile_sha256`, and `source_sha256` matching every production Scala/resource
input. Configuration identity is SHA256 of UTF-8 JSON with sorted keys and
compact separators. Retain detailed independent oracle evidence. A pending or
failed common-platform boot is not accepted; do not make a synthetic receipt
just to get to synthesis. The local physical-boundary simulation is not CPU,
DDR, GSIM or full firmware acceptance.

## Local execution and threads

Materialize the entire frozen package on a native local Windows drive first.
Use native Python, PowerShell and Vivado paths. UNC/WSL paths, `/mnt` trees,
symlinks/junctions/reparse points, traversal and ADS are rejected. Python checks
that the package drive is local/fixed. This avoids Windows tools reading through
WSL or cross-filesystem working trees. A fresh `local-run` directory is required;
preserve failures and use another frozen directory for retries.

```powershell
.\fpga\common\run-local.ps1 -Manifest 'D:\Valence\candidate\manifest.json' `
  -Vivado 'D:\Xilinx\2025.1\Vivado\bin\vivado.bat' `
  -Python 'D:\Python\python.exe'
```

Each stage waits for child tools and propagates failures before downstream
work. Sources/configuration, output hashes and per-tool command/evidence hashes
are checked between stages. No stage can write a bit. `-GenerateBit` requests
one bit only after all final gates pass; the default generates reports only.
This runner neither flashes hardware nor creates a local executor task.

The request is at least eight threads. Every Vivado process sets/readbacks
`general.maxThreads`; each distinct generated IP synthesis child also runs a
checked pre-hook and retains its own thread evidence; xelab gets `-mt N`. There is no old `-mt off` or opt1
setting, and no duplicate parallel synthesis to inflate the count.
- AMD documents **synth_design maximum 4**, recorded as requested8/effective4/
  unsupported, with a retained tool/version log.
- Place/phys-opt/route record configured limit8; this is not measured active
  utilization. `opt_design` records unsupported/unknown independent limit.
- xelab's count is sub-compilation jobs. xvlog/xsim expose no assumed runtime
  worker count; unsupported settings are explicit, with installed help saved.

See AMD [set_param](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/set_param),
[implementation threading](https://docs.amd.com/r/2023.1-English/ug904-vivado-implementation/Multithreading-with-the-Vivado-Tools),
and [simulation options](https://docs.amd.com/r/2025.2-English/ug900-vivado-logic-simulation/xelab-xvhdl-and-xvlog-xsim-Command-Options).
The vendor JTAG test intentionally admits only the public pinned Vivado2025.1
TAP model hashes; another model/version needs reviewed compatibility evidence.
The RGMII pad oracle uses behavioral primitive models and nominal fixed skew;
it does not claim vendor pad or routed timing qualification.

## Constraints and same-DCP release gate

Post-synth and post-opt inspect actual retained hierarchy before adding bounded
crossings. Common Held FIFOs use both writeGray and **capturedGray** two-stage
synchronizers; the legacy readGray template is insufficient. Explicitly pruned
lanes require inactive-value proof. Held synchronous-read payload RAM/address/
output structure, scalar synchronizers and time64 mailbox are checked. All
actual max-delay and bus-skew start/end sets are inventoried; blanket CPU/fabric
false paths are not used as a substitute.

The read-only final audit automatically queries the opened DCP for selected CPU,
same-net MIG/fabric, local reset release/recovery/removal, synchronizer and held
RAM mapping, and ROM primitive INIT/address/data/disabled-write semantics.
The ROM oracle checks both ports against all 32768 expected words and rejects
aliasing or unknown mapping. Unknown hierarchy/primitive/API/report shape
returns BLOCKED. These checks have synthetic negative controls, but cannot be
qualified against a real mapped DCP in the cloud without Vivado.

Final reports come from the same SHA256-bound routed DCP. All three media rates
are separately checked by reopening that DCP and changing only the reviewed
external media clock scenarios. RX input min/max are **-1.050/+1.050 ns on both
edges**, TX output min/max -1.250/+1.250 ns. The public RX budget assumes the
reviewed PHY/PCB skew model, including 0.25 ns allowance; actual board margin
still needs measurement. No zero input delay or false path hides RX hold.
Historical private RX hold failures are not results for this wrapper.

Every scenario must meet setup, hold, pulse width, coverage, route, DRC and all
mapped bus-skew constraints. The original final DCP also needs nonnegative
per-domain setup/hold, exact rates, no blackboxes, and the structural audits.
No-delay I/O ports require exact actual endpoint/synchronizer or registered
management-output proofs; partial min/max I/O budgets are rejected. UART/MDIO
input propagation is bounded to20/10 ns and registered management/status output
legs to20 ns. Functional reset recovery/removal remains timed; only proved
three-stage release assertion pins receive asynchronous assertion exceptions.
No Error/Critical Warning DRC is waived. Missing/ambiguous coverage, an unknown
report format, stale hash, failing timing or an unreviewed CDC Critical blocks
bit generation. The final read-only audit prevents common accidental constraint
or design mutations. The gate runs inside the same Vivado process **before the
only permitted write_bitstream**, on the original DCP rather than a rate overlay.
No full CDC/all-operating-condition/board-stability claim follows from this gate.

## Short cloud checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s fpga/common -p 'test_*.py'
tclsh fpga/common/test_common_cdc.tcl
tclsh fpga/common/test_common_io.tcl
python3 fpga/common/check_board_interface.py --emitted-top RTL/CommonMachinePlatform.sv
python3 fpga/common/manifest.py check --manifest fpga/common/manifest.template.json
# Last command MUST exit nonzero: incomplete production configuration.
```

Optional `check_board_interface.py --iverilog PATH` compiles the board shell
against only the actual emitted top's port header and ignores unresolved vendor
IP. It is a syntax/port check, explicitly not full-board elaboration. The common
pad test uses the actual specialized production encoder (its constant-zero TX
error/unused speed output ports are removed); its independent public oracle
checks rate changes, bytes, duplicate nibble behavior, phase and reset. It does
not claim error injection through an input absent from the production design.

## DCI startup repair, native verification still required

The r2 diagnostic contains 44 DCIRST-1 warnings and zero DCIRESET cells.
`native_dci_startup.sv` now owns one STARTUPE3 and one DCIRESET. It waits for
EOS on the independent configuration oscillator, asserts RST, observes LOCKED
low through three samples, releases RST, then waits for synchronized LOCKED
high. Those samples implement the acknowledgement synchronizer, not a claimed
vendor pulse-width minimum. The primitive guide gives no numerical RST width;
installed UNISIM and actual device checks remain mandatory.

MIG sys_rst stays asserted until DCI ready. No MIG UI clock, UI reset or DDR
calibration signal enters the DCI sequencer, so DCI-to-MIG startup has no
calibration wait loop. LOCKED loss asynchronously inhibits ready; release is
three-stage synchronized. This is not a waiver for other reset CDC findings.
`dci_constraints.tcl` times CFGMCLK at 57.5 MHz (DS925 50 MHz +15%).

The normal simulation producer now runs `common_dci_startup_tb` against the
installed UNISIM primitives and requires `dci-run.log`. Before accepting this
repair locally, require its post-EOS/cold-reset handshake PASS, one mapped
DCIRESET at `dci_startup/dci`, zero DCIRST-1 on the new DCP, a valid MIG sys_rst
release, successful DDR calibration, and unchanged full reset/CDC signoff.
Cloud source tests are not substitute evidence. No fixed delay is used as a
proxy for LOCKED, and no DRC severity is downgraded.

Official references:
- https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/DCIRESET
- https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/STARTUPE3
- https://docs.amd.com/r/en-US/ug570-ultrascale-configuration/Start-up-Sequence-Step-8
- https://docs.amd.com/r/en-US/ds925-zynq-ultrascale-plus/Configuration-Switching-Characteristics
