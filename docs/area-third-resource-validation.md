# Third resource batch: cache write data and fixed PMP callers

## Production scope and contract

Exactly four production leaves change. NonBlockingCoherentLineCache adds a default-off elaboration option factoring the retained/current 64-bit store data selection across bank bytes. The original posted/refill priority, masks, write addresses, write enables and ownership stay intact; no queue, state or port is added or removed. For posted P, refill R, masked-bank selection M, posted A, refill F, retained store X and live store Y, the original P?A:R?(M?X:F):Y equals (!P && (!R || M))?(R?X:Y):(P?A:F). This is a two-state identity, not an X-propagation proof.

SvPageTableWalker opts into natural-aligned shared PMP bounds for eight-byte PTE reads. InstructionLineCache opts in for aligned 64-byte demand lines; prefetch callers remain generic. The all-cycle domains follow from the unconditional zero low address bits, including invalid offers. CoherentCacheConcurrency's MachinePlatform factory activates write-data sharing only for its exact reviewed 512-line/two-way board configuration, 2GiB aperture at 0x80200000, concurrency, posted-owner and return-sidecar settings. Other constructor uses remain default-off.

## Retained qualification, not a new publication run

The combined candidate had one fresh CPU model, seven positive checks and eight designated negative checks. Positive stdout/event outputs matched its exact second-batch predecessor. COPY Bare/Sv39 remained 179571/191618 inclusive cycles; this establishes no cycle speedup. A native export had 308 files and five changed RTL leaves: cache, walker, instruction cache, PmpChecker_5 and NextLineAuthorization. NextLineAuthorization only acquired explicit read-access wiring through module-definition deduplication; concurrent instances are not merged.

The independent review rehashed the frozen source, classes, CPU model and runtime inputs, native outputs and original receipts. Packaging adds portable component runners and relocated imports; it does not rerun that CPU/native qualification or replace its frozen evidence. Repaired setup failures remain in the original evidence.

## Reproduce short components

Use the repository's pinned GSIM setup (`make gsim-setup`), Mill/JDK and Clang 19 or newer. From the repository root, choose fresh tags:

```
GSIM_CXX=clang++-19 python3 simulator/gsim/third_resource_components.py --component cache --posted 1 --tag third-cache-on --build-run
GSIM_CXX=clang++-19 python3 simulator/gsim/third_resource_components.py --component cache --posted 0 --tag third-cache-off --build-run
GSIM_CXX=clang++-19 python3 simulator/gsim/third_resource_components.py --component cache512 --tag third-cache512 --build-run
GSIM_CXX=clang++-19 python3 simulator/gsim/third_resource_components.py --component pmp --tag third-pmp --build-run
```

Omitting `--build-run` checks CLI planning only. Generated models, executable, logs and receipts go under ignored `build/gsim/<tag>`; none are source deliverables. These are component-only checks, never a full CPU or physical build. The 512-line component requires posted mode 1.

Cache positives pair the unchanged frozen full old cache with the candidate and reuse the independently authored posted-cache byte/ownership oracle. CPU read responses and dirty C payloads check physical bytes, not only installation observers. Cases cover all eight banks and 256 masks, retained miss overlay, posted accumulation, eviction and accepted second-owner/refill overlap. The 512-line supplement covers sets 0/127/128/255 and both ways with the same byte oracle, under a synthetic manager.

For each of the four real cache source negatives, create a separate disposable source copy (exclude `.git`, `out`, `build` and `simulator/build`), leaving the main checkout untouched. In that copy run:

```
python3 simulator/gsim/cache_write_data/make_source_negative.py miss-uses-live-request --output build/mutant
cp build/mutant/NonBlockingCoherentLineCache.scala src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala
GSIM_CXX=clang++-19 python3 simulator/gsim/third_resource_components.py --component cache --negative miss-uses-live-request --tag third-negative --build-run
```

Use an independently fresh copy for `hit-uses-stale-fill`, `refill-ignores-byte-mask`, and `posted-uses-refill-bytes` as well. Reuse the pinned GSIM checkout via `VALENCE_GSIM_SOURCE` if desired. Mill recompiles the modified source in that isolated copy; the runner checks the exact mutation and disables only pairing, requiring physical CPU/C byte-oracle rejection. Frozen reference and expected-byte logic stay unchanged. Timeouts, sanitizer errors or arbitrary failures are not accepted.

PMP runs paired Sv39/Sv48/Sv57 walkers and two-/four-word instruction demand caches plus four-word prefetch. It also requires three raw-permission observer corruptions and two host service-data corruptions to fail with designated diagnostics. These are observer/service negatives, not new DUT-source mutants. The shared-bound arithmetic source-mutant suite remains separate.

## Explicit limits

- No mapped LUT/FF/BRAM savings, timing, routing, hardware-board, CDC or PHY qualification is established. A literal mux-bit count is not a LUT estimate.
- Explicit fixed-caller COMPACT_TAG_TEST high-alias and CROSS4G_TEST transactions were not compiled. Highest-aligned fallback and invalid high/odd offers do not replace those transactions or full-line high-aperture authorization coverage.
- Exact held physical-register/ROB reuse remains NOT_REACHED; the held case requires family aggregation. A functional pass is not full family coverage.
- The 512-line cache fixture qualifies narrow geometry/storage/index behavior, not the entire board aperture, real Home reachability or tagged-return sidecar. Integration positives are not exhaustive schedules.
- Scalar fallback/held TL-D, upper-generation wrap, and all FP-return/fault/cancellation paths are not newly claimed as covered.
- The original native receipt's PENDING_STAGING suffix is retained. It is emission evidence, not a publication or physical acceptance status.

## Independent high-address addendum

A later independent component addendum closes the explicit guarded fixture gap in a bounded scope. Three paired compact-tag cache models passed: two-/four-word prefetch-OFF with COMPACT_TAG_TEST and CROSS4G_TEST, and four-word prefetch-ON with COMPACT_TAG_TEST. Both original service-corruption controls were rejected. The original host, Scala and qualification were unchanged; this does not retroactively alter the original not-compiled statement above. The evidence receipt SHA256 is `656814c0bfbdd7110baf3d5c369062f3dd4dc61dcddadd3c26605ea57e5188dd`.

Reproduce with:

```
GSIM_CXX=clang++-19 python3 simulator/gsim/third_resource_components.py --component pmp-high-address --tag third-pmp-high --build-run
```

All three use a synthetic 16-line/eight-set/two-way aperture at 0x80010000 with 2GiB bytes, full 64-bit TileLink addresses and 24-bit compact tags. OFF checks full-address 4GiB line fill/hit, low-line retention and bit40-alias precise fallback with returned instruction bytes. ON checks high-alias fallback A issue after a held prefetch A; it does not service/check that fallback reply and has no CROSS4G block. This is not exhaustive high-address PMP permissions, highest-aligned full-line authorization, actual-board geometry/traffic, held physical/ROB reuse, or a physical resource/timing result.
