# Repository Guidelines

## Project Structure & Module Organization

IonSoC is a Scala 2.13 Chisel SoC project built primarily with Mill. Hardware sources live in `src/main/scala`; the independent new OoO core is in `core/ooo`. Active Scala parameter/elaboration tests and GSIM emitters live in `src/test/scala`. `simulator/gsim` contains the only supported hardware simulator flow and direct NEMU differential tests. Old ChiselSim suites remain archived in `legacy/tests`, outside active test discovery; retired C++ harnesses and firmware checkouts have been removed. Historical documents and reusable payloads remain under `legacy/`; see `docs/layout.md`. GSIM C++ drivers, assembly images and pinned configurations live in `simulator/gsim/harness`, `payloads` and `config` respectively.

## Build, Test, and Development Commands

- `make compile` / `mill -i IonSoC.compile`: compile Scala/Chisel sources.
- `make test-scala` / `mill -i IonSoC.test`: active configuration and elaboration checks only; no hardware simulator.
- `make gsim-setup`: prepare the pinned GSIM toolchain.
- `make gsim-smoke`, `make gsim-backend-test`, `make gsim-integer-test`, `make gsim-core-test`: focused hardware checks; core tests include NEMU differential checking.
- `make gsim-ipc`: deterministic default bare-core IPC benchmarks with NEMU checks; reports in `build/gsim/ipc.json` and `ipc.csv`.
- `make test` / `make regress`: Scala checks followed by full GSIM acceptance.
- `make sim-verilog`: optional historical SoC RTL export, without running a simulator.
- `make payload`: assemble a historical bare-metal payload, not a GSIM compatibility claim.
- `make clean`: clean Mill and generated GSIM/payload artifacts, without invoking vendored simulator builds.

Dependencies are documented in `simulator/gsim/README.md`. Verilator is retired: do not invoke, install, or use it as a fallback or supplementary check. Do not run legacy emu flows that transitively invoke it. Vendored upstream files may mention Verilator; they are not active project entry points.

## Coding Style & Naming Conventions

Use Scalafmt-compatible formatting before submitting changes. `.scalafmt.conf` sets the Scala 2.13 dialect, 4-space indentation, 120-column limit, and aligned declarations. Use package names that match the existing subsystem directories. Name hardware modules and Bundles in `PascalCase` (`IonSoC`, `UartTx`, `CSRFile`), values and methods in `camelCase`, and constants in the local style already present in the file.

## Testing Guidelines

Put pure Scala configuration/elaboration checks under `src/test/scala`; hardware behavioral verification uses GSIM wrappers and independent C++ drivers in `simulator/gsim`. Do not introduce ChiselSim simulation calls into active Scala suites, since they implicitly invoke the retired backend. During development run the relevant focused GSIM target. After functional hardware changes run active Scala checks and full `make gsim-test` once; do not repeat broad tests without a change or failure that warrants it. For build/documentation-only edits, validate affected entry points and a GSIM smoke run. Archive reference cases are not current test coverage; migrate expectations independently before claiming coverage. Keep generated waveforms and simulator binaries out of commits.

## Commit & Pull Request Guidelines

The current history uses short imperative or topic-style subjects, for example `TileLink Dev`, `pipeline decode test`, and `Template cleanup`. Keep commit subjects concise and name the changed subsystem. Pull requests should include the motivation, affected modules, commands run, and simulator or waveform observations. Link related issues when available.

## Agent-Specific Instructions

Preserve user changes unless explicitly asked to clean them. Prefer Mill commands for Scala/Chisel work and Makefile targets for simulator flows. Do not edit vendored or generated difftest/NEMU outputs unless the task specifically targets them.

Keep `soc.isa` independent of `soc.core` and `soc.config`: architectural encodings may be shared, but pipeline control tables belong to each core (`core/pipeline/decode` for the legacy adapter). Audit reused encodings against the pinned specification; keep GSIM software instruction expectations and NEMU independent of the DUT definitions. See `docs/isa-reuse.md` for the audited scope.
