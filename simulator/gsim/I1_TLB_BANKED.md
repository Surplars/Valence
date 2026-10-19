# Explicit 16/32-entry I1 prepared TLB proof banks

Base: `42b903af77824518afde3f0649808dd5b0a7cf2f`. This is a local candidate,
not a full CPU, Linux, board or routed-timing qualification.

## Candidate and recommendation

`FiveStageConfig.bankedTlbProofs` defaults to **false**. For an explicitly
selected FPGA8/Sv39 profile, `--tlb=16 --banked-tlb-proofs
--fast-data-translation --indexed-data-proofs` enables two eight-entry proof
banks. `--tlb=32` enables four. Existing 4/8 prepared paths and generic unbanked
16/32 fallbacks remain available. Core ADDR/MEM and compressed-fetch dual
candidates stay enabled for the banked modes; no optimization is disabled to
make a larger configuration elaborate.

Recommend **16 entries per ITLB/DTLB** as the first common-platform candidate.
It covers the measured 16-page working set, retains the same longest generic
LUT depth as eight entries, and costs much less than 32. Keep 32 available for
workloads that demonstrate a larger translation footprint. This choice is a
resource/depth tradeoff; physical implementation must still establish timing.

Every bank prepares PA and permissions before the bank/candidate selection.
The D path copies its source PTE flags into the existing read/write proof
metadata at authorization. It still checks current privilege, SUM, MXR, A/D,
read/write/atomic requirements on every offer. Source-row ownership is retained;
replacement clears every proof belonging to that source, row-zero replacement
clears all potentially dominated proofs, and invalidation clears every proof.
Assertions check a granted proof's live source validity, exact PA and flags.
The bank flag adds metadata, not TLB mappings, request owners, PTWs or MSHRs.

SATP/PMP changes use the existing CSR invalidation contract; the MMU does not
silently invent autonomous epoch tags. A walk crossing invalidation cannot
repopulate a proof. ASIDLEN=0, global SFENCE over-fencing, Svade, addresses and
architectural behavior are unchanged. V/H is not advertised or implemented.
A later H design needs explicit VS/G/VMID context, guest-fault provenance and
HFENCE-dependent proof invalidation before reusing these proof banks.

## Same-trace 4 KiB capacity evidence

Full results: [576-row CSV](inorder/tlb_banked_capacity_20261019.csv).
Fixture semantics: [capacity fixture](I1_TLB_CAPACITY.md).
These are **MMU-interface CPU-clock-domain cycles**, with actual three-level
4 KiB PTE walks and a fixed two-cycle physical service. They are not a complete
CPU instruction benchmark. The I/D walkers and final D demand share one
physical D owner. I+D competition is bounded overlap, not saturated fetch.

Warm sequential load, three identical sweeps:

| Total pages | Requests | 4-entry cycles | 8-entry cycles | 16-bank cycles | 32-bank cycles |
|---|---:|---:|---:|---:|---:|
| 1 | 3 | 12 | 12 | 12 | 12 |
| 4 | 12 | 48 | 48 | 48 | 48 |
| 8 | 24 | 624 | 96 | 96 | 96 |
| 16 | 48 | 1248 | 1248 | 192 | 192 |
| 32 | 96 | 2496 | 2496 | 2496 | 384 |
| 64 | 192 | 4992 | 4992 | 4992 | 4992 |

A fitting sequential warm trace has zero PTE reads and zero slow admissions.
A thrashing load trace has three PTE reads per request. At 16 pages, moving
4/8 to 16 changes 144 PTE reads to zero and 1248 to 192 cycles (6.5x this
translation trace). At 32 pages, only 32 fits and obtains the same ratio.

The same 16-page copy trace (96 D requests) takes 2496/2496/384/384 cycles for
4/8/16/32, with 288/288/0/0 PTE reads. With concurrent I requests it takes
2592/2592/384/384, and I PTE reads are 144/144/0/0. Store results match load
for this fixed service. Cold misses still pay the three-level walk. All
capacities still thrash at 64 sequential pages or on multi-page VPN stride
1024 conflicts. Banking does **not** make the MMU nonblocking or solve hashing
conflicts; no claim that 32 is universally faster is made.

