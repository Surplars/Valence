# Reproduce and stage CPU/bus timing candidates from Git

These are small source scripts and SHA-256 contracts. No generated RTL, toolchain,
compiled module, kernel, rootfs, bitstream or checkpoint is stored here. Use the
existing Valence checkout and fresh subdirectories under its ignored `build/`.
The scripts never fetch, checkout, reset, install tools, launch Vivado or program
hardware. Preserve local changes before the separately authorized Git update.

## 1. Bind the final source and existing immutable inputs

Use the final confirmed `dev` SHA (40 hex digits), after all requested changes.
From the repository root:

    python3 fpga/zu15eg/concurrency_validation/verify_dev_sources.py --repo . --commit DEV_SHA
    python3 fpga/zu15eg/concurrency_validation/verify_local_inputs.py --root EXISTING_IP_ROM_ROOT

The first check compares both committed blobs and working bytes/inventory against
all production Scala sources, the native emitter and build settings used in the
cloud. The second verifies exactly 304 existing firmware/MIG/clock/BMG files and
their original `inputs.json`. Missing/changed/extra/linked files stop dependent
work. Paths are explicit arguments; no private machine path is assumed.

Expected ROM: 52,592 bytes, SHA-256
`434de77c74e735a56744851ded16231d7f24918f6d97d83753215d0ccf98b0d2`.
Matching BMG DCP:
`655bd7a26ede4002523ee0728ef74f7ad22ad5995e3ab40f210c65dab8851edd`.
Do not substitute an old ROM or regenerate firmware to conceal a mismatch.

## 2. Emit the integrated variants

Use already installed Mill 1.1.7, Chisel 7.3.0, and firtool 1.135.0. Set
`CHISEL_FIRTOOL_PATH` to the directory containing the installed firtool executable.
Missing tools require an explicit environment decision; this script installs none.

    python3 fpga/zu15eg/concurrency_validation/reproduce_integrated_exports.py --repo . --commit DEV_SHA --output build/FRESH_NATIVE_EXPORT

This calls `ooo.ManagedBoardSocMain` with the exact selected CPU100MHz/RV64GC/
issue2/LSU2/DDR2GiB/cache512/MSHR2/DDR4slots/16beats/write2 configuration and explicit
network queue settings in `EXPORT-RECEIPT.json`. The second export adds only
`--virtual-ram-load-precheck`. It verifies exact SV inventories/hashes against the
cloud exports. No new output overwrites an existing directory.

## 3. Keep comparison variants distinct

- `baseline`: 251 SV files exactly reproduce the latest supplied 6.1sol handoff.
- `resource`: historical 254-SV candidate, only shared bridge payload and banked
  home tags, before AW/W throughput and CPU-precheck source changes.
- `integrated-off`: latest 256-SV source, including AW/W dispatch and CPU safety
  metadata, virtual RAM load precheck disabled.
- `integrated-on`: identical latest source, 258 SV files, policy 2 flag enabled.

The disabled option does not remove every new metadata/control structure. See
`native-rtl-differences.json`. Resource→integrated-off includes AW/W and default-off
CPU changes; integrated-off→on isolates the flag. Do not call off an unchanged CPU
baseline or attribute all differences to the bus. Historical RTL may be reused
only when every hash/inventory matches its variant contract. This helper emits
latest off/on; it does not regenerate historical snapshots or claim old reports
qualify current RTL. The parent/user chooses which long implementations to run.

## 4. Stage one chosen variant and run the authorized local flow

    python3 fpga/zu15eg/concurrency_validation/stage_local_candidate.py --repo . --commit DEV_SHA --existing EXISTING_IP_ROM_ROOT --rtl build/FRESH_NATIVE_EXPORT/integrated-off --variant integrated-off --output build/FRESH_TIMING_OFF

For on, select matching `integrated-on` RTL and a fresh output. For a historical
variant, pass its already available, hash-matching RTL directory. Staging verifies
Git identity, exact SV, real checked-in board sources/constraints and every
external IP/ROM file before copying. It writes `staged-inputs.json` and does not
run implementation. It never changes the original GUI/IP project.

Use existing Vivado 2025.1 and native Windows paths if calling native Windows
Vivado (convert WSL paths first). The exact part remains xczu15eg-ffvb1156-2-i:

    vivado.bat -mode batch -source FRESH_ROOT/scripts/build_native_board.tcl -log FRESH_ROOT/build.log -journal FRESH_ROOT/build.jou -tclargs FRESH_ROOT FRESH_ROOT/mig/ZU15EG.srcs/sources_1/ip/ddr4_0/ddr4_0.xci rv64gc

That existing flow synthesizes/places/routes with real board clock/I/O constraints;
it does not write a bitstream. Reuse completed checkpoints for further reports:

    vivado.bat -mode batch -source FRESH_ROOT/scripts/report_ram_concurrency.tcl -tclargs FRESH_ROOT/implementation/routed.dcp FRESH_REPORT_ROOT

Review setup/hold, pulse width, unconstrained paths, CDC/reset/Gray/payload, RGMII,
DRC, actual PRF/home-tag/bridge RAM primitives and replication, ROM INIT/INITP, and
LUT/FF/LUTRAM/BRAM/DSP. CPU100MHz margin is a hard constraint. Old route references
are optional placement hints only; current synthesis cannot be replaced by them.

## Evidence boundary

Ten synthetic helper tests cover source/commit drift, wrong SHA, extra Scala,
IP and board-source mutation, missing binding, existing outputs and successful
staging within an existing checkout. Run `test_source_staging.py`. Tcl source
closure and syntax were checked, but vendor execution and actual local dependency
identity remain pending. No timing or mapped-area result is included.

Separate RAM A/B, bus A/B, and CPU-policy2 same-ELF tests passed at their documented
scopes. After AW/W merge: integrated compile, four config tests, byte-identical
bridge/fabric CHIRRTL and replay passed. A full-core replay of this final merged
AW/W version has not run. CPU precheck stays default off; directed same-ELF warm
ROI was4422→1809cycles, chain2311→2311, cold512→538 under a fixed AXI model. Backing-
fabric overlap is not full-board coherent CPU/DMA concurrency or MIG bandwidth.
