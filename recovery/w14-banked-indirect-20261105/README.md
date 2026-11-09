# W14 banked indirect-target snapshot

This is a **source-location-normalized recovery snapshot**, not a regenerated whole-core Scala source release. It preserves the latest W14 implementation and the actual component source change on an isolated development branch. The repository's normal `src/` tree is unchanged.

The remote publication is a **snapshot-only backup** based on existing remote commit `f1013f21d4aa4633428e9c2da5166cc1c2ac08a1`; `main` itself is not changed. The local source baseline was `fbdb3386c30603d3f4039389a537f18a5ae508f8`, and the original local raw-text snapshot commit `6339c31bcf913f5f058cb495a4b678d1b879df44` remains preserved. Those local commits and their development history are **not uploaded** by this alternate publication. Remote commit and full-repository tree hashes therefore differ. The exact final prepared **snapshot subtree**, not the original local commit, is verified against the remote.

## Included

- `rtl/` and `rtl.f`: all **173 ordinary SystemVerilog files**, with relative paths and `CommonA1CpuTile` as top. No observer-only core is mixed into this closure. The original frozen list is preserved, including three unused module definitions; 170 modules are reachable from the ordinary top.
- `fir/CommonA1CapacityGsim.fir.xz`: the losslessly compressed complete qualified W14 FIR, including the observer top used by the recorded CPU execution. It is a separate representation, **not** a claim that lowering this FIR recreates the ordinary-RTL closure byte for byte.
- `component/src/`: the actual nine-file Scala component source set, with the prior `BranchPredictor.scala` and exact source patch. `component/PredictionTrainingGsim.fir`, the five-file component RTL, and the independent C++ harness preserve the implemented change and affected tests.
- `baseline/`: only the prior indirect-table FIR module and ordinary RTL needed to inspect the W13-to-W14 change. The full W13 snapshot and older history are not duplicated.
- `PROVENANCE.json`, `SOURCE_CHAIN.json`, `RESULTS.json`, `MANIFEST.json`: source hashes, generation/graft chain, concise measured results and package integrity. Full local review reports, raw traces, mapped graphs, executables, model objects and runtime/tool binaries are not included.

## Source completeness and normalization

W14 replaced only the `IndirectTargetPredictor` FIR module in the W13 full-CPU FIR. In the ordinary RTL it replaced that module and added `ta_16x64`; the other **171 original RTL files are byte-identical to W13 before normalization**. The component uses four single-writer 16x64 memories, valid bits and a last-writer owner selector. Capacity remains 16 entries. The checked component source is maintained Scala; the inherited whole core contains earlier generated FIR/RTL compositions. **The current repository Scala tree does not regenerate this entire snapshot.** Closing that integration gap is still future work.

Original generated files contained private workspace locations. Only `.scala` path tokens inside FIR `@[SourceInfo]` or ordinary SV `//` source-location comments were replaced with `source_refs/<basename>`. These labels are historical attribution, not promises that every original source file is included. String literals, includes, memory initialization paths, attributes and all semantic tokens were left unchanged. The packaging check accounted for every private-root occurrence and verified that every byte outside the specifically rewritten path spans was identical. No reverse private-path dictionary is included.

`PROVENANCE.json` records each original hash, published hash, rewrite count and a protected-text hash that masks only those path tokens. **Published normalized files are not the original byte-exact qualified files.** Original local qualified files were not modified. Original full FIR SHA-256:

`31dca4707ee5ff3e61ce4849a980d3265f261115d8ab04d0697c71ed5a4abcd7`

Published normalized full FIR SHA-256:

`1cb205fe15805611feaf23b5dd01b7486d866e649a39367aa58eca6c6ef475de`

The original qualified package binding hash is in `RESULTS.json`; the new package has its own manifest. The original binding also included local filelists and baseline files, so it is **not** a manifest of this publication.

## Lightweight checks

From this directory, run:

```sh
python3 scripts/verify_snapshot.py
```

Python 3 standard library only, including its `lzma` module. The default check streams the compressed full FIR without extracting it. This verifies every published file hash and size, normalized-source protected-text hashes, relative filelists, unique modules, generated instance references, the ordinary and component tops, component/table/leaf identity, and the exact Scala patch. Replacing the W14 FIR table with the included W13 module must recover the recorded full normalized W13 FIR hash. The closure parser is deliberately limited to the observed unparameterized CIRCT output and rejects external includes/readmem dependencies. It is **not a SystemVerilog compiler, proof of RTL/FIR equivalence, CPU simulation, synthesis or timing analysis**.

