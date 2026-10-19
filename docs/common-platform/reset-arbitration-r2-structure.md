# Reset-defined RR: bounded actual-module structural cost audit

## Decision-relevant result

All ten independent small-module mappings and structural checks passed. This is a completed audit, not a timing or performance signoff.

**The reset fix does not shorten the measured maximum chain. Four of the five instances have no per-output-port depth increase. AXI AR has a local handshake-depth regression even though its overall maximum remains two primitive layers.**

- Five-instance sum: **FF 7 → 7; LUT 1303 → 1300; MUXF 102 → 102**.
- AXI AR: `io_in_0_ready` and `io_in_1_ready` each grow from 1 → 2 layers for both primary-input and FF-Q sources. `io_out_valid` grows from 1 → 2 layers from primary inputs and gains a two-layer FF-Q path. Its FF CE also gains a two-layer FF-Q path. The LUT decrease must not be described as shortening these paths.
- Other four instances: no source-category/individual-output-port depth change. No mapped FF increase and no new payload register stage.
- Reset wiring replaces the seven old FDREs with six FDPEs and one FDCE. New reset directly reaches PRE/CLR: zero combinational primitives; this is an added asynchronous-reset network, not zero physical reset cost.
- LUT sizes change even where total LUT counts do not. Equal layer counts do not establish equal propagation delay, routing, fanout, placement, frequency or timing margin.

## Scope and provenance

- Requested baseline identity: `df9821cd8be30898bf289a06350dd49d5ad65b66`. Actual old RTL input: `../common-platform-a1-native-rtl-r3/`.
- New source HEAD checked: `c7c54336f730fe24a719cdda4ff8f84856ababa0`. Actual new RTL input: `../common-reset-a1-native-rtl-r1/`.
- Both emission profiles have identical scalar parameters: actual A1, issue width 2, 32-KiB instruction/data caches, 8 TLB entries, DDR slots 4/write slots 2, home lines 1024/ways 4/acquire 2/writeback 2; no reduced-parameter stand-in.
- All ten module-file hashes and eight unique containing-module-file hashes match their original emission-profile artifacts. Each matched instance has identical named port connections except the added `.reset(reset)`. Every module port direction/width matches except that added reset.
- No source or compiled-class files were written. No elaboration, CPU simulation/synthesis, GSIM/guest/performance rerun, installation, Verilator or Vivado was performed. Existing behavioral PASS results are outside this audit; this audit does not claim to reproduce them.

| Instance | Old actual module | New actual module |
|---|---|---|
| CoherentWriteDispatch.arbiter | RRArbiter2_LineWriteRequest | ResetDefinedRRArbiter |
| TwoBankTileLinkRouter.replies | RRArbiter3_TLBundleD | ResetDefinedRRArbiter_1 |
| TileLinkAxi4OutstandingBridge.arArb | RRArbiter4_Axi4Address | ResetDefinedRRArbiter_3 |
| ParallelLoadStoreUnit.completion | RRArbiter2_BackendCompletion | ResetDefinedRRArbiter_4 |
| ParallelLoadStoreUnit.requests | RRArbiter2_DataRequest | ResetDefinedRRArbiter_5 |

## Resources and maximum output depth

Counts are standalone synthesized actual modules, summed once per listed instance. Values are old → new. MUXF is MUXF7+MUXF8+MUXF9.

| Instance | FF | LUT | MUXF | Input → output layers | FF-Q → output layers |
|---|---:|---:|---:|---:|---:|
| CoherentWriteDispatch.arbiter | 1 → 1 | 582 → 582 | 0 → 0 | 1 → 1 | 1 → 1 |
| TwoBankTileLinkRouter.replies | 2 → 2 | 188 → 188 | 102 → 102 | 3 → 3 | 3 → 3 |
| TileLinkAxi4OutstandingBridge.arArb | 2 → 2 | 53 → 51 | 0 → 0 | 2 → 2 | 2 → 2 |
| ParallelLoadStoreUnit.completion | 1 → 1 | 329 → 328 | 0 → 0 | 1 → 1 | 1 → 1 |
| ParallelLoadStoreUnit.requests | 1 → 1 | 151 → 151 | 0 → 0 | 1 → 1 | 1 → 1 |

## Complete endpoint/source split

Each entry is old → new; “—” means no path from that root category (constant-only endpoint or no reachable source), not zero. A direct source wire is 0. FF clock pins are excluded. D/CE/reset/set endpoints are all included; CE is sometimes optimized into D with CE tied high.

