# r23 fixed MAC platform integration, functional protocol only

**Dynamic protocol simulation, NOT hardware frequency switching.**

Final r23 bounded functional matrix PASS: real integration 4 positive + 5 ordinary
negative controls; adapter 6 positive (including 3 fail-closed fault cases) + 4
ordinary negatives. Default OFF 248/248 emitted SV byte-identical. Enabled
functional platform emits 265 SV. Independent verification is
`aggregate-verification-r1.json`; later sections retain checkpoint chronology.

Initial WIP1 was not native-validated. Later checkpoint evidence below supersedes
its pending-test status, not its exclusions. This continues r21/r22 with a
new, default-off `runtimeFixedMac` selection in ManagedPeripheralBank and
CommonMachinePlatform. No production default, clock gate, rate backend, MMCM,
DRP, reset topology or CPU300/fabric250 constraint is changed.

## Ownership contract

The existing network, control, debug, DDR/timer and runtime epoch owners remain
in charge. A new fabric adapter allocates strictly increasing nonzero 16-bit
command serials, not epochs. Real network DMA pause + runtimeTxIdle + absent TX
offers close producers. Both outer TX source stores drain before the command
crosses, and destination/prefetch/output owners drain before fixed MAC TX stop.
RX/status tails remain live; matching fixed RX proof additionally joins actual
fabric output-store emptiness and the existing DMA owner predicate. External
post-stop frames retain the receiver's explicit counted-drop policy.

Only matching raw fabric-held/all-obligations-idle and absent CSR offer allow
PARK. PARK is issued atomically only when the existing boundary is ready, so a
cancel cannot strand a queued PARK behind newly offered CSR work. CSR bridges
retain accepted replies until actual consumption. The whole single MAC source
island runs on its existing continuous raw125 leaf; UART/CMU remain fabric-native.

Actual AON terminal consumption permits the old sequencers to lower their votes.
The opt-in boundary defers the existing release command receipt until actual
fixed release, final matching released snapshot launch and fabric consumption,
and command destination drainage. The fabric adapter consumes observations
without depending on receipts, avoiding a cycle. Last-snapshot publication stays
closed until another command is actually consumed. No fresh CSR or packet work
is re-drained for old retirement. Receipt-return ACK propagation itself may
remain in flight; this is not a claim that every physical CDC wire is idle.

Same-epoch old-serial observations drain but cannot qualify. Matching false
observations withdraw old cached truth. Wrong epoch/future or malformed current
observations and unexpected/duplicate receipts fail closed. Publication ending
after release does not hide an old owner: the final receipt proves consumption;
subsequent PHY activity belongs to newly admitted work and is not an old idle
qualification. Live PHY diagnostics remain in the actual MAC/CSR path.

Persistent IRQ levels cross to fabric and survive a fabric pause while asserted.
Arbitrary external pulses are NOT claimed to be captured. Common cold reset
still discards all owners together; unilateral reset remains forbidden.

## Checkpoint status

- Initial Scala compile and adapter composition emission passed before final
  review corrections. A fresh compile is recorded alongside this checkpoint.
- Independent read-only review found and corrected requested-PARK admission
  proof self-dependency and combinational serial-exhaustion fault feedback.
- New adapter unit fixture explicitly models upstream/MAC owner witnesses;
  it is not evidence for the real CPU/Home/DMA platform joins.
- Native positive/ordinary-oracle negatives, actual default RTL equality,
  enabled platform emission and real-I1 normal/cancel regressions remain pending.
- No remote upload attempted. Historical denied receipt and prior bundles are
  preserved. This checkpoint must not be described as r23 qualification.

## Second local checkpoint: measured partial qualification

The initial warning above describes WIP1, not a claim that later tests did not
run. This second checkpoint preserves:

- Default OFF: 248/248 actual SV files byte-identical to r16, no normalization.
- Enabled CommonMachinePlatform emits 265 SV files with one real MAC; source and
  fixed FIFO endpoints use the same existing continuous raw125 clock.
- Adapter matrix r3: three ratios (fixed125, fabric50/250/~71.43), three explicit
  protocol-fault cases (old post-retirement snapshot, duplicate receipt, serial
  exhaustion), four ordinary observed-value negative controls. Modeled upstream
  and MAC endpoints remain explicit; this does not replace the real platform.
- Actual I1/Home/DMA/debug/DDR/timer/managed-MAC normal epoch at fabric50 PASS:
  175.457 seconds wall time, 4 commands/4 receipts, one final release snapshot
  held 44 fabric cycles, real CSR 6/6, DMA 16/16, two 60-byte-body TX frames,
  two intentionally closed-admission RX drops counted and recovered exactly.
  Old AXI R/TX tails, live timer owners, config images/CSR response/MDIO owners,
  AON terminal and final-snapshot backpressure, new post-release CSR/timer work,
  original network/debug/fixed retirement, and coordinated reset all exercised.
