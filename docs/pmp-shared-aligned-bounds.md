# Shared aligned PMP bounds

`PmpChecker(sharedAlignedBounds = true)` shares the high-part comparisons for naturally aligned accesses of 1/2/4/8 bytes or an aligned 64-byte line. Defaults remain generic. The original fixed 4-byte `decodedWordGranularity` branch is retained unchanged.

For a shared high address H, each entry compares H against both complete high bounds, including original bit64. Low-byte tests distinguish first overlap from full coverage. An earlier partial overlap still rejects, even if a later entry covers the entire request or M-mode would otherwise bypass an unlocked permission. Entries, first-match priority, lock/M behavior, and all physical address bits remain intact. Arbitrary decoded boundaries, including malformed reversed test intervals, retain generic byte-range behavior.

The bounded production opt-ins are FloatingPointMemoryPipeline, PendingVirtualStoreProof and aligned NextLineAuthorization. Their existing address construction supplies the natural/line domain. The checker asserts its domain independently of valid. No request ports, state, capacity or cycles were added. This does not authorize an unaligned caller.

## Reproduce the component checks

Use the repository's pinned GSIM toolchain and an unused tag:

```
python3 simulator/gsim/pmp_shared_bounds.py --tag pmp_bounds_check
python3 simulator/gsim/pmp_shared_bounds.py --tag pmp_bounds_run --build-run
```

The default command verifies that each mutant is exactly the current production checker plus its uniquely matched declared expression replacement and class rename. It also checks the frozen byte reference and CSR oracle. The second command builds only four component models: the parameter matrix, actual CSR consumers, and two single-candidate domain-contract wrappers. It records hashes, commands, logs and controls beneath `simulator/build/gsim/<tag>` through the existing repository runner.

- Matrix: entries0/8/16, natural sizes0..3, line size6, candidate/OFF/frozen generic pairing and independent unsigned128 byte oracle. Qualified:61,536 vectors,430,752 decisions,102,800 partial-first decisions,58,660 irregular-region vectors. Generic unaligned/wrapping requests are also checked.
- Six actual source mutants target missing coverage, lost bound64, wrong low coverage endpoints, reversed priority and unconditional low comparison. Six natural and five line controls reach and reject. The last mutant is an identity for line lastByte63, so no line negative is claimed for it.
- Actual MachineSystemUnit CSR publication retains its independent CSR/WARL/lock/TOR oracle and old word consumers, and adds natural/line frozen-reference consumers. Qualified:638 commands,20,441 cycles,326,640 snapshots,40,830 access checks. Observer corruption is explicitly an observer negative.
- Four invalid-domain negatives use single-candidate wrappers. At natural address0 with illegal size4, end15 crosses the fixed eight-byte high block; the specific first diagnostic is `shared PMP endpoint high bits differ`. The initial test run incorrectly expected the older size-domain text first. That failed runner result was retained; only this exact diagnostic expectation was corrected, with no RTL, input or oracle change. Other natural misalignment and both line violations require their own domain messages. A separate constructor negative rejects shared mode without either supported domain.

Existing `PmpChangeBoundary.scala`, `R6PmpCheckerReference.scala`, `pmp_csr_publication.cpp` and `pmp_csr_oracle.h` are reused. The old word-mutant files are refreshed separately to remain exact derivations of the updated checker. This does not change the old word host or oracle.

## Structural and qualification limits

Standalone native RTL has0 new registers and identical ports. At16 entries the old structure has64 wide65-bit order comparisons. Natural sharing has32 wide62-bit order comparisons,32 wide inequalities and64 low3-bit comparisons. Line sharing has32 wide59-bit order comparisons,32 wide inequalities and32 low6-bit comparisons plus reductions. These are expression counts, not a LUT-saving estimate. Standalone assertion inputs are not synthesis constants; only actual caller construction can expose constant low bits. Mapped area, packing, routed timing and board operation remain unmeasured for this candidate.

The combined resource batch separately reuses one CPU model for functional acceptance; component success alone is not ISA or whole-CPU qualification.
