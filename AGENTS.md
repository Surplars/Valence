# Repository Guidelines

## Project Structure & Module Organization

Valence is a Scala 2.13 Chisel SoC project built primarily with Mill. Current hardware sources live in `src/main/scala`; the Orbital-a1 OoO core and VL100 assemblies are in `core/ooo`, reusable IPs in `ip`, shared ISA in `isa`, and the shared TileLink protocol in `bus/tilelink/TileLink.scala`. The current Mill module retains the name `IonSoC` for script compatibility. Historical in-order hardware and its pure elaboration/configuration checks are isolated in `legacy/hardware` under the independent `LegacySoC` module; current `IonSoC` does not depend on it or `DifftestLib`. Active tests and GSIM emitters live in `src/test/scala`. `simulator/gsim` contains the only supported hardware simulator flow and direct NEMU differential tests. Old ChiselSim suites stay in `legacy/tests`, never compiled by either active test module. Historical documents and reusable payloads remain under `legacy/`; see `docs/layout.md`. GSIM C++ drivers, assembly images and pinned configurations live in `simulator/gsim/harness`, `payloads` and `config` respectively.

## Build, Test, and Development Commands

- `make compile` / `mill -i IonSoC.compile`: compile Scala/Chisel sources.
- `make legacy-compile` / `make legacy-elaboration`: opt-in historical compatibility compile/pure elaboration checks, not retired hardware simulation.
- `make test-scala` / `mill -i IonSoC.test`: active configuration and elaboration checks only; no hardware simulator.
- `make gsim-setup`: prepare the pinned GSIM toolchain.
- `make gsim-smoke`, `make gsim-backend-test`, `make gsim-integer-test`, `make gsim-core-test`: focused hardware checks; core tests include NEMU differential checking.
- `make gsim-ipc`: deterministic default bare-core IPC benchmarks with NEMU checks; reports in `build/gsim/ipc.json` and `ipc.csv`.
- `GSIM_CXX=clang++-19 make gsim-staged-fabric-test`: short, combined two-issue timing-candidate acceptance; CoreMark/DDR reuse one board model. No Vivado or full regression.
- `GSIM_CXX=clang++-19 make gsim-control-stage-test`: next combined control-path candidate, affected capacity/fetch/core-NEMU/VM checks plus reused-model board smoke; no full GSIM or Vivado.
- `GSIM_CXX=clang++-19 make gsim-data-stage-test`: combined LSU request / CPU response-credit candidate; affected credits/range/NEMU/burst/ROM/VM and reused-model board smoke only.
- `GSIM_CXX=clang++-19 make gsim-execute-stage-test`: combined two-issue ranked-operand/RAS candidate; independent RAS/NEMU/VM and reused-model board smoke only.
- `GSIM_CXX=clang++-19 make gsim-rename-stage-test`: combined prediction-payload/rename-candidate/PRF-ready checks, independent ledger/packet/NEMU/VM plus reused-model board smoke only.
- `GSIM_CXX=clang++-19 make gsim-retire-stage-test`: combined balanced branch comparison / retirement fault / ordered RAS control, affected short checks only.
- `GSIM_CXX=clang++-19 make gsim-redirect-stage-test`: combined early redirect qualification / static pending clear / native carry comparison, affected short checks only.
- `GSIM_CXX=clang++-19 make gsim-preparation-stage-test`: combined parallel memory preparation / aligned fetch PMP, independent selector/PMP/fetch plus short packet/NEMU/VM and reused-model board checks only.
- `GSIM_CXX=clang++-19 make gsim-payload-stage-test`: combined circular one-hot issue/early completion owner/raw fetch presence, independent selector/fetch plus short packet/NEMU/VM and reused-model board checks only.
- `GSIM_CXX=clang++-19 make gsim-return-stage-test`: combined registered CPU response/direct memory payload/one-hot physical operand candidate, independent credits/MMIO/operand plus short packet/NEMU/VM and reused-model board checks only.
- `GSIM_CXX=clang++-19 make gsim-fetch-address-stage-test`: combined early fallback address/static prefix decode/compact PRF candidate, affected independent decode/routing/fetch/VM/NEMU and reused-model board checks only.
- `GSIM_CXX=clang++-19 make gsim-fetch-control-stage-test`: combined ROM reply credits/raw TL reply metadata/direct prediction qualification; affected independent oracle/routing/ROM/NEMU/VM and reused-model board checks only.
- `make test` / `make regress`: Scala checks followed by full GSIM acceptance.
- `make sim-verilog`: optional historical SoC RTL export, without running a simulator.
- `make payload`: assemble a historical bare-metal payload, not a GSIM compatibility claim.
- `make clean`: clean Mill and generated GSIM/payload artifacts, without invoking vendored simulator builds.

