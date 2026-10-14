# Exact aligned-word PMP comparisons

The optimization is an explicit `PmpChecker(decodedWordGranularity = true)` constructor option. It requires the fixed aligned four-byte access mode. Only the existing aligned-word branches in SynchronousFetch and InstructionTranslationAdapter enable it. Other constructors retain the original algorithm, including partial-overlap rejection.

For an active decoded TOR/NA4/NAPOT region, low bits are `00` and inclusive-end bits are `11`. Every intersecting aligned four-byte word is therefore entirely covered. Per entry, compare the full request word index against both full decoded word bounds; retain bit 64 of each bound, all address high bits, first-overlap priority, access permission, lock and M-mode rules. No entries, physical address width, owner tags, ports, registers or cycles are removed. Empty/reversed TOR stays inactive. Region publication remains atomic with the original CSR producer.

Pre-mapping native RTL has 32 unsigned 63-bit ordering operations per aligned 16-entry checker instead of 64 unsigned 65-bit operations. This is a structural count, not a mapped LUT/timing result. Adjacent words keep independent first matches and may have different permissions. No adjacent-word sharing or physical-address narrowing is included.

## Reproduce the focused component gate

With the repository's pinned GSIM toolchain active:

```
python3 simulator/gsim/pmp_word_granule.py --tag pmp-word-check
python3 simulator/gsim/pmp_word_granule.py --tag pmp-word-check-run --build-run
```

Preflight checks each source mutant is exactly one declared replacement in the current production checker and checks the frozen byte-range reference hash. Build/run uses two component models: a 0/8/16-entry, two-word matrix checked against an independent byte-interval oracle and frozen reference; and the real MachineSystemUnit CSR publication fixture. Six actual source mutants test high-address truncation, reversed priority, ignored lock, wrong write permission, inactive regions and truncated high region bounds. No production mutation is applied by the runner.

Original qualified results: 31,456 word vectors / 188,736 decisions / 1,117 differing adjacent-word permissions. The actual CSR gate covered 20,441 cycles, 638 commands, 326,640 entry snapshots, 40,830 original access checks, 793 flush holds and 1,119 completion holds. Six source mutants, three input-contract controls, a constructor-domain control and a CSR observer corruption all rejected.

The three malformed-input contract logs first abort in a co-instantiated mutant's copied same-source assertion. They establish shared-contract rejection but do **not** isolate the candidate's assertion. The runner preserves this attribution. The standalone candidate assertions are visible in source/native RTL; no claim of an isolated candidate-only negative is made.

The first historical host compile failed on a C++ narrowing literal and was corrected with an unsigned-long-long suffix; no RTL or oracle algorithm changed. The original failure and exact qualification artifacts were retained outside the source tree. Component success alone is not whole-CPU or physical qualification.