- `checkpoint-verification-r1.json` independently rehashes current source/RTL,
  tools, native binary, guest artifacts and logs; checks ordinary oracle markers,
  exact topology, default equality and terminal ledgers. It explicitly reports
  `whole_matrix_complete=false`. Cancel/second-ratio/real-MAC negatives remain
  pending at this checkpoint. No gate, DRP, board, physical timing or integrated
  RX-payload-through-DMA qualification is claimed.

Intermediate adapter matrix r2 failed only its test ledger: the deliberately
injected same-epoch old-serial released observation was incorrectly counted as
a final current release. The ordinary ledger now checks epoch+serial identity;
its original failure receipt/log are preserved. Matrix r1 lacks the later three
protocol-fault cases. Neither is substituted for final adapter matrix r3.

For runtime speed, the real MAC is always fixed125. The fixture only pauses
empty fabric/CPU/UI/timer/debug domains during preboot PHY initialization after
reset release and checks they own no transactions. It NEVER switches or rejoins
the MAC source clock. This is simulation scheduling, not physical gate evidence.

## Third local checkpoint: all four real positive scenarios

Normal and early-cancel PASS at fixed125 with fabric50 and ~71.43 MHz. CPU, AON,
debug, raw RX, DDR UI and timer have the independently phased ratios in the
receipts. Two normal cases consumed 4 commands/4 receipts; two cancels consumed
3/3. Last released snapshots were held for 44 fabric cycles at 50 MHz and 40 at
~71.43 MHz. The five actual-MAC ordinary negative controls remain pending here.
The ~71.43 MHz stress ratio is not a 5 MHz grid whitelist entry.

Adapter matrix r5 adds a real accepted CSR reply while PARK is desired with live
held witness. No PARK command can be queued behind that reply. Cancellation then
releases/retire the old epoch while the fresh CSR reply remains owned, and the
reply is consumed afterward: 2 CSR accepts/2 replies, 5 commands/5 receipts across
two epochs. Matrix r4 reached its DUT PASS but the host checker still expected
one CSR, so that failure is retained. Matrix r5 updates the exact ledger to two.

The first second-ratio attempt did not start VVP: the reused host helper rejected
its 300-second ceiling without a named approved-case budget. The retry supplies
that existing budget field; there is no change to DUT/MDIO/guest/protocol timing.
Only this approved host ceiling and three inaccurate TB header comment lines
differ from the first two positive source snapshots. The independent verifier
checks these exact differences and all unchanged source/RTL/tool/guest/log hashes;
it never claims the two runner/TB texts are byte-identical.

`archive-manifest-wip2.json` was generated before the WIP2 SCOPE append and thus
its SCOPE entry describes the earlier text. The immutable manifest is preserved,
not silently repaired; the remaining entries are unchanged. The new checkpoint
manifest is written only after the final documentation and archive copy.

Additional explicit exclusions from independent review: early cancellation is
not late-cancel-after-park; retained RX/status/B-owner/timeout branches are not
executed by this case3-only integration; negative8 corrupts an ordinary checker
observation, it does not inject an old snapshot into the real MAC adapter (the
adapter unit matrix tests protocol injections). Integrated final reset pauses
CPU/DDR/timer but not the MAC fixed125 clock, so it is not fixed-MAC-paused-reset
coverage. AXI RAM and Clause22 PHY pins are external models; real MAC/MDIO/media/
watchdog/CDC/CSR/DMA/CPU/cache/Home/runtime owners remain actual RTL.

The shortest remaining board dependencies, without starting extra optimization,
are recorded in `BOARD_ENABLEMENT_REMAINDER.md`.

## Final bounded qualification

All five actual-MAC ordinary negatives now pass by corrupting an observed value
and reaching the unchanged corresponding checker: TX payload, accepted CSR drain,
retained RX-drop statistics, PARK retention during terminal backpressure, and
release while the last snapshot remains unconsumed. They do not count direct
forced fatal exits or timeouts as successful negatives. All native children were
bounded/reaped; 519 production fatal/assertion sites remained in the preprocessed
RTL. The 300-second host ceiling applied only to the explicitly named later
cases, based on the original 175.457-second normal measurement.

The verifier checks exact case coverage, immutable source snapshots and their
listed host-only/header-comment differences, tool and native binary hashes,
guest input/image hashes, production assertions, topology, exact ledger markers,
return codes, resource bounds and original logs. ELF debug paths vary by output
directory and each ELF is individually bound, not claimed byte-identical; actual
guest images and other guest artifacts match. All intermediate failures and
earlier receipts are preserved. No production RTL source changed after WIP1.

Remote publishing was not attempted by this worker. The next task is the actual
CMU lease/clock-backend integration, not another peripheral performance extension.
The user's dynamic-frequency request is not satisfied by offering a static local
profile; the remaining board document is a dependency map, not that substitution.