Dependencies are documented in `simulator/gsim/README.md`. Verilator is retired: do not invoke, install, or use it as a fallback or supplementary check. Do not run legacy emu flows that transitively invoke it. Vendored upstream files may mention Verilator; they are not active project entry points.

## Coding Style & Naming Conventions

Use Scalafmt-compatible formatting before submitting changes. `.scalafmt.conf` sets the Scala 2.13 dialect, 4-space indentation, 120-column limit, and aligned declarations. Use package names that match the existing subsystem directories. Name hardware modules and Bundles in `PascalCase` (`IonSoC`, `UartTx`, `CSRFile`), values and methods in `camelCase`, and constants in the local style already present in the file.

## Testing Guidelines

### Important user-directed optimization workflow (2026-10-01)

- Keep the two-issue FPGA baseline. Batch related structural changes into one coherent candidate; do not run GSIM or Vivado after each small edit.
- Latest explicit user refinement (2026-10-05): larger batches may address ten or more related structural changes/paths before one short verification and one implementation. The earlier 2–3-path target is no longer a limit. Prioritize measured long chains and preserve independent proof coverage; do not pad the batch with unrelated risky changes.
- Finish the batch, compile once, then run only the necessary short, affected GSIM checks. Fix any failures before advancing to synthesis.
- After short checks pass, export and synthesize the combined candidate once and compare timing/resources/cycle cost with saved baselines. Reuse checkpoints for report queries.
- Do not run full GSIM, long Linux simulation, repeated full implementation, or bit generation unless the user explicitly requests them or approves a specific necessary exception.
- Preserve independent oracles, precise exceptions, ordering, and backpressure correctness. Record unverified routed timing and board results honestly.
- This explicit user workflow supersedes generic full-regression guidance below for the ongoing SoC optimization work.

Put pure Scala configuration/elaboration checks under `src/test/scala`; hardware behavioral verification uses GSIM wrappers and independent C++ drivers in `simulator/gsim`. Do not introduce ChiselSim simulation calls into active Scala suites, since they implicitly invoke the retired backend. During development run the relevant focused GSIM target. After functional hardware changes run active Scala checks and full `make gsim-test` once; do not repeat broad tests without a change or failure that warrants it. For build/documentation-only edits, validate affected entry points and a GSIM smoke run. Archive reference cases are not current test coverage; migrate expectations independently before claiming coverage. Keep generated waveforms and simulator binaries out of commits.

## Commit & Pull Request Guidelines

The current history uses short imperative or topic-style subjects, for example `TileLink Dev`, `pipeline decode test`, and `Template cleanup`. Keep commit subjects concise and name the changed subsystem. Pull requests should include the motivation, affected modules, commands run, and simulator or waveform observations. Link related issues when available.

## Agent-Specific Instructions

Preserve user changes unless explicitly asked to clean them. Prefer Mill commands for Scala/Chisel work and Makefile targets for simulator flows. Do not edit vendored or generated difftest/NEMU outputs unless the task specifically targets them.

Keep `soc.isa` independent of `soc.core` and `soc.config`: architectural encodings may be shared, but pipeline control tables belong to each core (`legacy/hardware/src/main/scala/core/pipeline/decode` for the historical adapter). Do not move legacy configuration back into the current module or use its control logic as the current correctness oracle. Audit reused encodings against the pinned specification; keep GSIM software instruction expectations and NEMU independent of the DUT definitions. See `docs/isa-reuse.md` for the audited scope.
