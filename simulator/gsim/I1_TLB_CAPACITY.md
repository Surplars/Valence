# I1 4 KiB TLB capacity fixture

`inorder.I1TlbCapacityMain` and `harness/i1_tlb_capacity.sv` are a short,
independently checked MMU-interface trace fixture. They instantiate the real
I/D `FiveStageAddressTranslation` modules. The fixture copies the CPU-private
three-user arbitration in `FiveStageCachedCore`, with `coherentBandwidth=false`:
rotating grant, sticky stalled offer, and **one physical D owner** shared by D
demands, D page-table walks, and I page-table walks. Instruction physical data
uses a separate one-owner endpoint, as in the core. It does not substitute the
different `I1SharedDataArbiter` owner FIFO for this private arbitration.

## Scope and counters

Every reported cycle is a **CPU-clock-domain MMU-interface trace cycle**. This
is not a complete CPU program, retired-instruction IPC, cache/DDR benchmark,
Linux test, board result, routed timing result, or an MHz claim. The fixed
physical responder returns a beat two cycles after acceptance. Performance
phases have no synthetic READY stalls; correctness phases add deterministic
request and response stalls. Both responder ports assert at most one owner.

The fixed configuration is FPGA8 timing cuts, Sv39, fast I/D translation,
direct fast D issue, indexed D proofs, four PMP slots with one active TOR range,
no data reply handoff, and no retirement overlap. Banked proofs are explicitly
selected for 16/32 entries. All profiles use exactly the same service law and
request traces. The source configuration's default for banking remains off.

- `d_hit`/`i_hit`: raw RTL hit pulses, including slow TLB lookup hits, even when
  subsequent permission checks fail. These are not fast-path counts.
- `*_slow_admission`: accepted requests without a same-edge hit pulse. Thus
  `accepted - slow_admission` is the independently counted fast admission.
- `*_miss`: raw canonical translated lookup miss pulses.
- `*_pte_reads`: accepted physical read-only PTE beats, attributed to I or D.
- `*_physical`: accepted final physical demand beats.
- `cycles`: ticks from immediately after the phase snapshot until all of that
  phase's requests and replies are drained. Invalidation/setup ticks are excluded.

## Matched traffic

There are 144 result rows per configuration: cold/warm × 1/4/8/16/32/64 pages ×
sequential/conflict stride × load/store/copy × D-only/I+D competition.

Every mapping is an actual three-level Sv39 **4 KiB leaf**, not a superpage.
The sequential VPN stride is one. Conflict VPN stride is 1024 (4 MiB virtual
byte stride), colliding under the current 4/8/16/32-entry XOR hash. Physical
pages remain distinct and contiguous. Cold runs one sweep after invalidation;
warm runs three sweeps with no intervening fence. Each row starts from a fresh
page-table setup for its cold/warm pair, so changing capacity does not change
trace, PTE flags, physical mappings, or service delay.

A load/store sweep accesses offset zero in each page. Copy loads page `i`
offset zero, waits for the independently checked returned value, then stores
that value to page `(i + N/2) % N`, offset eight. N is the **total VPN working
set**, not N source plus N destination pages. For N=1 the two words are in the
same page. This is a scalar copy-shaped translation trace, not full-page memcpy.

In competition mode, one I request is offered alongside the first D operation
for each page; both are drained before the next page. Copy's second/store
operation has no additional I offer. This is bounded overlapping I/D demand,
not a continuously saturated fetch pipeline.

## Independent checks

The SV oracle walks its own explicit page-table memory from satp, decodes the
architectural PTE bits independently, evaluates one TOR PMP region, and checks
exact physical addresses, operation/data/mask, load/copy data, page-versus-access
faults, and exact response ownership. Actual memory effects depend on actual
accepted bus operations, not expected architectural outcomes. Demand fires are
independently checked for PMP permission before they can affect memory.

Directed checks include R/W/X/U/A/D, reserved W-without-R, SUM/MXR/privilege
changes without a fence, noncanonical addresses, instruction U-page rejection,
SFENCE remapping, a distinct satp root/PA, invalidation during a walk, cached
PMP write-proof revocation and restoration, PTE/physical bus errors, source-row
replacement, and concurrent I+D under backpressure. Offers and responses must
remain stable under stalls. Context-root/PMP changes explicitly invalidate,
matching the CSR-to-MMU contract; the MMU has no autonomous satp/PMP epoch tag.

The Python checker requires exact demand/response accounting, three accepted
PTE reads per valid 4 KiB miss, hit+miss=accepted on these legal performance
traces, zero warm PTE misses for sequential working sets fitting the selected
TLB, and **zero warm slow admissions** in those fitting cases. It also runs a
negative test that perturbs the independent expected physical address and must
be rejected. This fixture complements the existing exhaustive single-MMU
`five_stage_translation.cpp` oracle; it does not replace superpage, atomic,
split-candidate, full PMP-bank, or complete CPU architectural coverage.

## Reproduction

Compile `OrbitalI1.test.compile`, obtain `OrbitalI1.test.runClasspath` using
Mill `show`, and pass the resulting JSON array or colon-separated classpath to:

```
python3 simulator/gsim/run_i1_tlb_capacity.py --classpath /path/to/classpath.txt
```

The default profiles are `4:off,8:off,16:on,32:on`, with output under
`build/gsim/i1-tlb-capacity`. Tools default to PATH. Tool paths may be supplied
with `--java`, `--firtool`, `--iverilog`, and `--vvp`. The runner does not install
tools or invoke Verilator/Vivado. Every child is bounded to 1200 seconds, and
it checks the hard 4 GiB free-disk floor before and during execution. Outputs
include source/RTL/binary hashes, exact commands, logs, `capacity.csv`, and
`receipt.json`. Assertions are explicitly enabled during firtool lowering.
