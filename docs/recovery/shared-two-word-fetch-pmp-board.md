# Experimental shared two-word fetch PMP board wiring

This is a newly reconstructed, default-off candidate, not a restoration of lost
source bytes. It extends the separately checked component through ordinary
constructor arguments only. `OooParams` remains a 178-field product and
`FpgaNextConfig` a 95-field product. No frozen export, CLI profile, manifest or
physical recipe is changed.

## Constructor graph

`FpgaNextSocTop.sharedTwoWordFetchPmp` → `FpgaNextConfig.managedBoard` →
`BoardSocTop.sharedTwoWordFetchPmp` → `MachinePlatform.sharedTwoWordFetchPmp` →
`SynchronousFetch` and `InstructionTranslationAdapter`.

The separate standalone `FpgaIntegerCore` wrapper forwards the same default-off
argument to its `SynchronousFetch`. It is not an intermediate board constructor.

Native MAC, raw clock handoff, BSCAN chain 2 and RAM-loader choices remain those
of the explicit `ThreeProofRowNativeProfile` constructor used for this experiment.
The cache `splitCacheableBounds` candidate remains disabled. This experiment does
not inherit the older profile's qualification merely by using its configuration.

## Reproduction

Source `scripts/cloud/env.sh`, then invoke:

```
mill -i IonSoC.test.runMain ooo.SharedTwoWordFetchPmpBoardMain FRESH_DIRECTORY default
mill -i IonSoC.test.runMain ooo.SharedTwoWordFetchPmpBoardMain FRESH_DIRECTORY off
mill -i IonSoC.test.runMain ooo.SharedTwoWordFetchPmpBoardMain FRESH_DIRECTORY on
```

Use a different fresh directory for each invocation. The independent exporter
writes complete CHIRRTL and an `experiment.json` with actual constructor audits,
full core/profile values and field order, and raw/hardware CHIRRTL hashes. It
rejects any unexpected helper count (zero for default/off, two for on), changed
core values, cache range enabling, or missing native MAC/BSCAN/loader instances.

`simulator/gsim/shared_two_word_fetch_pmp_board_audit.py ROOT` compares archived
`before/default/off/on` exports and verifies the `after-source-sha256.json`
snapshot against the current source. `before-source-sha256.json` preserves the
prepatch source hashes. The comparison strips only source-location annotations;
all hardware IR remains in the comparison. Raw hashes are also retained.

## Limits

The board export itself is a constructor and complete-CHIRRTL check. It is not
enabled-caller behavioral qualification, CPU execution, board testing, synthesis,
timing, or physical qualification. The separate bounded adapter check below has
its own narrower evidence. No Verilog or physical recipe is emitted. The separate
component proof retains the baseline's 56-bit physical maximum-NAPOT contract;
an unbounded byte oracle would differ above that domain for all-ones raw54 NAPOT.

## Short configured instruction-adapter dynamic check

The separate `SharedTwoWordFetchAdapterGsimMain` now uses the complete current
178-field core configuration from `ThreeProofRowNativeProfile`, checking its
values, the 95-field profile, and both field orders against the experimental
board export. It selects the effective adapter tuple from the current native
caller definition: p.copy(machineSystem=true, virtualMemoryLevels=3, pmpEntries=16).
After construction, it records and checks both actual adapter parameter products,
option flags and two-word port widths against that tuple. This is a configuration
binding check; it does not run the exported board. It pairs real `InstructionTranslationAdapter` instances with the
option OFF and ON under identical input signals. Neither instance drives the
other's translation or memory responses.

Run with the isolated reviewed repaired GSIM binary (SHA-256
`f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116`):

```
python3 simulator/gsim/shared_two_word_fetch_adapter.py \
  --tag FRESH_TAG --gsim /absolute/path/to/repaired/gsim \
  --board-export /absolute/path/to/on/experiment.json
```

The first bounded run passed: 20 owners accepted and retired, 19 simultaneous
old-reply/new-request handshakes, 12 translations, 12 physical transactions,
60 held-reply cycles, 31 held-request cycles, 120 live-PMP churn cycles,
182 live-context churn cycles, two reset epochs, and four idle unowned replies
rejected. Translation access-only/page faults and physical error/page metadata
were independently checked. ASan/UBSan and both observer-negative controls passed.

Every complete OFF/ON adapter IO bit is compared each cycle, including invalid
payload bits under deterministic simulation initialization. This is implementation
equivalence, not a claim that invalid payload has architectural meaning. The
independent byte-PMP and memory/owner oracle checks only offered/owned transactions.
The reused stream enables two raw PMP entries (TOR/NA4); the remaining fourteen
are OFF. The separate component proof covers wider PMP state combinations.

The adapter has no cancellation port. The test discards an accepted owner with
whole-interface reset and rejects stale/unowned replies while idle; it does not
invent a tagged cancellation or late-reply contract. Live CSR churn is adversarial
isolation stimulus, not permission to violate the architectural drain requirement.
The negatives inject observer mismatches, not production-source mutations.

The receipt binds source hashes, the repaired binary, compiler, input board
export, generated FIR/C++/headers, executable and logs. This closes only the bounded instruction-translation-adapter gap.
At this adapter-check stage, `SynchronousFetch` enabled behavior remained open;
the separate bounded frontend check below addresses it. Full-board/CPU execution
and physical qualification remain unverified. No main GSIM installation is replaced.

## Short configured SynchronousFetch dynamic check

`SharedTwoWordFetchFrontendGsimMain` pairs real OFF/ON `SynchronousFetch`
instances using the current native frontend tuple: 16 sets, two words, registered
window, address-before-PMP, and qualified compact keys. The complete core/profile
values and field order match the experimental board export. All 16 actual retained
frontend constructor fields are read back and checked; only the shared-PMP flag
differs. This checks configuration binding, not execution of the exported board.

```
python3 simulator/gsim/shared_two_word_fetch_frontend.py \
  --tag FRESH_TAG --gsim /absolute/path/to/repaired/gsim \
  --board-export /absolute/path/to/on/experiment.json
```

The bounded run passed 18,717 cycles: 11,563 valid instructions, 2,742 requests,
1,273 stalled-request cycles, 182 stale replies, 1,300 concurrent fill/hit cycles,
1,296 reply/new-preparation turnovers, 885 PMP-denied masks, 2,112 straddles,
3,501 access faults and 588 page faults. All 16 sets, both ways and all three
query offsets were covered. It also observed 364 revocable and 153 irrevocable
preparation-cancellation witness cycles, 150 context changes, 148 invalidations
and two reset epochs. Cancellation counters count qualifying cycles, not unique
canceled owners. Cold/hot cache, permission/context changes, full64 wrap addresses,
backpressure and actual enable/pause/invalidate/suppress cancellation inputs use
the existing independent full64 cache/owner/PMP oracle.

Complete deterministic OFF/ON IO equality and the independent valid-transaction
oracle passed under ASan/UBSan. The two negatives are observer injections, not
production-source mutants. Invalid payload is compared only for implementation
equivalence. One raw PMP entry is active in this fixture; broader state coverage
remains the separate helper proof. Whole-interface reset explicitly discards the
external response obligation; no late-reply cancellation protocol is invented.

The receipt binds production/test sources, the input board export, the isolated
repaired GSIM binary, all generated FIR/C++/headers, executable and logs. Its scope
is this bounded configured frontend pair. The separate adapter pair and frontend
pair do not establish combined full-board/CPU behavior or physical qualification.
