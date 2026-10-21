# R9: opt-in MSI admission hold

`runtimeInterruptHold=true` requires `runtimeCancellation=true` and `runtimeMaintenance=true`. All three remain default-off. A1 rejects the runtime endpoint. No CMU backend, clock switching, rate whitelist, or full AON drain ACK is enabled.

The fabric freezes new MSI admission from the registered external prepare owner until matching terminal completion is consumed. A source request accepted on the same edge as prepare belongs to the older admitted work and must finish. A registered one-entry queue makes the admission boundary explicit: once accepted, a request cannot be withdrawn by STOP. Already admitted requests and real replies continue; the outstanding ledger retires only when the APLIC consumes the final reply. The fabric's drain condition includes that ledger, including admitted requests not yet issued to the CPU.

APLIC pending bits and outgoing queues are not cleared or reset by stop, cancel, or normal resume. Unaccepted pending MSI offers intentionally do not prevent this transport from draining. They remain in the real APLIC/arbiter and become eligible after terminal consumption. Terminal backpressure therefore keeps new admission closed even after the CPU and Home have processed release. Ordinary FENCE behavior with no external runtime owner is unchanged.

This preserves existing APLIC source semantics, not an unbounded event counter: multiple events while a source is already pending may coalesce. Persistent level-high source behavior is tested against the existing implementation. Coordinated cold reset discards all endpoint ownership and architectural pending state together; unilateral barrier reset is unsupported.

The standalone test uses the real machine/supervisor APLIC pair and real IMSIC. It observes actual admission/issue/reply handshakes plus architectural MMIO/CSR state, without looking inside pending registers. Capacity two deliberately reaches credit saturation with the real IMSIC reply queue; production helper default capacity is eight. Positive and deliberately wrong ledger/payload/pending monitors are source-bound in the component receipt.

Single-clock functional tests do not establish physical interrupt capture while fabric clocks are stopped, independent-clock reset safety, gate-open/closed acknowledgement, PLL lock, frequency selection, DDR timing or board qualification. Those interfaces remain separate required work. CPU/fabric performance constraints remain 300/250 MHz; the hardware-default 50 MHz goal is unchanged. BootROM direct Linux remains independent of optional U-Boot.

Before connecting a real fabric clock-stop ACK, every external interrupt source needs a verified stopped-clock capture contract: fixed/AON-domain event retention, or a source that holds its request until acknowledged. A synchronizer clocked only by the stopped fabric cannot capture an arbitrary short pulse. This stage deliberately does not alter peripheral event semantics or pretend that the admission barrier solves that separate requirement.

## Compatibility checks

The prior real-I1 cancellation/data regression passes with the new opt-in barrier instantiated: six epochs, five cancellations, one normal resume, six terminals, 36 stores, 36 loads and 48 dirty release beats. Its deliberately wrong load oracle fails as required. All 306 production/fixture/runner source hashes were rechecked after the run.

A fresh actual default-off `performance300-static` I1 export is byte-identical across all 248 SystemVerilog files to r8 (and its r7/r6 baseline). Thus this option adds no default production ready chain or synthesized logic. Scala compilation passed. These are functional/elaboration compatibility results, not new timing signoff.

## Real full-I1 MSI result

The independently compiled 37-word guest configures the actual M-APLIC and reads actual IMSIC pending CSR state while continuously checking RAM. The native suite passes in 5084 cycles: two normal resumes, two cancellations and four terminal results, plus one epoch aborted only by coordinated full-fixture reset. Before reset, exact delivered/replied ledgers progress 3/3, 5/5, 8/8; reset is applied with 9 delivered, 8 replied and two further unaccepted events. After reset, a new generation delivers exactly one of each identity 11/12/13, returns all three replies and retires pending bitmap 0x3800. Terminal backpressure must keep new MSI delivery closed until completion consumption.

Independent retirement ordering and both same-iteration and previous-store persistence checks cover dirty-cache recovery rather than allowing a new store to overwrite evidence of a lost writeback. Deliberately wrong memory-data and IRQ-bitmap oracles fail. Exact source, original emitted RTL, executable tools and guest hashes are in i1-msi-receipt.json; all were rechecked before publication.

The guest observes pending CSR state with global IRQ delivery disabled. It does not claim new trap-handler/IRQ dispatch coverage. Existing earlier precise-stop trap/MRET/pending tests are not silently replaced by this pending-state test.

Reproduce after sourcing scripts/cloud/env.sh: run simulator/gsim/common/i1_runtime_epoch_native.py with a fresh --out and explicit --iverilog/--vvp, then simulator/gsim/common/i1_msi_epoch_native.py with a fresh --out, the same tools, --rtl-dir pointing to the first run's rtl directory, and --emission-receipt pointing to its receipt.json. The second runner rejects source/RTL mismatch before simulation. The standalone component runner uses existing compiled classes and explicit prepared tools; exact executed commands are in component-receipt.json. No generated RTL is patched.
