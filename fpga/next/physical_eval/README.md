# Three-row physical evaluation tools

These tools prepare an explicit, already emitted ThreeProofRowNativeMain export
and support one fresh synthesis followed by opt/place. They do not emit a
different hardware profile, route, generate a bitstream, or program a board.
The supported board/recipe remains CPU100, core178/profile95, proof3,
earlycredits2, LSU4, native MAC, USER2 chain2 and RAM loader; no CPU halt/step claim.

Run `python3 -B prepare.py --help` for required arguments. Supply the source
checkout's full commit, native directory, reviewed IP root and hash manifest,
selected ROM directory and both the unpadded and zero-padded 128KiB SHA256s.
The source checkout must have no tracked changes. The run directory must be new
and outside the source checkout; prior export/run evidence is never overwritten.
The IP manifest uses paths relative to its supplied root and binds every copied
IP/XDC file by hash. No old SoC checkpoint is imported. The fixed ROM XCI relative
COE binding and generated MIF are checked against the selected image.

Python execution is explicit: `--python-mode native --python-command python3`
for Unix Vivado, or `--python-mode wsl --wsl-distribution DISTRO
--python-command python3 --wsl-command wsl.exe` for Windows Vivado. Run preparation
in the Unix source environment. Runtime config is generated outside Git; convert
the run-root argument to the native Vivado path when launching on Windows.

Preparation never launches a tool. After reviewing its receipt, explicit Vivado
batch entry points are `scripts/r3_synth.tcl RUN_ROOT` and
`scripts/r3_place.tcl RUN_ROOT FRESH_RUN_NAME`. Each invocation needs its own log
and journal outside the source tree. Both default to four threads via generated
config; `--threads 16` explicitly requests sixteen. Non-positive/non-integer
values fail in preparation. The installed Vivado validates its own supported
upper bound through `set_param`, followed by `get_param` readback: rejection or
a changed value aborts rather than silently reducing the request. Each run
records requested/configured values, tool version and status in `threads.tsv`.
A configured maximum is not a claim that all workers are continuously busy.
The preparation receipt records the request; actual values are unknown until
an explicitly launched tool run. No cross-version maximum is hardcoded.
AMD UG904 2025.1 documents an older 1..8 limit, while preserved evaluation
logs explicitly show the installed placer using 16; runtime verification keeps
that discrepancy visible rather than treating the old table as an executable
upper bound. See [UG904](https://docs.amd.com/r/2025.1-English/ug904-vivado-implementation/Multithreading-with-the-Vivado-Tools). Both physical MAC
generics are explicitly one through the source-bound synthesis consumer.

Every fresh placement extracts actual mixed-width BRAM INIT, parity and primitive
connectivity and checks all logical words through the A-even/B-odd shared-row
boundary. Unknown mappings fail closed. `verify_rom_graph.py ROOT DUMP
--rom-sha256 HASH --padded-sha256 HASH` is read-only by default; optional `--report`
uses exclusive creation. No saved filename alone authorizes ROM contents.

Run `python3 -B test_tools.py` for lightweight CLI/Tcl guards.
`python3 -B summarize.py RUN_ROOT RUN_NAME` reads existing reports and prints JSON;
it never opens Vivado or writes to the run. Negative setup/hold and CDC findings
remain visible; these tools do not confer timing closure, CDC/RDC or board signoff.

The preserved historical evaluation used four synthesis threads, then sixteen
opt/place threads following the user's exact message “16线程开满”. That was an
authorized historical setting, not the default for future runs. Original logs,
DCPs and scripts remain outside this patch and must stay immutable.

Candidate verification covers portable input/runtime guards and the decoder on
preserved positive and tampered INIT evidence. A new full Vivado run of this
parameterized entry point has not been performed. Pipeline RTL is unchanged.
