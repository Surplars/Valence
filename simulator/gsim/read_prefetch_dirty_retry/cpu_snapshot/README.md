# Exact CPU observer snapshot

These files are byte-identical copies of the final qualified `cpu-ab-r1` host
sources, including passive posted-refill/install tracking and its negative
controls. `provenance.json` lists original paths and SHA256 values. This newly
tracked directory has not been executed.

`run_cpu_ab.py` intentionally retains its original recovery-relative topology
and historical source-freeze constant. It is a provenance snapshot, not a
relocatable entry point. Do not invoke it from this directory. Restore the
original thin CPU evidence package and its referenced matching-board/toolchain
materials in the recorded layout, then follow that package's README. A future
fresh run from a different layout must independently bind its sources, tools,
guest, actual constructors and output hashes and obtain the appropriate run
grant; changing this snapshot's paths would not reproduce an already executed
run.

The original source-freeze commit predates the final focused-driver fixes.
That historical identifier describes the CPU run only. The active focused
driver in `simulator/gsim/harness/read_prefetch_dirty_retry.cpp` is the final
`a14a94e` version. No obsolete focused driver is added by this snapshot.

The six matching-board Scala wrapper files in the normal test source tree
match the qualified CPU source exactly; the other modified production and
Scala test files match the focused qualification. The original guest, full
logs/raw traces, failed fixtures, previous observer revisions and prior
binaries remain referenced by the evidence packages. The thin CPU package
contains source/host/raw/receipts/guest and small constructor metadata; generated
models, objects, executables and tool binaries are excluded.

The observer preserves original full-byte/fault/reply/drain controls. The new
posted refill/install checks identify a full generation and require real
handshakes before owner retirement. See the experiment document and
`sv39-zero-posted-bridge.json` for the narrower evidence supporting the retained
original ON Sv39 run. None of these files establishes physical timing, FPGA
resource cost, or board behavior.
