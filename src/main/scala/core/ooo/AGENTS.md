# New OoO core

- This is a fresh implementation. The legacy in-order core is known to have bugs and is not a correctness oracle or a control-logic template.
- Derive instruction/exception behavior from the pinned RISC-V specification; derive microarchitecture from explicit invariants. Audit any candidate reused module and its test expectations independently.
- GSIM is the only supported simulator. Use focused `make gsim-*-test` targets during development and `make gsim-test` for full hardware acceptance. Never run Verilator, legacy ChiselSim suites, or legacy emu flows, including as supplementary checks. Historical tests are archived outside the active test source root.
- Keep the default two-wide backend extensible by configuring rename, completion, and commit widths independently. Wider elaboration alone is not evidence of a working four/six-issue CPU.
- Verify allocation ownership, same-packet dependencies, ordered retirement, precise exceptions, rollback, and stale completions with an independent model. Do not change the model merely to agree with the DUT.
- Preserve the old core and its regression assets. Keep new implementation status, limitations, and reproducible commands in `simulator/gsim/README.md` and `docs/ooo-core-plan.md`.
- Do not claim an executing CPU, ISA compliance, GSIM speedup, or synthesis performance based only on ledger/module tests.
- For each new module, define throughput, latency, capacity, port and backpressure targets before implementation; assess critical paths and scaling to wider configurations. Verify performance under dependencies and resource contention as well as correctness. Record unmeasured synthesis/timing metrics as unverified, and mark conservative bring-up mechanisms as baselines rather than final high-performance designs. Optimize system performance within explicit power, frequency and area constraints; GSIM runtime is not hardware performance evidence.
