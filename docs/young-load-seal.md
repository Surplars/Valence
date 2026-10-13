# Younger-load posted-seal deferral

`postedYoungerLoadSealDeferral` is an explicit default-OFF experiment. On the
qualified, unchanged COPY guest and service law, Bare completion falls from
198642 to 179571 cycles (9.6007% fewer cycles, 10.6203% higher payload rate).
Sv39 stays at 191618 cycles. This is measured CPU execution, with original
architectural, independent-byte, accounting and service checks retained.

## Production boundary

The stateless helper defers only selected-memory intent sealing for a pending,
live, full-token-qualified, nonhead ordinary physical load with legal aligned
RAM/PMP authorization while posted responsibility remains. The head must be
nonmemory or an ordinary non-atomic store. Actual-head loads, AMO/LR/SC,
system/hard seals, refill exclusion, recovery, context and interrupt guards keep
their original boundaries. Enabling requires posted store merging, registered
memory addresses and no proof frontier.

The original actual-head store proof, LSU/store-buffer completion and retirement,
cache ACK and original owner/cohort/reservation/install/drain duties are retained.
A load still cannot issue with posted responsibility outstanding. No register,
payload port, reverse cache lookup or early ACK was added.

## Qualified results and limits

| Gate | Qualified result |
|---|---|
| Real helper and real instruction decode | 43 independent guard cases |
| Real posted-store owner component | 11 positive cases; 3 RTL assertion controls |
| Real directed CPU OFF/ON | 1801 cycles each; 16 actual-trace mutation controls |
| Original-law COPY | Both modes and all 105 original fields pass |
| Original COPY controls | Read, final-memory and trap corruption rejected |
| New observation controls | Join/newLine confusion, wrong cohort and wrong slot rejected |
| Same-object short NEMU/PMP | 7 runtime cases/controls, exact original-A stdout parity |

The real directed trace shows U `(index=10, tag=58)` at age 4 behind actual-head
S1 `(6,54)`: OFF seals, ON defers, and the load does not start. ON subsequently
joins S1 into S0's original cohort before the refill offer. Full tags, circular
ROB membership, selected/unselected head loads, U/Y/V old/new bytes, retirement
ordering, wrap, killed-load index reuse and registered recovery hard seal are
checked. CPU AMO/LR/SC execution is not claimed; their rejection is covered by
the real decode/helper component.

Bare has 162 real joined members, 162 actual cache ACKs and 162 installed-member
drains across 49 complete owner contexts (120 ROI, 42 pre-ROI, zero tail). Bare
ROI/tail cycles are 171636/7935 versus 190705/7937. Whole-run accepted, physical,
physical-reply, cache-reply and completed counts remain 49157 each; local/store
buffer accepted/replied counts remain 24577 each. Prefetch scheduling and refill
classes also change, so the cycle gain is not assigned one-for-one to joins.

## Preserved failure and corrected observation

The original ON Bare host failed with `ledger retired owner lacks refill/install
completion`. Its receipt and logs remain in the evidence archive. The production
`demandAlloc` observation also pulses on an accepted posted join, although the
MSHR state allocates only on accepted `newLine`; the old host invented a second
owner. This patch does not change that DUT pulse.

The separately frozen corrected host contains the original 17 files, only two
ledger hookups changed, plus one read-only helper. It excludes a join from
new-MSHR accounting only after real acceptance, original full-token store start,
full physical address/context/root/epoch/reservation and the original live MSHR
are proven. It checks the next-edge original seven-field pending tuple,
reservation and serial, excludes phantom free-slot allocation and permits legal
phase advance. Every member independently conserves ACK/drain/release. Original
retired/refill/install and raw attach-exclusion assertions remain intact. The
next-edge check does not inspect every byteValid bit; unchanged complete COPY
byte checks retain overlay-data responsibility.

With this observer, A OFF stdout, AXI TSV and supply TSV are byte-identical in
both modes. The frozen observer phase receipt records its last positive stage;
the final qualification separately confirms all four cases and all seven
controls. The failure is not replaced by a success claim for the old host.

## Integration and reproducibility

Execution was qualified on `767e7683f3d6f5bd1fee257735505b353500d2a5` plus the
frozen young-load change. This source integrates it onto published MAC commit
`e4a823f5e08cb17042d515e1ac62b0c55e16cb78`. All 136 other core Scala files are
byte-identical to that tested source; only BoardSocTop/FpgaNextConfig add the
preserved MAC default-false plumbing. IntegerBackend, OooParams and the helper
are byte-identical to the executed candidate.

Current constructor shape is 173 core fields and 90 profile fields. The profile
ends in `triSpeedRawClockHandoff`, then `postedYoungerLoadSealDeferral`; the core
has only the latter new field. Historical A172/88 and exact64 retain every old
ordered value through explicit named-false projection. Both historical Python
entries compose the MAC and seal source checks; the original MAC raw entry
remains executable with seal deferral OFF. Historical manifests/receipts remain
unchanged. No field is inferred from arity.

The merged source passes 16 configuration tests and real in-memory native-board
construction for young ON/MAC OFF and young OFF/MAC ON, checking complete actual
core/backend parameters. Its full young-ON configuration equals the tested
configuration after removing only the named MAC-false platform field. No new
CPU model or simulation was run for this integration; CPU identity requires MAC
raw handoff OFF. MAC-enabled CPU execution remains untested.

Run the four focused Scala configuration suites in
`PostedYoungerLoadSealConfigSpec`, `NearTermAConfigSpec`,
`RetirementIntentBoardConfigSpec`, and `MacRawHandoffEntrySpec`.
`ooo.YoungLoadSealMergedGate <fresh-directory>` performs in-memory construction
without exporting native RTL. Python exporter/source bridge tests live in
`fpga/next/test_posted_younger_load_seal_export.py`,
`fpga/next/test_young_load_seal_source_bridge.py`, and
`fpga/next/tests/test_mac_raw_handoff_entry.py`.

The complete portable host/data fixtures and their hash checker are described
in [FIXTURES.md](../simulator/gsim/young_load_seal/FIXTURES.md). Relative source
hashes, final qualification and integration gate hashes, original failure hash,
and recovery archive identities are in
[the evidence summary](evidence/young-load-seal-e4a-r1.json).

Only the original phase/service law is qualified. No second-law/phase sweep,
full ISA/Linux run, tag exhaustion or exhaustive CPU fault/system matrix was
performed. The 270-module CHIRRTL comparison shows only IntegerBackend changed,
with identical declared state/interfaces; its 111-node, depth-22 expression cone
is not mapped fanout or physical timing. Mapped STA, routed timing and board
hardware remain unverified. The feature stays OFF by default.
