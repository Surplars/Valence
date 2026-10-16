# Experimental D-side miss-only translation cache

Base RTL: `50cb0c5d4b17318904d6cf818ad23829821d5d93`. This is an opt-in candidate, not a release-profile change. The later firmware-only development commit may accept the RTL patch separately; merge metadata deliberately rather than replacing a development tree.

## Hardware contract

`dataTlbMissCacheEntries` defaults to **0** through FpgaNextSocTop, FpgaNextConfig.managedBoard, BoardSocTop and MachinePlatform. Only the D service receives this argument. I remains 8 entries with no L2; tested D L1 remains 16. No FpgaNextConfig product field or selected production profile is changed. Service `missCacheEntries` accepts exactly 0, 32, 64 or 128; all nonzero sizes use two ways, with depth, set count and index widths derived from that capacity. Only 64 has native fullCPU and resource qualification.

The optional L2 is inclusive, (entries/2) sets × 2 ways, indexed by the corresponding low VPN bits (VA[16:12] for 64 entries), with one synchronous payload-memory port and serial way probes. It admits successful Sv39 4KiB non-NAPOT leaves only. L1 demand/peek protocol has no added cycle. L1 misses probe two cycles before either replying/promoting to L1 or starting the unchanged PTW. Three same-set pages may conflict. This is not a fully associative 64-page guarantee.

Exact root/ASID/mode/privilege/SUM/MXR and access/reuse semantics are preserved, including conservative exact-ASID matching for global leaves. Failed walks do not allocate or upgrade. Flush invalidates valid bits under the original drained-idle contract. The final adapter still authorizes physical access with current PMP state. There is no posted-store admission change.

This is the current Sv39 **stage-1 D translation cache**, not an H-extension-ready combined translation cache. Future H integration must extend or isolate VS/G-stage identity (including VMID/hgatp and relevant address-space controls) and corresponding invalidation. Current root/ASID keys do not certify those future semantics. Existing H reservations are unchanged.

## Reproduce without a new DUT build

The contract runner accepts existing compiled BoardSocGsim objects. It never modifies or builds that model, never imports a saved historical header, and checks the supplied model's source-bound D-service fields before linking. Use the exact compiler flags and toolchain compatible with those objects. A supplied receipt can carry `host_flags`; a JSON array of flags also works.

From repository root (replace shell variables with local tool/output paths):

```sh
CONTRACTS=simulator/gsim/dtlb_miss_cache/contracts
python3 "$CONTRACTS/run.py" guests --cross-prefix "$CROSS_COMPILE" --output "$OUT/guests"
python3 "$CONTRACTS/run.py" link --model "$MODEL" --guests "$OUT/guests" \
  --output "$OUT/bin" --cxx "$CXX" --host-flags "$MODEL_RECEIPT"
python3 "$CONTRACTS/run.py" run --guests "$OUT/guests" --binaries "$OUT/bin" \
  --output "$OUT/results" --expect-l2 64
```

For a saved default-OFF baseline, link against its own objects/header and pass `--expect-l2 0`. The expected baseline result is architectural/data PASS followed by deliberate missing-L2-coverage rejection, not CPU functional failure. On L2, the runner additionally poisons coverage. It runs independent bad-data/stale-PA and precise-trap-cause negatives as appropriate. Guest binary/symbols, sources, model objects/header, link commands and result logs are hashed in generated receipts. Source-bound field drift intentionally fails closed; review a new hierarchy instead of silently substituting old getters.

The M-mode assembly uses MPRV/MPP=S for data while keeping instruction execution physical. Context guest checks a real PTE store + SFENCE remap and a subsequent SATP root/ASID change. Permission guests revoke SUM, MXR or PMP after an observed target L2 hit and require precise cause/PC/tval, no normal faulting-load retirement and no extra physical target access. Host never writes DUT registers. Target coverage is keyed by saved translation context and PA, not an out-of-order retirement-marker window.

## Fresh-model entry points, when explicitly needed

The test-only `ooo.MissCacheBoardGsimMain` takes a fresh output directory, `l2-on|l2-off`, and a saved production-ON actual JSON. It constructs the complete frozen profile with all existing repair flags still ON, checks the entire old actual/fabric audit, then independently inspects the instantiated I/D services. It does not change release defaults.