## Generic structural mapping, not physical timing

ABC six-input LUT mapping of each complete single-translator test harness,
including its PMP logic. All sizes use the same dual-candidate/atomic interface;
D includes retirement overlap. This is not the entire core resource count.
Verification layers are excluded from synthesis, but enabled for simulation.

| Entries | I LUT6 | D LUT6 | I+D FF bits | I max LUT levels | D max LUT levels |
|---|---:|---:|---:|---:|---:|
| 4 | 1305 | 1971 | 2298 | 9 | 9 |
| 8 | 1630 | 2336 | 3462 | 10 | 10 |
| 16 banks | 2353 | 3607 | 5942 | 10 | 10 |
| 32 banks | 4844 | 6516 | 10822 | 11 | 10 |

16 uses 1994 more I+D LUT6 than 8 (+50.3%). 32 uses 5400 more than 16
(+90.6%) and adds one generic I logic level. D's late candidate-select to PA
path is 6/8/4/4 LUT levels for 4/8/16/32; I's is 3/5/3/4. Full candidate
address to PA is I=5/6/7/8 and D=7/10/10/10. All are unweighted mapped-graph
levels; placement, fanout, routing, carry/RAM mapping, clock delay and MHz are
unqualified. [Full structural summary](inorder/tlb_banked_structure_20261019.json).

Reproduce mapping by lowering the same `FiveStageTranslationHarness.fir` with
firtool `--default-layer-specialization=disable --disable-all-randomization
--lowering-options=disallowLocalVariables,disallowPackedArrays`, sv2v
`-DSYNTHESIS`, then Yosys `synth -flatten -noabc; abc -lut 6; clean; stat;
ltp -noff; write_json mapped.json`. The bounded local run used existing Yosys
0.52/ABC and firtool 1.135.0. Analyze emitted JSON with
`inorder/tlb_banked_structure.py --mapped-root DIR --output summary.json`.

## Verification performed

- `OrbitalI1.test.compile` and all 18 `FiveStageConfigSpec` tests passed.
- 4/8/16/32 I and D GSIM models passed the independent Sv39/PMP oracle,
  including all 256 PTE flag patterns, precise page/access faults, Svade,
  superpages, noncanonical/high PA, SUM/MXR/MPRV, SFENCE during a walk,
  source-row eviction and dominant-superpage invalidation, stalled offers and
  responses, dual-candidate unselected noise and D retirement replacement.
- 16/32 were rerun after adding all-bank warmed privilege/SUM/MXR changes and
  cached PMP revoke/restore checks. Each owner passed with proof/source
  assertions enabled. A final same-RTL run also evicted every nonzero source
  row (15/31 rows, including upper banks), with both D proof classes checked
  against a remapped PA. The final totals are I16=559, D16=977,
  I32=799, D32=1297 transactions. Negative page-fault and proof-count oracle
  mutations were rejected.
- The independent native RTL capacity fixture passed 144 rows per profile,
  576 total, plus 11,093 checked responses per profile. Every profile rejected
  the deliberate wrong-PA oracle and observed at most one physical D owner.
- No Verilator, Vivado, bitstream, long OS boot, tool installation or remote
  push ran. Every build/test was bounded and guarded by a 4 GiB free-disk floor.

`inorder/tlb_banked_acceptance.py` reruns the finite single-MMU checks using
explicit existing Mill/GSIM/C++ paths. The local GSIM binary was the previously
qualified restored build (SHA256
`0e11f2d6b6eadeb2310084817660cf4c38097307344eacf13fc1d82df4f97118`),
not an assertion that the upstream checkout is unmodified. The independent
Icarus capacity oracle is a second simulator check of the banked RTL.
