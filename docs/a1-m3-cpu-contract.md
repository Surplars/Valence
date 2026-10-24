# M3 actual CommonA1 CPU contract

This is a bounded experimental validation contract, not a timing or board qualification.
The default Selected/FullCandidate and published full-r1 baseline remain unchanged.

## Scope and identity

The new `M3CompletedCanonicalCpuGsim` inherits the unchanged actual CommonA1 VM tile fixture and selects only `full-r1-m3`. It preserves the full RV64GC core, ROB16, PRF48, four LSU owners, real Sv39/PMP, DTLB16 and 32 KiB two-way caches. New outputs are passive test-wrapper taps, not production counters or credits.

The published M2/R1 host and models are immutable. Before reuse, the runner checks all retained full-r1 artifact hashes and freshly elaborates full-r1 with M3 disabled. Its effective parameters must differ only by the new false field. CHIRRTL must match the retained baseline byte-for-byte after removing source-location annotations and six explicitly approved builtin diagnostic source-line locations only (five LSU `315→352`, one backend `3406→3454`, with exact occurrence checks). The first stricter gate rejected these strings; its failed receipt and raw diff remain intact. No predicate, format beyond those exact locations, or other structure is normalized. Any structural difference requires a fresh explicitly identified control instead of reusing an invalid baseline.

## Matched guests and service

The two original programs remain byte-identical, including setup and ROI boundaries: `vm_store_stream` and `vm_dependency`, each 233 retirements and 49 ordinary stores. A software dump compares both original byte streams exactly before any model runs. Their instruction/PTE/cache service is unchanged: instruction A continuously ready up to 16 owners, D latency 3/II 1, native PTE latency 3, legal whole-line L1D Grant latency 3 with source/sink ownership and E acknowledgment. Ordinary stores remain conservative and serial; these are not high-MLP bandwidth tests.

The isolated functional-only `vm_alias` guest has 72 retirements, nine stores and 18 loads. Only this mode enables a second supervisor VA page mapping to the same PA line. Its initial alias load establishes independent read translation. Eight subsequent original-VA stores are read through the alias. This case has no historical performance baseline.

## Independent checks

All programs are pre-executed from raw instruction bytes using the retained independent ISA, CSR, Sv39 page-image and PMP oracle. Every retired PC/instruction/destination/value, final GPR and precise EBREAK is checked. The actual demand path independently verifies MPRV/MPP=S while fetch remains M.

For every actual forwarded load, the host requires a matching live full-token source certificate, independent VA/PA/size/mask/read authorization and current stable epoch, an actual earlier successful store reply, and the same LSU slot's actual completion handshake. Forwarded bytes must match both the source store and the independent architectural memory value. Forwarded full tokens are tracked to retirement. Physical loads plus forwarded loads must equal the architectural load count. Every store still requires a real physical request, reply, completion and retirement. The alias guest must produce an actual nonzero different-VA/same-PA forwarding witness.

A separate previously authorized passive trace binds baseline traffic without rerunning a model: stream 57 physical loads and dependency 105, each with 49 physical stores/replies. Its 108 original metric fields exactly match the published full-r1 result. The CPU receipt compares work and ROI cycles per guest and actual CPU-to-L1D physical request reduction; these are not external TileLink transaction reductions, since the warm line remains cached; a nonzero event alone is not a throughput claim.

Two CPU negatives mutate sampled observations, not RTL: forwarded bytes and a retired GPR value. Each must reach its exact marker and independent rejection, with ASan/UBSan clean. Subword/sign/mask extraction, failed reply, cancellation and high-tag reuse are covered by the separate actual ParallelLSU model; permission/epoch/PA qualification uses the separate independently modeled predicate fixture. These component scopes are not substituted for CPU integration coverage.

## Results

The frozen batch passed one Scala compile, five configuration tests, two small component models with four negatives, and one new actual CPU model reused for three positive guests and two observation negatives. The new CPU model's real generated-header API gate passed before C++ model compilation. No production or host repair was needed after freeze.

| Matched guest | Retired | FullR1 work → M3 work | Work delta | FullR1 ROI → M3 ROI | Physical loads → M3 | Actual forwards |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vm_store_stream | 233 | 1024 → 736 | -288 (-28.125%) | 856 → 568 | 57 → 9 | 48 |
| vm_dependency | 233 | 1173 → 1120 | -53 (-4.518%) | 1005 → 952 | 105 → 57 | 48 |

Both retained all 49 physical store requests, actual replies, completions and precise store retirements. Bootstrap remained 168 cycles; drain remained seven and final-register inspection 32. The dependency case improves much less despite the same forwarding count; these are measured total-cycle results, not a claim that each forward saves the same latency. No additional diagnostic rerun was performed to assign the residual dependency cost.

Both still performed 136 external instruction requests/beats, three PTE reads and one coherent data line acquisition/grant/E acknowledgment. Thus the observed request reduction is on the CPU-to-L1D load path, not a reduction of shared-bus/cache-miss traffic or a sustained bandwidth qualification.

The isolated alias functional guest passed 72 retirements in 316 work cycles, with eight actual different-VA/same-PA forwards. Its nine physical stores/replies/completions were conserved; 10 physical loads plus eight forwards matched its 18 architectural loads. It has no matched historical cycle comparison.

The initial baseline gate correctly rejected six changed builtin assertion diagnostic line strings. The preserved r1 receipt is `build/gsim/m3-common-cpu-20261024-r1/receipt.json` (SHA256 `aa7f6981713b68e6f3da137480880f6a13bf56d549f382bc5d96e8b26e3dd7a3`). Raw diff and exact diagnostic mapping analysis are in its `baseline-structural-gate/` directory. R2 reused that control elaboration, checked the two exact 5+1 mappings, and proved all remaining normalized FIR bytes equal at SHA256 `2a2d55cec4b41e1b40ff96111876e71df69fae3f4ecc3027551fd123a958c60c`. Raw FIR bytes are not identical. No old baseline model or guest was rebuilt/rerun.

The successful CPU receipt is `build/gsim/m3-common-cpu-20261024-r2/receipt.json`, SHA256 `045aea52acdd12813b491d6327a7492aa38b83dba9c791001e7458461122d371`. Its sources, tools and bound historical baseline artifacts remained unchanged. The component receipt is `build/gsim/m3-completed-forward-20261024-r1/receipt.json`, SHA256 `8393e8d4f154f7b4c909914f9f54a511ae1a7272c09dabd5d8756b4d26543e34`.

These are bounded functional and matched-cycle improvements only. No Fmax, area, 300 MHz, CDC, shared-DDR, Linux, complete ISA or board qualification is claimed. Actual Selected accepted-prefix specialization remains false; default profiles are not promoted.
