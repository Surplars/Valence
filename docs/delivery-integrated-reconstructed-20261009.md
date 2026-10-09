# Reconstructed delivery composition

This records the earlier 6a26 delivery freeze. The subsequent opt-in MRU
composition is documented in [delivery-mru-integrated-20261009.md](delivery-mru-integrated-20261009.md).

This is a new source checkpoint based on public dev
`926ea18ecab93364a1a7b1ae745fc674c275c2b1`. It combines the reconstructed
hardware freeze `d31bbf3afc7fb4fd4e6682a036c382f63d811773` with the following
explicit source inputs:

- BootROM MMU menu, production diagnostic and portable fixtures from
  `a69023368abb097232d3d4421a2b709e63eded70`.
- The two-file, 81-line passive cache observation addition from
  `eb18e1c2f1a8e9b5aec22bb0f39109c6dada042e`.
- Checked-store PF policy/adapter/cache fixtures from
  `d21d3eb3d681acfc241a2ba523d22edca23724b7` and their source-bound reporting
  documents from `0332de0d25e65d693811d66c25c1730207b6ec12`.
- A portable `--tool-files` option for the fixture launcher, identifying an
  existing installed-tool receipt. Its new input inventory binds all tracked
  regular files, including `build.mill` and `simulator/gsim/config/toolchain.json`.
  It neither builds nor installs tools. Historical receipts retain their original
  inventories and source identities.

Production `src/main` is `0f744f6cbb07d816355eb9d0b6f9d1cdb397397c`.
Relative to d31, the only hardware source edits are the passive observation
Bundle fields and Wire assignments. Defaults remain D8, prepared-store OFF and
checked-store PF OFF. No posted-store merge, WB reservation or MRU insertion
candidate is included. Issue width, public image/stage2 flows, DMA, MAC and JTAG
implementations remain at their established inputs. The BootROM change adds
explicit `u`/`9` dispatch without increasing the reserved scratch region or
changing automatic boot.

## Qualification boundary

This checkpoint is not the lost original `0e62d30` candidate. Reconstructed d31
receipts remain proof only for d31 and their stated profiles. The reconstructed
PF module receipts remain proof for their own source. Neither set is renamed as
a whole-system PASS for this delivery source.

The passive-observation native bridge has status
`PASS_NARROW_SYNTACTIC_CACHE_BRIDGE`. Its scope is the cache and reachable
children: bijective declared combinational temporary renaming and expansion of
one uniquely assigned preceding mux, with every other token and order exact.
It includes nine deliberate mutation rejections. It is neither a whole-Board
comparison nor a formal equivalence proof. Its original comparison receipt,
checker, two export receipts and exact SHA256s belong to the external delivery
checkpoint index. The passive fields change the raw source identity even when
unobserved logic disappears during native export.

The BootROM input has a separately executed native/menu test and complete ROM
link. Its production supervisor kernel is 1472 bytes with SHA256
`f5a152ca2779ee567a9f864bc29d524bd91a935dab0323f21353ae9c9af0fec5`.
Importing the source alone does not execute the new menu on this hardware.
The source-only delivery gate verifies input composition, public preservation,
default/config host checks, Python syntax and patch replay. It does not emit RTL.

## Next source-bound checks

Before calling this new source an executing integrated candidate:

1. Run the five focused Scala/config suites and emit a fresh full-Board C model
   from this clean commit with the existing pinned tools, one job at a time.
   Bind all source files, parameters, tools and generated objects.
2. Run the fresh model's actual RV64GC smoke and its independent mismatch
   negative. Export current C native RTL and compare the relevant cache/RAM
   structure under the explicitly stated comparison rules.
3. Use a new source/model-bound host for the new BootROM/MMU guest if claiming
   its whole-Board execution. Keep immutable guest and production-kernel hashes,
   privilege/PMP/context checks, complete data checks and terminal owner drain.
4. Renew any specific NEMU, DMA, timer, alias or Sv39 claim for this source by
   either actual execution or an explicit, adequately scoped structural bridge.
   Existing d31 receipts remain useful evidence but are not new-source results.

The previous common profile is selected read configuration, LSU4, physical
load ingress, virtual RAM load precheck, older-load retirement, previous-fetch
packet and DMA line transfers with four owners. `prefetchBreakOnStore=false`.
A uses D8 with both new feature flags OFF. B differs only by D16. C is B with
prepared-store and checked-store PF ON. In Sv39, the reconstructed prepared-store
lookahead is inactive; physical B/C results reflect both flags together.

No mapped/routed timing, FPGA behavior, general bandwidth benefit, long Linux
qualification or controlled Sv39 late-cancel/ROB-reuse qualification is claimed.
The separately blocked controlled gate stays blocked.