```sh
mill -i IonSoC.test.runMain ooo.MissCacheBoardGsimMain "$FRESH_OUT" l2-on "$REFERENCE_ACTUAL"
```

Generate/compile with the project's pinned GSIM and host flags; this document does not inherit qualification for a differently built model. Bound Java/GSIM/compiler resources and use at most two native compilation workers.

Parameter extension was independently checked: complete service+adapter FIR for 0 and 64 is byte-identical to the qualified fixed-64 implementation after stripping only source locations and assertion line numbers. Actual 32/64/128 service+adapter/PMP runs pass permission/context/flush/derived-set three-page conflict/RW-upgrade checks and two oracle-poisoning negatives per size. The 32/128 values have not been run as fullCPU models or mapped for resource/timing.

Portable focused runner (uses only a service fixture, never a fullCPU):

```sh
python3 simulator/gsim/dtlb_miss_cache/run_service.py --entries 32 \
  --output "$FRESH_SERVICE" --gsim "$GSIM" --cxx "$CXX"
```

Repeat for 64/128; entry 0 runs the default-OFF capacity/PA oracle rather than requiring L2 hits.

Focused service entry: `ooo.DataTlbMissCacheGsimMain fresh-output 64` (or 0). Existing GSIM drivers are `mmu_capacity.cpp`, `mmu_l2_contracts.cpp`, `mmu_l2_peek.cpp`, compiled with `DTLB_ENTRIES=16`, `DTLB_WRITE_READ_REUSE=1` and `MISS_CACHE_ENTRIES` equal to the selected L2 size for `mmu_l2_contracts.cpp`. They retain independent PA/data/permission/owner oracles. Peek's L2-aware walk-count expectation differs deliberately from its old L1-only test. See the receipt for measured scope; no theoretical VPN simulation replaces actual service RTL.

## Results and boundaries

See `results.json` for source-linked small receipts. Sparse READ page-sweep additionally preserves READ16 at 12052 cycles and changes READ17 131716→28934, READ32 247300→53894 cycles (128 passes, one 8-byte access/page, 4160-byte stride). ROI PTW2176/4096→0 and L2 hits2176/4096; DDR reads likewise disappear, with zero data-cache ROI misses on both arms. Boot+cold-warmup increases 30/32/60 cycles for 16/17/32 pages. This matched assembly microbenchmark is not the user’s GCC13.2 production C binary or a measured board score. Portable page-sweep sources and exact independent counters are provided in the sibling page_sweep test directory. Standalone xcup/no-wide mapping adds 359 logic LUT + 224 allocated LUT-as-RAM = **583 LUT**, plus **185 FF**; 28 RAM64M8 and zero BRAM. Each RAM64M8 is counted as eight LUT sites even though the SDP techmap uses seven live read-data lanes. Hot L1 demand/peek structural depth stays 11 LUT levels; no routed delay or ns claim follows. The generic graph cuts RAM boundaries and does not characterize LUTRAM internal read delay.

Matched native continuous-stream READ1 and READ16 retain 4125 and 74093 ROI cycles. COPY16 pages/stream changes 175018→172020 cycles, ROI PTW64→0 and actual L2hit0→64. That workload is not sparse board page_sweep. Cold costs remain: boot/cold-warmup increases 4/42/77 cycles for those cases; context guest 12669→12755 cycles despite PTW99→96. SUM/MXR each 5072→5104, PMP5249→5284. Do not report only warm wins.

Default-OFF raw CHIRRTL is not identical: two service modules retain disabled common wires/refill expressions. The other 270 native modules match after local alpha-renaming and assertion-line normalization. Actual D16 service formal equivalence proves all 10760 points, zero unproven, with no input assumptions. I8 has not been separately formally checked.

Not qualified: native LR/SC or AMO, new NAPOT-specific cases, full architectural/Linux regression, physical STA/placement/routing. Atomic and physical timing remain promotion gates. Do not combine this result with early-load-descriptor changes without a separately attributed combined check.
