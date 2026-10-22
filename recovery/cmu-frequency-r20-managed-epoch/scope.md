# r20 bounded managed control epoch validation

Current result: the bounded real combined TX matrix is complete: two clock ratios × normal/early-cancel, plus four independent normal/unrelated observation negatives. Final exact-source qualification is managed-accelerated-normal-r5; remaining results and aggregate verification are in managed-remaining-matrix-r3. Historical attempts below remain preserved and do not replace the final scope limits.

This opt-in stage joins the real ManagedPeripheralBank/TriSpeedManagedGmac control park to the existing I1/debug/network/DDR/timer epoch sequence. Production defaults remain off. All raw clocks run. No gate/DRP endpoint, runtime frequency whitelist, physical signoff or full-system drain ACK is supplied.

## Ordering contract

The actual fabric maintenance handshake reserves the epoch. Only matching actual fabric-held and all-obligations-idle observations can request control park. Earlier CPU/Home/MMIO owners must finish first; requesting park at prepare could strand their CSR operations. A currently parked real control endpoint adds qualification to the existing DDR/timer qualified observation, without feeding it back into the fabric's own held predicate.

Park is retained while CPU resume and the real terminal travel to AON, including AON result backpressure. Actual AON consumption authorizes release. A source/fabric-clock registered low-request observation, guarded by a release-issued state, then permits terminal retirement alongside debug, network, DDR and timer receipts. Combinational !parked is not a release witness. Completion validity is never gated by release, and retirement fire does not participate in a combinational permit/fault cycle.

Cancellation before park or qualification may retire after its real matching canceled terminal and release receipt. A PHY policy fault blocks park qualification, but is not converted into a permanent global fault: releasing park lets the original PHY retry machinery run. Genuine protocol/epoch errors remain fail-closed until common reset.

## Drain or retain

Previously offered CSR requests and accepted replies complete. Configuration dirty state and consumed-image mailbox receipts drain. MDIO serialization, arbitration and denied-response owners drain. PHY policy finishes its actual page/transaction sequence before parking. Statistics source totals and snapshots remain retained; consumers resume and merge deltas exactly once. Persistent statisticsPending is not an obstacle to park or retirement. Fresh work after release is not re-drained as an old epoch obligation.

## Planned evidence and exclusions

Use the actual managed bank in place of, not in parallel with, the old test-only unavailable-MAC/simplified packet adapter. The real I1/private caches/Home, DMA, DMI, CPU crossing, DDR five-channel crossing, timer and epoch terminal joins remain present. The external AXI endpoint remains a RAM model, not MIG. Test-only PHY startup/poll wait reductions are explicit; MDIO divider/bit/page protocol and other timeouts must stay unchanged.

Before this stage is qualified: compile/lower the actual opt-in platform, compare the default 248 SV modules against the preserved baseline, run component ordering tests and real-bank combined owner/backpressure tests, and bind source/tool/log receipts. First checkpoint: Scala compilation and actual platform emission (260 SV) pass; combined real-bank fixture emits 257 SV. Production-default emission is 248/248 byte-identical. Source and RTL hashes for both new emissions were independently rechecked. Standalone sequencing passes 201 checks, seven retired epochs and thirteen protocol-fault cases plus an observation-corruption negative. Its parked/released inputs are models, not real MAC lifecycle evidence. Real-bank native integration remains pending; its first compile found only testbench lazy-IO port-name mismatches, which are being corrected without changing emitted RTL.

Fixed-cpuHz MDIO/PHY/media/watchdog timing remains a real DFS blocker. Moving control to a fixed clock domain requires a separate design; this stage does not silently recalculate rates or relax timing. External IRQ retention during stopped fabric clocks and true gate feedback remain separate blockers. UART and CMU ownership are not covered by a MAC-only control park. CPU300/fabric250 performance constraints and the hardware-default-50 goal remain distinct and unchanged.

The combined fixture uses the real production-default AON drain and cleanup budgets, 65536 cycles each. Earlier r19 fixture 4096-cycle drain budget is too short for the real MDIO policy tail and is not reused. No production timeout or MDIO timing parameter changes.

Standalone final record is sequencer-native-r2/record.json. It includes the actual Icarus engine, ivl/ivlpp and vvp target/config chain, with before/after tool checks. Main independently rehashed sources, all seven tools and all artifacts including VVP. Earlier r1 record remains preserved, but its two-tool inventory was incomplete.

## Initial combined native attempts

