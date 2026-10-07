# BootROM update gate: current native RV64GC100 board

## This handoff fix needs a new full-board bitstream

The netboot handoff fix changes the GMAC ingress-stop/drain-acknowledgement RTL as
well as firmware. It is **not eligible for an INIT-only ROM ECO**. Updating ROM
contents in the old r6 routed checkpoint would leave the old GMAC hardware in
place and cannot implement this fix.

Keep the current profile: two-issue RV64GC, F/D enabled, CPU 100 MHz, AON/UART
50 MHz, UART 460800, DDR 2 GiB, and native GMAC. Do not substitute the old
DDR50/AXI-Ethernet build or use an old CPU checkpoint as the new implementation.
Old routing may be a declared incremental reference only; it is not evidence
that a changed netlist has been implemented or qualified.

No Vivado, routed-checkpoint examination, bit generation, programming, or board
validation was performed for these changes in the cloud. The original r6 DCPs,
MIF and signoff artifacts are not in this checkout. Their documented local
archive is described in [the timing ledger](../../docs/fpga-timing-windows.md).
Do not treat recorded historical margins as new results.

## What changed in the historical ECO script

`update_bootrom_bit.tcl` retains its historical DDR50 command line and 29-BRAM /
14-skew assertions. They describe that legacy flow, not the current native board.
It now rejects native GMAC, an FPU, or a CPU endpoint that is not driven by the
actual named generated 50 MHz clock **before any INIT mutation or output
creation**, including `prepare-only` mode. A spare 50 MHz clock on a 100 MHz
board does not satisfy the gate.

The script also rejects an existing output directory, compares all exposed ROM
primitive properties except INIT/INITP, checks identical INIT/INITP property
sets, and compares whole-board primitive REF/LOC/BEL and net ROUTE snapshots.
Unknown differences fail closed. Do not remove a comparison because it appears
to be metadata: inspect the actual checkpoints first. Direct legacy release
writes the patched DCP only after the existing timing/skew/route/DRC checks.
`prepare-only` output is explicitly unsigned and still requires the historical
release's firmware, reset and CDC checks. A partial directory after an error is
not a completed update.

Offline guard test, from the repository root:

```sh
tclsh fpga/zu15eg/test_bootrom_eco_guard.tcl fpga/zu15eg/update_bootrom_bit.tcl
```

This uses mocked Vivado queries. It covers the early rejection gates and route
snapshot sensitivity; it does not exercise real IP comparison, full signoff,
checkpoint serialization or bit generation.

## Local workflow for this hardware batch

1. Finish the coherent firmware/RTL batch and its affected short checks. Preserve
   their exact source hashes. Export the current full production RTL with RV64GC
   and the current two-issue board configuration; build the matching BootROM with
   netboot, 100 MHz and the 460800 UART contract. Generic historical `make
   fpga-board-rtl` defaults to 40 MHz and is not this board's export command.
2. On the user's Windows Vivado machine, stage a fresh private candidate, keeping
   r6 and the GUI project unchanged. Bring over the matched new RTL, firmware,
   native board sources, current constraints, verified MIG/clock/AXI IP, and the
   new ROM IP. Freeze inputs and affected proof receipts for this batch. Do not
   relabel old receipts or overwrite the r6 contract to make hash gates pass.
3. Use `build_native_board.tcl` with explicit `rv64gc` for a fresh source-integrated
   full-board synthesis/implementation. Its optional old routed checkpoint is
   only an incremental placement/routing reference; its resume argument accepts
   only the new candidate's own synthesized DCP. This is a local execution step,
   not a cloud command or a request to install Vivado here.
4. Recompute current routed reports, actual CDC/mailbox facts, firmware word and
   INIT identity, and a new release contract. Follow the gates implemented by
   `verify_ddr2g_release.py` and `release_native_rv64gc.tcl`; keep existing checks
   intact. Those tools bind candidate paths, hashes and proof inventories. They
   cannot release this new candidate with an unchanged old r6 contract. Use a
   distinct new release name; adding a tag or new evidence classification needs
   review rather than a renamed r6 artifact.