| Instance | Input→D | Q→D | Input→CE | Q→CE | Input→reset/set | Q→reset/set |
|---|---:|---:|---:|---:|---:|---:|
| CoherentWriteDispatch.arbiter | 1 → 1 | 1 → 1 | — → — | — → — | — → 0 | — → — |
| TwoBankTileLinkRouter.replies | 1 → 1 | 1 → 1 | 1 → 1 | — → — | — → 0 | — → — |
| TileLinkAxi4OutstandingBridge.arArb | 1 → 1 | 1 → 1 | 2 → 2 | — → 2 | — → 0 | — → — |
| ParallelLoadStoreUnit.completion | 1 → 1 | 1 → 1 | 1 → 1 | — → — | — → 0 | — → — |
| ParallelLoadStoreUnit.requests | 1 → 1 | 1 → 1 | 1 → 1 | — → — | — → 0 | — → — |

## Per-port changes, including changes hidden by module maxima

| Instance | Output port | Source | Old layers | New layers |
|---|---|---|---:|---:|
| TileLinkAxi4OutstandingBridge.arArb | io_in_0_ready | input | 1 | 2 |
| TileLinkAxi4OutstandingBridge.arArb | io_in_0_ready | FF_Q | 1 | 2 |
| TileLinkAxi4OutstandingBridge.arArb | io_in_1_ready | input | 1 | 2 |
| TileLinkAxi4OutstandingBridge.arArb | io_in_1_ready | FF_Q | 1 | 2 |
| TileLinkAxi4OutstandingBridge.arArb | io_out_valid | input | 1 | 2 |
| TileLinkAxi4OutstandingBridge.arArb | io_out_valid | FF_Q | — | 2 |

Only these six source/port comparisons change. AXI AR ready[2]/ready[3] and payload remain at two-layer maxima. All other per-port comparisons are unchanged.

Representative retained witnesses:
- Router reply payload maximum: input → LUT1 → MUXF7 → MUXF8 → `io_out_bits_opcode[0]`, or FF-Q → LUT5 → MUXF7 → MUXF8. Same three-layer patterns in both versions.
- New AXI AR FF-Q → CE: LUT6 → LUT4. The old CE cones have no FF-Q dependence and the old input → CE maximum is already two layers (LUT4 → LUT2).
- Full witness endpoints, source names, cell sequences and reachable-bit counts are recorded in every `analysis.json` and in `receipt.json`.

## Reproducible method and limitations

1. Read each actual emitted `.sv` directly with installed sv2v v0.0.13 using `-DSYNTHESIS`. This excludes only the generated non-hardware `$error`/`$fatal` assertion block; reset and functional logic remain. Existing optional `ENABLE_INITIAL_REG_` behavior remains disabled by its normal undefined macro. No replacement RTL or reduced widths are introduced.
2. Run installed Yosys 0.52 (`fee39a3284c90249e1d9684cf6944ffbbcbb8f90`) identically: `read_verilog dut.v; hierarchy -check -top MODULE; synth_xilinx -family xcup -top MODULE -flatten -noiopad -noclkbuf; check -assert; write_json mapped.json`. No timing constraints, retiming or physical implementation.
3. Count mapped primitives, then trace longest unweighted primitive connectivity from primary inputs or FF-Q to every output and every FF D/CE/reset/set pin. Every LUT/MUXF primitive counts as one layer. Every input pin is conservatively considered to affect its primitive outputs, so logical false/unsensitizable paths may be included. Constants are not launch sources.
4. Independently recompute all group depths and reachable-endpoint counts by forward topological traversal (`verify_forward.py`), and verify hashes/counts of every retained complete mapped JSON. All ten pass.
5. These are isolated-module mapping results. Cross-boundary optimization and whole-platform downstream path extension are not measured. No ns, routed timing, clock frequency, WNS/TNS, or throughput improvement is inferred. The audit shows a bounded structural tradeoff and identifies the AXI handshake regression for any next no-throughput-loss optimization.

## Evidence

- `receipt.json`: commands, tool hashes, exact module/instance mapping, emission-profile hashes and matching parameter summary, per-source/per-endpoint/per-output-port data, integrity and space checks.
- `summary.csv`: compact 10-row FF/LUT/MUXF and 2×4 endpoint-depth matrix.
- `*/mapped.json.gz`: all ten complete Yosys mapped JSON files, losslessly compressed, including primitive library definitions. Raw JSON hashes are retained.
- `*/analysis.json`, `*/map.ys`, `*/map.log`, `*/dut.v`, `*/sv2v.log`: per-module mapping, checks and witnesses.
- `independent-verification.json`, `verify_forward.py`: independently recomputed graph maxima and SHA checks; rerun without synthesis using `python3 verify_forward.py`.
- `audit.py`: exact bounded mapping/analysis procedure; writes only this evidence directory and stops its own command group if free disk falls below 4 GiB or added evidence exceeds 30 MiB.
- `finalize_report.py`: emission-profile cross-check and summary generator.

Observed mapping peak new evidence: 21.563 MiB. Minimum sampled free disk: 4.795 GiB. Final compressed deliverables: approximately 12.5 MiB. No source commit was made.
