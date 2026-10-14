# Independent review: exact-R16 shared address state

Reviewed 2026-10-14. Verdict: **no blocking defect found for the bounded component-level shared-row qualification below**. This review inspected source, generated products, host, and saved execution evidence; it did not build or execute hardware models or change production source.

## Reviewed identity and execution evidence

- `host.cpp` SHA-256: `ba2b970d3c31f7b8402dc877e2e9c94c9491a57d4d4943682d133cf8367e8fb6`.
- `fixture/R16SharedAddressGsim.scala` SHA-256: `994ff9040a57ad1c49bee99767e0a4cbbb3d15047052fb56d110b350f5c68f9b`.
- Both actual constructor products contain 177 fields and exactly match their corresponding native products. Their sole differing field is `sharedMemoryAddressState`.
- `results-final/off-1.trace` and `results-final/on-1.trace` are byte-identical, SHA-256 `8ca84c19ed8fe35379b2693f18ff4222f6ada4ade97cfbf98a3f07f53a794d3b`. Independently checked 1,930 consecutive cycles and 244 public output scalars per cycle.
- Both final logs are identical, SHA-256 `e0f809006a31b1923636ea394be59515fa714ce116116f3917852fa4ad7b0c1b`.
- Witnesses: two load-plus-two-delayed-store write edges; one atomic exclusion; four positive replay selections, including wrap to row 0; one noncanonical virtual load; one prechecked load; one prepared virtual store retaining VA `0x80401000` while the service maps PA `0x80201000`; 12 killed preparation captures; 52 canceled instructions; 433 row reuses; 157 requests and 157 replies. All 16 rows were allocated. These required witness categories now fail closed in `report()` if absent.

## Canonical authority and masking

The former raw-payload expectation for every virtual load was too strong. In `IntegerBackend.scala:1138-1164`, the selected preparation PA payload can exist independently of a valid matching certificate. A serial virtual head load may launch without that certificate. Its arbitrary stored load metadata is not an authorized PA interpretation.

The source preserves the necessary consumer guards:

- `memoryCanonical` is set to `!virtualized || precheckedLoad || frontierChoice` at actual start (`1715`); the exact profile has no frontier.
- The sole `loadBeat`/`loadLanes` functional consumer, replay selection, requires live, nonpending, ordinary-load class and `memoryCanonical` (`1434-1439`). The initiating checked event also requires a speculative/canonical load start (`1330`, `1708`).
- Kill, retirement and allocation clear interpretation validity (`697-708`, `2874-2878`).
- Store interpretations require store class and prepared/known state: saved-address selection (`913-915`), live-store conflict checks (`1297-1310`), and `PendingStoreProofRobOwner.connect`'s full ordinary-store owner qualification.

Consequently, skipping PA-value comparison for the noncanonical load is correct. The final host additionally checks the live row's canonical-bit transition, validates canonical payloads against independently calculated addresses/lanes, and compares exact replay validity and oldest winner against accepted-owner order and stored expected metadata (`host.cpp:50-66,93-99`). No broad authorization/error masking was found in the public snapshot: valid bits remain compared; only their invalid payloads, plus invalid head-profile payload, are masked.

The replay oracle still observes the DUT's registered check-valid and live/pending/authorization gates. It independently validates the checked owner and payload and chooses the oldest matching accepted owner; it is not a second independent implementation of the entire scheduler or authorization pipeline.

## Service model and limits

The host's fixed successful RW mapping is bounded by explicit observed SATP, PMP cfg/address and data-privilege checks before VM service activation (`host.cpp:92`). Its PA expectation is independent of DUT-generated PA payloads. It is not an Sv39 page-walk or general protection model. Context-epoch invalidation, denied permissions, faults, reordered replies and arbitrary mappings are outside this test.

No write-precheck query or valid frozen-store request occurred in the final trace. Bound pending-store and frozen-proof positive coverage is therefore **not claimed**. Canceled instructions are not refetched; this is backend recovery/reuse evidence, not CPU execution. Memory bytes are updated from actual DUT requests, so this is not a general independent memory-ordering oracle.

The native analysis correctly reports removal of 1,104 declared scalar state bits. This is not measured mapped FF/LUT reduction, electrical fanout, equivalence, timing or board performance. The shared option remains an opt-in candidate.

## Negative-oracle evidence and remaining limits

The separate `../r16-shared-address-lanes-negative-r1` source mutation replaces only the accepted shared load writer's `actualLanes` with `actualLanes ^ 1.U`. Independently verified that this exact replacement explains the complete original/mutant source difference, and verified original/mutant source, final host, compilation receipt, runtime log and trace hashes. With the unchanged final host, the mutant exits 1 with `FAIL independent row payload mismatch`; the saved failure is neither a DUT assertion nor a sanitizer failure. Its runtime receipt SHA-256 is `e58b213a1c6e992220e708ccac4aaccedaafb9d53df5cedf5cb384af7e5320bd`. This establishes sensitivity to an actual incorrect shared byte-lane write, not all possible faults.

No remaining functional blocker was found for the stated narrow claim. The final positive runtime receipt should bind the host, executable, exact constructor products and the final paired logs/traces above; generation/compilation receipts alone do not establish runtime execution. The broader scope exclusions above remain.