5. Generate a new bit only when every gate passes. Record its SHA256 and the exact
   candidate/ROM identity. Physical UART, network handoff/repeated boot, DDR and
   Linux validation remain separate, explicitly authorized local board work.

Before step 3, once `$Candidate`, `$MigXci`, `$Repo` and `$Vivado` are resolved to
real local paths and the fresh input package has passed its own hash checks, the
existing full-board entry point is:

```powershell
& $Vivado -mode batch -source "$Repo/fpga/zu15eg/build_native_board.tcl" `
  -tclargs $Candidate $MigXci rv64gc
```

This template starts implementation, not a release. Do not run it against the
old r6 candidate directory or before the affected checks and input staging pass.
The archived local paths must be recovered and verified first; this checkout
alone cannot supply the missing checkpoints or approve a release.

## Conditional plan for a future firmware-only native ROM ECO

A separate native ECO adapter can be considered only with the exact baseline
artifacts available. The current legacy script deliberately does **not** provide
that adapter. Required evidence, before implementing or running it:

- Verify the baseline own routed DCP, frozen candidate manifest, original ROM
  OOC DCP/MIF/binary, reviewed release contract and every linked receipt by hash.
  Use the immutable baseline source snapshot expected by its contract; current
  edited source is not a substitute. Recover missing files into a new directory.
- Establish that all non-ROM RTL, IP settings, clock/reset/CDC constraints, address
  map, interfaces and board inputs remain identical. Any GMAC drain protocol,
  DMA, clock, capacity or other hardware change makes this path ineligible.
- Build only a fresh ROM IP using the baseline's exact BMG settings/tool version.
  `build_netboot_rom.tcl PRIVATE_CANDIDATE_ROOT` is the existing isolated ROM
  builder; first compare its settings with the actual baseline XCI. Audit every
  new MIF word against the selected binary including zero padding with
  `fpga/firmware/audit_bootrom.py`. Independently verify the compiled UART contract.
- Compare old/new ROM primitive sets, ports, pin/net connectivity and every
  non-INIT property. Obtain the exact hierarchy, BRAM and INIT/INITP inventory
  from the verified DCPs; do not guess a hierarchy or replace 29 with a new number.
  Require each implemented old INIT/INITP to equal the baseline before writing.
- Change only matching memory INIT/INITP properties. Check every new value, preserve
  and compare whole-board topology, placement, routes and timing constraints,
  save to a fresh path, reopen it, and repeat identity/invariance checks. Any
  topology/configuration mismatch requires full implementation.
- Re-run complete current signoff and bind fresh evidence to the updated DCP.
  The native release checks actual CPU 10 ns, AON/UART 20 ns, raw TX 8 ns, delay
  reference 2 ns, ODDR TX 4 ns and DDR UI 4 ns endpoints. Require FPU presence,
  no black boxes/legacy Ethernet replacement, exact quarter-TX topology, setup /
  hold / pulse and physical TX/RX timing, coverage, clean complete routes,
  bitstream DRC, and the current reviewed CDC fingerprints without broad waivers.
- Derive the exact expected skew inventory from the verified baseline constraints
  and reports and require it unchanged and all passing. The current native
  release's minimum of 27 is not permission to guess counts or accept missing
  constraints; the old DDR50 expectation of 14 is invalid here. Preserve all
  current contract checks and reject unknown findings or unparseable reports.

A new DCP hash invalidates the old release's hash-bound evidence. A future native
ECO adapter must explicitly bind the unchanged-hardware proof plus new firmware,
ROM readback and current reports; it must not merely rewrite old hashes or claim
that `verify_ddr2g_release.py` already supports arbitrary ROM-patched checkpoints.
Until these conditions are met, no native ECO bit is qualified or generated.
