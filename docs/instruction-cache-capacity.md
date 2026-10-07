# Bounded instruction-cache capacity experiment

## Scope and configuration

The capacity-only experiment keeps `staged-fetch-feedback`, issue width two,
RV64GC/FPU hardware, 100 MHz CPU, UART 460800, two data-cache ways, and 2 GiB DDR.
It compares 8 versus 32 instruction-cache lines: 512 B versus 2 KiB, always two
ways and 64 B lines. The default remains **8 lines** in every board constructor
and exporter. The isolated historical cache test still defaults to 16 lines.
The accepted board range is powers of two from 4 through 256; zero cannot silently
disable the instruction cache.

The instruction-prefetch request flag remains enabled, but effective line
prefetch is **disabled** for the production two-word fetch packet. The platform
requires four-word fetch for line prefetch. Do not conflate this with data prefetch.

Reuse exact archived firmware bytes. Existing CoreMark firmware is uncompressed
RV64IM code running on RV64GC hardware; the completed matched RVC compiler experiment is a
separate software comparison. The turnover-only candidate remains a separate
profile, `staged-fetch-turnover`; it is not the capacity-only baseline.

## Production activation

The native managed production entry point is `ooo.ManagedBoardSocMain`.
Its optional final argument is instruction-cache line count, default 8. An explicit
32-line export command is:

```sh
mill -i IonSoC.test.runMain ooo.ManagedBoardSocMain \
  build/managed-capacity32-fresh 100000000 staged-fetch-feedback 460800 \
  rv64gc 50000000 50000000 250000000 2147483648 32
```

This command documents activation; it is not a claim that the export, synthesis,
implementation, or board run has occurred. `EthernetSocTop` and the final optional
argument of `EthernetTimingMain` also pass through the capacity explicitly.
The generic `BoardSocMain` exporter retains its prior interface/default.

**A capacity change requires fresh full RTL implementation and timing/resource
signoff. It is not a ROM ECO.** No old receipt, old signoff guard, or profile allow
list was relaxed. In particular, the existing `stage_native_rv64gc.py` checks are
not evidence that a new profile/capacity is approved for the board.

## Focused verification

`ooo.InstructionCacheCapacitySpec` elaborates the native managed RV64GC board
with 8 and 32 lines, verifies two SRAMs of 512 bits by 4 or 16 sets and corresponding
56- or 54-bit tags, checks the 2 GiB bound, checks Ethernet wrapper pass-through,
and rejects unsupported board counts. This is a configuration/elaboration proof,
not clock-domain or board validation.

```sh
source scripts/cloud/env.sh
mill -i IonSoC.test.testOnly ooo.InstructionCacheCapacitySpec
python3 simulator/gsim/instruction_cache_geometry.py --tag UNIQUE --lines 8 32
```

The width-two GSIM tests independently cover burst fills, one packet/cycle hits,
held hit/refill replies, real third-conflict LRU eviction, invalidate and
invalidate-during-fill, denied last refill beat with precise fallback/error
lanes, PMP-limited fallback, and refill/fallback TL source namespaces. A negative
run corrupts returned data and must be rejected. The runner verifies emitted SRAM
and tag geometry and saves source/FIR/executable/log hashes in each receipt.

Conflict stride is `64 * (testedLines / 2)`, derived independently of the DUT.
The test memory range expands for accepted larger geometries and the instruction
oracle mixes high address bits. Optional geometry edges are supported by the
runner but are **not part of the default executed matrix**; do not claim them
verified merely because argument validation accepts them.

## Physical risk

32 lines quadruples instruction data storage from 4096 to 16384 bits and increases
sets from 4 to 16 while retaining two ways. Tag width decreases by two bits.
These are logical sizes, not measured LUT/FF/BRAM utilization. Memory inference,
set-index muxing, tag comparison, place/routing, frequency and power must be
measured by fresh synthesis/implementation. No physical timing or resource result
is inferred from GSIM cycle improvements.

## Final evidence status

`build/gsim/icache-geometry-capacity-final-20261007-w2-n8/` and `-n32/`
contain passing final geometry receipts, sanitizer logs and rejected negative
data-corruption controls. `ooo.InstructionCacheCapacitySpec` passes 3/3 tests.
The managed-board tests explicitly pass 8 and 32; the omitted-argument default
of 8 was source-reviewed, not separately exercised by a default-omission test.

The capacity-only same-BIN CoreMark comparison is 834653→586310 ticks; see
`frontend-performance-diagnosis.md` for traffic attribution and the small DDR
write/copy regressions. Functional tests and logical geometry do not establish
FPGA memory inference, frequency, power or timing closure.
