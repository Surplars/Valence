# DTA configuration readability cleanup

## Scope

Based on public commit `5a0cb2993f177b498774fd570dbee9889901ca80`.

`DataTranslationAdapter` now derives canonical-store event staging and checked-hint factoring directly from `OooParams`. Both capabilities remain independently configurable; only their duplicate constructor arguments and the resulting equality checks are removed. Read-only module properties remain available to elaboration audits. Every permission, ownership, credit and topology requirement is retained. Checked enqueue-valid is written once instead of repeating the same OR expression for certified-ingress ON/OFF.

This is a source/API cleanup, not a CPU performance optimization. No queue, register boundary, architectural feature, default, or pipeline topology was intentionally changed. The constructor API change requires callers to stop repeating these two flags.

## Bounded evidence

The candidate and original production sources were freshly compiled with Java 21, Mill 1.1.7, Scala 2.13.17 and Chisel 7.3.0. `DataTranslationReadabilityEmit` creates eight small untapped production-DTA configurations; the control emitter differs only by supplying the removed constructor arguments explicitly from the same parameters. All eight effective parameter/constructor records matched. FIRRTL was lowered with firtool 1.135.0 using the same `--strip-debug-info` option on both sides. **Every paired SystemVerilog file was byte-identical**, without additional identifier rewriting or logic normalization. Raw FIR and SV differences were retained in the validation evidence.

| Configuration | Identical SystemVerilog SHA256 |
|---|---|
| canonical-0-factoring-0 | `3723c624e5042566b490c622fa572ef28a7b586c6baf224f381c18400bf2b43b` |
| canonical-0-factoring-1 | `79d63a8fe74aa7915413aaca47786e8f17aef7625c7e5db357201d74275cb3c9` |
| canonical-1-factoring-0 | `c361277ce2b00db2b0a50e0f57807217613596a37b951735514d04c0f4caf875` |
| canonical-1-factoring-1 | `8ccf796e2ef4f25f0de5a6771ad89603e02fc4e23b2e234ad67033e15d8b6a15` |
| certified | `7f5a48f0ee1ca52e78c236adc91ea21ef3480cd7fe32645f4e11d700d5afb966` |
| coexisting | `8d37bb8fff78bb2c3aec101814aa14f64d18d7a0fa8329fcc93eaa385b72f432` |
| frozen-checked | `afd7a5912cc811d704dce82c22ed7a3c7b1c585f3a91421df9666d86e05354b2` |
| nomination | `9ca78bd2a0b3beaf9b4392ec5f0be535a717fb8c5aa0bda63a26dee4c5e65de7` |

The emitter entry point is `mill -i IonSoC.test.runMain ooo.DataTranslationReadabilityEmit build/dta-readability-emit`. Lower each generated `DataTranslationAdapter.fir` with the pinned `firtool --strip-debug-info -o DataTranslationAdapter.sv`. For a matched original-control checkout, supply `registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent` and `factorCheckedNextAllowed = p.factorCheckedNextAllowed` in the otherwise identical emitter factory.

The four canonical/factoring combinations use `PendingStoreProofFixture`; the other cases cover frozen checked flow, certified ingress (efficiency profile 3), coexisting ingress (profile 4), and payload nomination (profile 5). These eight configurations are not exhaustive proof of every legal parameter combination.

## Selected checks and retained failure

The validation selection contains 25 tests: all tests in `DataTranslationConfigSourceSpec`, `FrozenCheckedFlowConfigSpec`, `TimingBatchConfigSpec`, `CombinedCheckedDataFlowSpec`, and `RegisteredRawCertifiedFlowSpec`, plus the first four tests in each of `CoexistingPhysicalLoadIngressSpec` and `LoadPayloadNominationSpec`. The two full-tile final tests are explicitly excluded; this is not seven complete suites.

The first run passed 24 tests and failed one historical `TimingBatchConfigSpec` assertion that assumed 71 configuration fields; the current base has 128. Running that same test on the original public control reproduced the failure. The obsolete total-count/position assumptions were replaced with direct typed capability checks. The existing complete configuration equality, core-parameter equality, and cache/DDR/storage/network comparisons remain. Failure logs were retained rather than reclassified as a passing original run.

After the initial test maintenance, all 25 selected tests passed. Review then simplified the maintenance itself from reflective field lookup to direct typed access. The final change affects only that test: it is recompiled and rerun separately, while the other 24 passing checks and unchanged production/emitter evidence are inherited from the preceding verified epoch. That final focused test passed; final coverage is one freshly rerun test plus the other 24 inherited passes, not a third full run of 25.

## Configurability and interpretation

For research, distinguish architectural parameters (rename/issue/completion/commit widths, capacities), microarchitectural topologies, and temporary experiment selectors. Removing duplicate inputs does not mean hardcoding the current configuration. Document legal combinations and separate elaboration coverage from behavior-tested and mapped configurations; wider elaboration alone is not evidence of a working wider CPU.

No new CPU benchmark, GSIM runtime test, resource map, routed timing, or board result is claimed. The matched DTA output supports this bounded cleanup; it does not establish universal formal equivalence or a performance/area improvement.