The initial complete eight-clock bootstrap attempt hit its 180-second wall-clock limit before the final PHY_READY marker; that marker also follows two CSR operations and configuration drain, so its absence alone does not locate a failure. The next diagnostic attempt pauses only CPU/UI/timer clocks during preboot start=false, after common-reset release and ROM loading. The MAC source/fabric, AON, raw TX and raw RX clocks and actual MDIO bit/page protocol remain unchanged. Those three clocks resume before guest/epoch work. This does not establish simultaneous eight-clock initialization coverage.

Read-only comparison found no concrete PHY/reset/wiring, CSR address or zero-cycle response-sampling defect. Actual progress at 32768 fabric cycles/six MDIO transactions and 65536/twelve transactions matches the unchanged 64-bit Clause22 operation at about 5120 source edges. The actual manager needs 27 setup operations plus two twelve-operation debounced polls: 51 transactions, approximately 262000 fabric edges including overhead. Prior r18 logs independently observe PHY_READY at 51 transactions. Therefore a single normal combined case is approved for a bounded 600-second wall-clock run, with the original 180-second failures preserved and distinct phase-progress markers. No DUT timer, MDIO divider or guest deadline is changed. If that bound is exceeded, diagnose before increasing it again.

The two preserved initial-native-failures receipts are explicit FAIL/wall-timeout results: r3 fully concurrent preboot and r4 paused CPU/UI/timer preboot. Both final subprocesses returned -9 after 180 seconds, with process-group termination and child reaping confirmed. r4 reached 131072 fabric edges and 25 real MDIO transactions, still link=0. The current normal/unrelated 600-second attempt is pending; its runner and TB are saved as a WIP checkpoint, not a combined native PASS.


The first 600-second attempt r5 was deliberately interrupted after static review found three invalid test stimuli: initial configuration writes did not each wait for their consumed-image receipt; a later config blocker was issued while TX was busy; and the second DMA launch omitted the required ACK of txDone. No DUT failure is inferred. The tool session returned 130, but no final runner receipt exists, so process-group kill/reap is NOT established. An exact interruption note, partial progress log (163840 source edges/31 MDIO transactions), and source snapshots are preserved. A later session poll reported the session absent; this is not a child-reaping proof.

The corrected bench waits each setup config receipt, accepts its held image/reply while idle before CPU start, checks CSR errors immediately, and uses the production-defined ACK|START=3 for the second TX with an independent oracle. An independent read-only review checked these rules against the actual CSR/DMA implementation before fresh r6. Scala, DUT, MDIO and guest timing are unchanged. r6 remains pending at this checkpoint.

The runner now persists active PID/PGID, UTC start and command immediately, and supports a stop.request file consumed by its own try/finally. Main-thread source-bound controlled-stop test genuinely terminated a 30-second sleeping child in about 0.2 seconds, reaped it, verified the PID absent afterwards, and rehashed source inputs. This test is separate from the uncertain r5 interruption; it cannot retroactively prove that old child's outcome.

## Real combined normal/unrelated result

The corrected r6 case PASSED in 509.775 seconds under the explicitly approved 600-second bound, return code 0 with child reaping confirmed. The exact receipt/logs and test-source snapshots are saved in managed-normal-r6. Independent verification rehashed 331 source files, 257 original SV files, all 11 tool executables/configuration files, guest artifacts, logs, emitted assertion-expanded simulation and binary. Production-default emission remains the previously measured 248/248 byte-identical result.

The actual PHY completed 51 MDIO initialization transactions. Actual CSR reply/config-image/MDIO tails blocked control qualification; two raw frames arriving during park produced retained admission-drop statistics. AON terminal backpressure held park. After terminal consumption, new actual CSR and timer replies remained blocked while the old epoch joined exactly once across AON, debug, receipt, network and fabric. Statistics read back exactly two drops and the retained MAC address. The CPU issued the legal ACK|START=3 and sent a second packet: both packets contained 72 wire bytes with independent FCS checking, DMA request/reply 16/16, timer 58/58, AXI R 66/66 and B 3/3. Common reset cleared stale epoch proofs.

This is ONE normal case and ONE clock ratio, not the full matrix. Cancellation, reversed clock ratio and four new combined observation negatives remain unverified. The standalone sequencer negatives do not replace those real-bank integration negatives. Original 180-second timeouts and r5's uncertain interrupted-child outcome remain preserved and are not relabeled. Full-system ACK, physical gating/DRP, runtime frequency support and board signoff remain absent.

## Test-only preboot acceleration pending checkpoint

bootstrap-pending-r1 preserves the optional fixture-only preboot source schedule and both original accelerated failures. Production sources remain unchanged. Before any owner/guest starts, actual park/reset/CSR/four-stream/packet-owner emptiness is required; the real source and unchanged Clause22 model run while other empty domains pause low, then actual PHY parked/page-zero/config/MDIO idle permits low-phase permanent fabric rejoin. The real released receipt precedes ROM, CSR and guest work. This is not a production fixed-clock design or gating proof.

