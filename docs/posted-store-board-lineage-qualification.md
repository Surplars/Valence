# Executed CPU / posted cache / coherent home composition

The exact DMA4 Board pair passed the real instruction-driven composition gate
on 2026-10-10. OFF and ON use the same raw guest and complete initial memory.
The observed path is the actual integer CPU, proof transport, private cache,
coherent home, TileLink-to-AXI bridge and modeled DDR. All three positive runs
and both precise oracle mutations reached their intended terminal result.
The separate final-instance audit also passed. These are functional results;
the deliberate delayed write responses are not benchmark measurements.

## Frozen identities and terminal receipts

All paths below are relative to the recovery directory that contains the
worktrees and gate outputs. Every gate receipt contains its complete source,
tool, environment, command and output digests. No historical PASS is inherited.

| Role | Actual source commit | Actual source tree |
|---|---|---|
| Model OFF and ON | `8f9d08a592ac38d35db66b9d260cf24ad9f28b88` | `430b0ef8756c858101cf3299ce913c56e20e209a` |
| Functional host and runner | `0dbe0d116eb4daaad121a7ef6c8a8d97806e6a57` | `a8b38630412a9a83e1c017ca9c6ca4d34c6fb8d8` |
| Final-instance audit | `2bf0f5f292d82d5f1d878dee464e1099d9afa657` | `9b1b788447982bd67337711e4d6eca7de83a2337` |

| Receipt path | SHA256 | Terminal result |
|---|---|---|
| `posted-board-dma4-off-gate-r1/receipt.json` | `2b2c6b41f9eaccf5fd7f020c2c848267ac63a83921bb4119f25b05747915c11f` | `PASS_MODEL_SIDE` |
| `posted-board-dma4-on-gate-r1/receipt.json` | `db74fbe840e2a81099692142e9b9e7ec024a0d69455d041254a8c26d7df162f6` | `PASS_MODEL_SIDE` |
| `posted-board-dma4-host-gate-r1/receipt.json` | `76588f46625286597a006d268d110cbbfa143e4aefe699aaceca208a4cf9ec5a` | `PASS_REAL_BOARD_FUNCTIONAL_ONLY` |
| `posted-board-actual-params-gate-r1/receipt.json` | `91fb4b808b72707f6846ffe83740c1df0bb4eee3480f2ffcb16a606fdcb914e0` | `PASS_ACTUAL_FINAL_PARAMETERS_SAME_GRAPH` |

The model processes exited zero in sessions 51434 and 92311. The functional
process exited zero in session 64614 and the audit in session 64416. The latter
two were both normally polled to their actual terminal exit before releasing
the compilation/runtime slots. The final source collection also includes the
audit files on the functional host branch and this document; that collection
is an archive checkpoint, not a claim that its new commit was the executed
model or host commit.

## Exact profile and instantiated parameter audit

The profile is tied to the independently recorded native OFF reference at
`afe85a27d675199b7e4f32a3a208309fed3f3332`, receipt SHA256
`f24511281d2e87ee89ae9d9371fc6e2d875b1fe8c8fb131aa0503f1e9e252f3d`.
Its full 24-field FpgaNextConfig map and all 134 OooParams values are retained
in each side's `profile.json`. OFF and ON differ only in postedStoreMerge.
The profile checker rejects missing keys and compares every nested value.

The pair has DMA line transfers enabled with four entries, LSU4, D-TLB16,
I-TLB8, PTE4, precheck, prepared stores, store prefetch/MRU, physical load
ingress, older-load retirement and previous fetch packets. Both prechecked
request flow and translated response empty flow are OFF. Actual
fastBufferedStoreRetire is false and registeredStoreResponseOwners is true, so
this gate exercises ordinary store-buffer retirement. RV64GC, issue2,
512-line two-way I/D caches with
64-byte lines, MSHR2/response2/WB2, 128-KiB ROM at 0x80000000, 2-GiB RAM at
0x80200000, 100-MHz CPU and 460800 UART also match. Actual bridge configuration
has four read and two write outstanding slots, maximum burst16, AXI ID4,
unordered responses, and the cache uses TileLink source3/sink1.

The audit reads the actual final objects after the builder's copies and derived
settings. It records all 134 OooParams fields at BoardSocTop, MachinePlatform,
MappedMachineCore, MachineCore, IntegerCore and IntegerBackend. It additionally
records both Board/platform DDR configurations, Board/platform/cache concurrency,
and both inherited/concrete cache TileLink parameter fields. All equal the
exact expected profile. It changes no hardware or input.

The audit re-emits each identical top. Both raw FIR files, including source
locators, are byte-for-byte equal to the corresponding already compiled model:

- OFF FIR SHA256: `30ba381305e8fc756d405768c3b8a308ccc08f538e852fd0155f456dbf92903f`
- ON FIR SHA256: `afbb33cdf6adbb124006761c0454e50c2dc20443a03a03b9b9db6282809bfa11`

The runner also requires the complete graph to match after removal of source
locators; it never erases nodes, ports, registers, connections or assertions.
Actual instance-report SHA256 values are
`4914c6e54ff63d9046a3d40be0d936c922882c98a6c3d3c93387f67e85f115cc`
(OFF) and `467ab60c186c268c4d04ed7803d9c1c9ba7bc5b837c1979ec11bd0f0811a19b5`
(ON).

## Independent guest, authority and byte results

The raw guest contains 65 interpreted instructions, nine stores and two loads.
It dirties two same-set cache ways, performs the third conflict, then makes a
masked same-line update, independent arithmetic, an ordinary load, further
masked updates, a final load and FENCE.I. The same guest bytes have SHA256
`07a91d311b85a07783146b383a67b876ee073170042c2270697bf0cc19f1b358`.
The independent instruction decoder supplies expected addresses, sizes, masks,
data and load values. It does not accept proof bits as the source of authority.

The host ledger follows actual allocation and complete ROB tokens, accepted
head requests, privilege/PMP, proof epoch, cache owner generation/cohort and
reservation, acquired/refilled/installed lines, ordered masked bytes, all
member ACKs/drains, writeback tickets and the complete actual TileLink/AXI tail.
It verifies held request/return payload stability and final responsibility
drain. The environment delays the actual DDR write response by 256 cycles
after WLAST. It does not synthesize CPU proof, cache busy, retirement or owner
responses.

| Case | Result | Cycles | Stores / loads | Accepted proofs |
|---|---|---:|---:|---:|
| old-only reference invocation of the OFF object | PASS | 1363 | 9 / 2 | 0 |
| OFF | PASS | 1363 | 9 / 2 | 0 |
| ON | PASS | 1366 | 9 / 2 | 9 |
| ON with high full-token bit corrupted in the observer | exact token rejection, exit1 | — | — | — |
| ON with final observed memory byte corrupted | exact byte rejection, exit1 | — | — | — |

The old-only invocation is an additional fresh run of the same OFF model,
not a third hardware implementation. The two negative controls each have the
matching mutation event, exactly one intended oracle-rejection terminal and
no success terminal.

ON exercised three posted owner lifetimes and four members, including a
second member on the same live line. Every member was acknowledged and drained,
every owner refilled, installed and released, and all three writeback tickets
completed. The dirty victim's AW fired at cycle406, B at672 and final coherent
ReleaseAck at676. The held B interval was256 cycles. An ordinary load was
blocked for293 cycles; 30 ROB-index reuse witnesses and15 retirements occurred
while the dirty write remained pending. These are required nonzero witnesses,
not inferred properties.

Each positive case compares every guarded dense byte and the union of every
actual/expected sparse DDR word across the complete modeled 2-GiB aperture,
including writes outside the guard. All guest, initial and final snapshots
agree across the three positive cases. Final dense-memory SHA256 is
`9e2ddb37c8c7b5d8bcc0186c1c4778c1514f740a268c4f5ba3c1fa7eba1ad047`;
final full sparse-memory SHA256 is
`215f5747a5b43a2fb12c4f6d10771320e1940eee028cf543227f5c3a6f134750`.

Kernel and flush each retain the full passive bus accounting described in the
design document: channel fire/stall/no-offer conservation, wire versus payload
bytes, pre-edge outstanding histograms, carry-in/out, concurrent ownership,
same-edge R/W transfers and latency/backpressure/empty-window separation.
Those counters use this deliberately delayed functional environment.

## Preserved earlier scope and remaining limits

The initial `25a8c3f` model pair had DMA line transfers OFF and one entry.
The first guest/host gate at `8cc4bb8` failed the required ON load-blocking and
retirement/reuse coverage; its traces and failed receipt remain preserved.
The independent guest reorder at `bfbeff4` passed against those same DMA1
objects, with receipt SHA256
`8142d3b271f26618f7a503fce803cfea107adf552924b981d6faa2845fc39222`.
These outcomes are distinct from the newly emitted DMA4 pair. The complete
DMA1 package is archived separately; it is not relabeled as DMA4.

This composition guest exercises physical integer stores and ordinary loads,
dirty eviction, same-owner merging, real delayed write completion and FENCE.I.
It does not independently establish every virtual fault, APLIC, FP/atomic,
recovery or context-transition scenario. Those CPU-only and cache/home-only
qualifications keep their separate scopes and exact sources. No new physical
throughput improvement is claimed here. Existing benchmark guest/kernel bytes,
their original memory timing and full correctness checks must be preserved for
the separately bound OFF/ON performance runs. Posted-store merge and the
published return-flow option both remain default OFF.
