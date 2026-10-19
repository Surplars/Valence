# Shared ROM beat contract

`TileLinkInstructionRomAdapter.completeReadBeat` defaults to `false`. The
common fabric explicitly enables it because I1 can independently authorize
reuse of the containing 64-bit fetch word after a 16-bit parcel Get. The old
`FiveStageBootRom` already returned its complete `UInt(64.W)` storage word for
every legal narrow request.

The option changes only the physical ROM bank-read mask. It does not widen
TileLink `A.size`, `A.mask`, the requested-range denial check, `D.size`, or the
requested-word error selection. The default keeps the original single-bank
behavior. Neither setting changes any CPU PMP or translation logic.

## New bounded checks

- `fabric_machine.py`: actual common fabric, 128 KiB ROM, independent nonzero
  words in both banks. Tests byte/halfword/word Gets from each bank, the final
  high word, and aligned word/beat Gets just beyond the ROM end. Checks full
  returned data and original source/size/opcode/denied/corrupt metadata.
  Also tests narrow reads over scalar lane 0, the actual I1 uncached-fetch path.
- `fabric_rom_contract.py`: a small separate fixture compares the unchanged
  default with `completeReadBeat=true`. Checks 22 genuine replies including
  six denied out-of-range requests, and 88 held-reply observations. Separate
  expected-assertion runs reject a misaligned Get and an incorrect byte mask.
- Both runners use the existing qualified GSIM compiler, ASan/UBSan, immutable
  source/class manifests, bounded timeouts, and the 4 GiB free-space floor.
  Pass explicit tool paths and the compiled Java classpath, as for the other
  common-fabric runners. They never compile Scala implicitly.

## Existing permission boundary, unchanged

These are source-contract references and existing oracle cases, not a claim
that this change added or reran an MMU/PMP behavioral test:

1. `FiveStageAddressTranslation.scala:258-265` creates `wordPmp` for the aligned
   XLEN-wide word with execute permission and the effective privilege.
   `:344-348` still requires the original parcel PMP check and saves only
   `wordExecuteAllowed` as `span`. The fault path at `:309` clears `fetchSpan`.
2. The instruction fast paths at `:853-872` can set span directly only under
   the existing `fastEligible` proof. That proof is either unrestricted
   M-mode with all PMP entries off (`:142-151`), a matching bare full-page PMP
   proof (`:155-178`, `:225-238`), or a matching translated full-page PMP proof
   plus current PTE/privilege checks (`:499-518`, `:684-706`). PMP/context
   invalidation still clears those proofs.
3. `FiveStageFetchWordCuts.scala:42-51` issues halfword parcel requests unless
   a same-word reusable entry exists. `:146-148` publishes that entry only on
   a real response with `fetchSpan`, no error, and no stale/invalidate state.
   The second-parcel decision at `:63-73` also respects `fetchSpan`.
4. Existing independent oracle
   `simulator/gsim/harness/five_stage_fetch_aligner.cpp:138-160` checks whole-word
   reuse, partial-span reauthorization, context invalidation, and stale/fault
   rejection. Its partial-span case explicitly requires another physical
   parcel request. `five_stage_translation.cpp` separately contains the
   existing independent Sv39/PMP/page-vs-access-fault oracle.

Fetching both read-only storage banks supplies data for an already existing
permission proof; it grants no new execution permission. Board behavior and
physical timing remain outside these ROM-only checks.
