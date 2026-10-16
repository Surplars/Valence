# Cloud reconstruction, 2026-10-16

The executor workspace was replaced. The remote `dev` baseline
`223453bae0185dcc59b9ea5414ddb266e1f5af93` was cloned anew. The former unpushed
`685400dd` candidate and same-disk bundle were not recovered. These changes are
new implementations with fresh validation, not byte-identical restoration.

## Scope

- Combine all enabled registered request sidecars in one typed FIFO. Preserve
  native request/metadata fields, queue depth, non-flow/non-pipe behavior and
  physical response ownership. Canonical/frozen metadata is independent of
  posted authority.
- Add default-off shared two-word fetch PMP checks and guarded callers.
- Add default-off split cacheable aperture bounds; unsupported geometries retain
  the old arithmetic.
- Retain a source-only patch and focused tests for pinned GSIM input width,
  padded Vec interfaces and byte-range state initialization. Use it explicitly
  in an isolated GSIM checkout, without replacing the original pinned binary.

## Evidence and limits

Fresh baseline compilation passed (209 main sources). Reconstructed main
compilation passed (210 sources); focused Scala suites cover queue optional
configurations, PMP guards and cache range structure. Cache interval-partition
checks and an endpoint mutant first established mathematical-model evidence.
The later fresh emitted-RTL SAT qualification is recorded below.

GSIM fixes passed six focused normal/RANDOMIZE_INIT sanitized executions and
seven upstream FIR emissions with six runtime harnesses. Final tested binary
SHA-256: f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116.
RANDOMIZE_INIT retains upstream final zeroing; this is not a claim of randomized
initial-state behavior. LeakSanitizer was disabled for ptrace compatibility;
ASan and UBSan remained enabled.

No new Vivado synthesis/place/route, full SoC cancellation/boot qualification,
board result, LUT reduction or timing gain is established for this reconstruction.
Previous lost-work measurements must not be attributed to these new bytes.
Default-off PMP/cache options are experimental. Queue transport checks do not
replace integrated LSU cancellation and response-drain tests.

Dynamic test results will be appended only after completion. Generated models,
binaries, dependency caches and large logs must not be committed.

## Completed focused dynamic checks

- Atomic queue: 16,094 cycles; 11,244 accepted, 11,243 consumed, one reset
  discard; 7,774 simultaneous transfers. Four host-oracle negative controls
  (stale token, permission, canonical, frozen) rejected. Flush/quiesce stimuli
  are queue-harness observations, not integrated cancellation qualification.
- Shared two-word PMP: 53,450 independent-byte-oracle trials; 18,737 cases
  with differing lane outcomes. Active-granule and misaligned-packet negative
  controls rejected. Raw54 maximum NAPOT is explicitly bounded to the existing
  56-bit decoder contract; unbounded architectural range equivalence is not
  asserted.
- Both used the explicitly selected repaired GSIM binary above, ASan/UBSan,
  and stable source inventories. Enabled caller end-to-end behavior remains
  unqualified.

## Fresh fixed-aperture RTL equivalence

All 11 fixed apertures in `FixedApertureCases.apertures` passed Yosys SAT with
all 64 address bits and both size bits unconstrained. This includes the current
`0x80200000 + 2 GiB` board aperture, unaligned addresses/apertures, the exclusive
end at `2^64`, and arithmetic-fallback cases. The reference retains the original
67-bit dynamic shift and 68-bit addition. This proves these 11 fixed parameter
instances, not universal quantification over all possible aperture parameters.
A real emitted-RTL boundary mutant failed with `address=0x1001fffff, size=0`.
No alignment or valid-request assumptions were introduced.

Tool boundary: all 11 proofs used firtool 1.135.0 output converted by sv2v 0.0.13
before Yosys 0.52. Ten cases additionally passed the native Yosys SV reader.
Case 7 needs conversion because the native reader rejects its packed-array
initializer. Its four 7-bit constants and indexing were checked explicitly:
size 0..3 selects `0x78, 0x77, 0x75, 0x71` before and after flattening. This is
not an independent formal proof of the converter. No cache-level traffic,
throughput, resource, timing, or enabled-board behavior follows from this miter.

Portable reproduction, from the repository with these tools on PATH (the
negative command must exit nonzero and produce a counterexample):

```sh
source scripts/cloud/env.sh
python3 simulator/gsim/fixed_aperture_range_partition.py
for i in $(seq 0 10); do
  d="build/cache-range-formal/case$i"
  mill -i IonSoC.test.runMain ooo.FixedApertureRangeMiterMain "$d" "$i"
  sv2v "$d/FixedApertureRangeMiter.sv" > "$d/miter.v"
  yosys -p "read_verilog $d/miter.v; prep -top FixedApertureRangeMiter; flatten; opt; sat -verify -prove equivalent 1 -show-inputs -show-outputs"
done
d=build/cache-range-formal/mutant
mill -i IonSoC.test.runMain ooo.FixedApertureRangeMiterMain "$d" 0 mutant
sv2v "$d/FixedApertureRangeMiter.sv" > "$d/miter.v"
yosys -p "read_verilog $d/miter.v; prep -top FixedApertureRangeMiter; flatten; opt; sat -verify -prove equivalent 1 -show-inputs -show-outputs -dump_json $d/counterexample.json"
```

Fresh source SHA-256:

```text
bc01fc50e499ada37f6d9fe599a8308c0fa0b5505fd6460cdd0b24e12f2165bf  src/main/scala/core/ooo/FixedApertureRange.scala
b1881eebad97e47f21d421ed962aef25a0dfc0c181a71f8c90427967052994de  src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala
75a7fd2d976d78950d8f5d6d306128fc1c3f31258a6be78bde97a71b0aa6bc01  src/test/scala/ooo/FixedApertureRangeSpec.scala
e1cc71ccaadff072774de8304cbe5e254c271afd827c12a29b24d0902f610123  simulator/gsim/fixed_aperture_range_partition.py
```

Tool SHA-256: firtool `c2e1ac4d88be9579313c8a33ea3c8643db7d1840c78a4593dc05395171e25051`;
sv2v `b80a8ac6212aa72a196d9d6129cda35f16dbfa799ec61848c46321f845b6b635`;
Yosys `0e2b5c8f3ba616fa9ac5b05830e86181577ebf60d99401c10993885ff656e3ab`.
Original/converted RTL hashes, commands, logs, and the counterexample are retained
in the ignored sibling `recovery-tools-r1/cache-range-formal/` receipt directory.