Accelerated r1 failed a delta-cycle clock-identity sampling check; the settled-delta observation correction does not alter handshake sampling or the no-runt check. Accelerated r2 timed out at 180.008 seconds after 51 real initialization transactions, permanent rejoin, first packet and ongoing runtime MDIO tail (57 transactions, park requested). No architectural PASS is claimed. A one-case 300-second normal/unrelated wall-only comparison is approved but no previous execution output or journal was found at recovery; it remains pending at this checkpoint. No DUT, guest or MDIO deadlines change. The existing baseline PASS, all failures and the earlier r5 uncertain-child outcome are retained.

## Accelerated normal/unrelated qualification

managed-accelerated-normal-r3 passed in 229.611 seconds under its approved one-case 300-second wall limit, with rc0 and confirmed child reaping. Independent architectural comparison against original r6 passes across packet bytes/FCS, guest artifacts and symbols, CPU coherent readback, ordered CSR values, retained statistics/configuration and exactly-once joined retirement. Independent comparison negatives reject lost packet, incorrect retained statistics and broken timer conservation. Both runs complete two packets and DMA16/16, AXI R66/66 B3/3 and CSR6/6. Phase-dependent final timer traffic differs, r6 58/58 versus r3 42/42, with corresponding post-resume held replies 53/52 versus 37/36. This is expected traffic-timing variation, not dropped ownership: every per-run conservation oracle remains active.

The real 51-transaction bootstrap, empty-owner low-phase detach/rejoin and actual released receipt pass. Production315 source hashes remain identical to r6; all source/RTL/tool/log/guest/native artifacts were rehashed, and preserved default RTL remains248/248 identical. The fixture optimization does not implement fixed-clock production control or broaden fullACK/gate/DRP/physical claims. Cancellation, reversed clock ratio and four combined observation negatives are still pending at this checkpoint.

## Remaining-matrix cancellation timeout

The first remaining-matrix run reached the real51-MDIO bootstrap, permanent rejoin, CPU TX and first72-byte packet, but unrelated cancellation timed out180.008 seconds. The original failure is preserved under initial-native-failures/managed-remaining-matrix-r1 with child-group kill/reap and source/RTL/tool/log rehashes. No later matrix case started. A possible inherited testbench self-lock at the normal-only fixed-proof pause is under read-only investigation; no DUT failure or budget increase is inferred.

## Requalification after cancellation stimulus correction

The test-only cancellation erratum is documented separately. Normal/unrelated r4 now passes240.339 seconds/300 with the corrected source-bound TB, including stronger prior-edge park-order and unconsumed-AON control-ownership assertions. Original r6 architectural comparison and comparison negative selftests pass again. Source332/RTL257/tool11 hashes were verified. The remaining matrix must use this exact r4 qualification; its cancellation and negative results are not yet claimed.

## Final bounded matrix

All four positives and four observation negatives pass their intended oracles. Current normal/unrelated229.083s, unrelated cancellation72.713s, reversed normal180.182s and reversed cancellation78.170s all complete within the separately approved named wall budgets. TX/CSR-drain/statistics/park-retention negatives reject genuinely corrupted observations in ordinary checkers at72.359/74.999/234.968/237.186s respectively. Every child is reaped in its own source-bound receipt. Source332, unchanged production315, emitted RTL257 and tool/config11 hashes match; both preserved default inventories remain248/248 byte-identical. All positive packet DMA16/16, two72-byte/FCS frames, AXI R66/66 B3/3 and joined epoch retirement counts agree. Timer traffic42/42,17/17,80/80,12/12 and CSR6/6 versus2/2 vary by scenario/clock timing but conserve per run.

The cancellation oracle is conditional exactly as the real protocol: each actual park requires a prior matching raw-held+idle witness; a no-park cancellation needs no such qualification. Both actual early-cancel ratios show one raw-held sample, no qualifying held+idle sample, no park and actual release/once-only terminal join. Original self-lock and overstrong-checker failures are explicitly retained. Tiny extracted checker tests additionally exercise legal park history and reject missing/simultaneous/stale-epoch history, but do not establish an integrated late-cancel-after-park case.

All results are fixture-only preboot scheduling plus real running-clock epoch behavior. Production fixed-clock island, fullACK, stopped-clock/gate feedback, DRP/backend, whitelist, physical/routed/board timing, RX payload, timeout and late cancellation remain outside this proof. The original r5 interrupted child's reaping remains unknown. No source/main or FPGA production file changed during this recovery; no upload was performed by this task.