The full FIR is stored as deterministic XZ (preset 3), with compressed and decompressed hashes and byte counts in `FIR_SOURCE.json`. Compression changes no source bytes. To check only its stream, or explicitly extract to a **new** directory without overwriting anything:

```sh
python3 scripts/restore_fir.py --check
python3 scripts/restore_fir.py --output-dir NEW_DIRECTORY
```

`PROVENANCE.json` uses the logical uncompressed FIR path; `MANIFEST.json` binds the actual compressed file. The extracted FIR has the normalized SHA above, not the original qualified SHA.

## Recorded results, not rerun for this backup

- Original CPU mains and necessary independent checks passed. GCC: **360526 / 320327 = 1.125493636 retired IPC**. LLVM: **407538 / 389222 = 1.047057977**. W13 cycle counts were unchanged; all **19 timed artifacts were byte-exact** to W13. These are one unchanged cold iteration per compiler, not an official CoreMark timing score.
- Ordinary full-core Yosys mapping: **257932 LUT, 77024 MUX, 62535 FF, 6935 CARRY4, 30 DSP48E2, 365 RAM32M16, 1992 RAM64M8**. Versus W13: 2008 fewer LUT, 2032 fewer FF and 168 fewer MUX, with 40 additional RAM32M16. These are separate primitive counts, not a cross-type area scalar.
- Selected structural depths (W13 to W14): query **33→35**, payload **51→52**, present **50→51**, nextFetch **63→63**, prepared **67→68**. This is not across-the-board timing improvement. Migrating payload FF state into RAM changes the FF-Q launch population. RAM clock-to-output and RAM-output/public-output CUT paths remain unmeasured; unknowns are retained. **No STA, Fmax, routed timing, board, saturation or full-source equivalence claim.**
- Component coverage: 40004 randomized cycles, original directed tests, bank-owner/stale-hit tests, and four expected observation-negative failures. Payload storage is 4096 bits plus 32 metadata bits, versus 2064 total bits previously; the functional table still holds 16 entries.

## Reproduction boundaries and dependencies

`component/dependencies.json` records Scala 2.13.17, Chisel 7.3.0, firtool 1.135.0, the Maven jar names/hashes, and original native tool executable hashes. `component/commands.json` records portable command templates and exact parameters. Supply a compatible Java 21 runtime, verified jars, firtool, GSIM, Clang 19 and required runtime libraries yourself. The tools and complete tool-source/runtime closure are **not bundled**. No claim is made that GSIM or Vivado is installed or that this works out of the box on another machine.

The component settings are two rename/commit lanes, compressed instructions enabled, registered prediction training enabled, 16 indirect entries. The isolated direction-predictor fixture uses 32 branch entries; do not confuse it with the inherited whole-core direction predictor. Compilation must use only the nine component sources and the listed non-project dependencies, not older project classes. Expand the command-template variables explicitly into a new output directory, inspect the actual generated files, compile/link with ASan+UBSan, and record tool/runtime identities before executing. The source-location-normalized FIR will naturally differ from newly emitted location metadata.

For an independently built and verified component executable:

```sh
python3 scripts/check_component.py --executable YOUR_RUN --executable-sha256 YOUR_SHA256 --output NEW_RESULT_DIRECTORY
```

The preserved C++ harness contains the independent reference and fixed seed. This optional runner checks the positive output counts and four expected rejection markers. It does not reconstruct the original full runtime binding, and is not a whole-CPU runner. No component or CPU executable is run by the default snapshot check. No new hardware-tool runs were made for this publication.

The recorded ordinary mapping used `sv2v -DSYNTHESIS` over `rtl.f`, then `synth_xilinx -family xcup -top CommonA1CpuTile`. Its complete graph/finite-depth engine and input/runtime closure are not bundled. There is no turnkey Vivado project, part choice, clock constraint or board pin assignment here. Any later Vivado use requires explicit device and timing constraints; a core-only synthesis result is not whole-board qualification. This package does not run implementation, route, bitstream generation, or introduce timing exceptions.
