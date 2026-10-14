# Secondary setup locality batch

This candidate preserves two-issue operation, 48 logical physical registers,
the existing 12-address PRF topology, one fresh memory AGU, and all existing
pipeline/credit/retirement/kill rules. No new register or cycle is introduced.
Physical timing and area remain unverified until the combined batch is placed.

## Compact PRF read address

`OwnerBankedPhysicalRegisterFile` keeps low read-address bits independent of
the compact-depth range check. For non-power-of-two depth N and b = ceil(log2 N),
N > 2^(b-1). An invalid b-bit address is safely mapped into the lower half by
clearing only its MSB. Valid addresses are unchanged. The original `inRange`
output guard still forces invalid reads to zero; x0/initialized/owner selection,
write bounds, two-writer collision priority and no-write-through are unchanged.
Power-of-two depths use the raw address directly.

This specifically targets the placed address-high-bit -> range-safe-low-bit
detour shared by execution payload and memory AGU paths. It does not grant a
new physical register or expose the underlying aliased data.

## Resident exclusion after circular ranks

`ResidentMemoryPreparationSelector` computes the original eligible pool's first
and second circular ranks before the caller's full-token resident decision.
If the resident is valid and the original first owner matches it, fresh owner
is the second rank; otherwise it is the first. This is exactly the oldest owner
of `E \ {resident}`. Empty masks retain zero owner/index and false freshValid.

The resident full-token predicate remains in the caller. `issued` still affects
only the resident-versus-fresh result, never fresh PRF selection. Current-cycle
accepted issue, same-owner hold, payload immutability and full-token stale-owner
rules are preserved. The second combinational rank now survives dead-code
elimination, so LUT/route cost must be measured. No second payload or PRF group
is added.

## Bounded validation, after the combined edits

These are instructions, not a record of completed tests. Use one batch compile,
then the necessary focused cases. No Verilator/full GSIM/Linux/bitgen is involved.

1. `mill -i IonSoC.test.testOnly ooo.OwnerBankedPrfSpec`
   checks 33/48/63/64/65/127/128/129/255/256 elaboration, read-address mapping for
   every supported depth 33..256, and rejected 32/257 depth bounds.
2. `GSIM_CXX=clang++-19 python3 -B simulator/gsim/owner_banked_prf.py --tag UNIQUE-prf --build-run`
   runs the existing real-RAM matrix and independent word oracle. The host adds
   every invalid 48-entry address, with its safe alias populated from both RAM
   banks; invalid output stays zero before and after writes. Existing reset,
   x0, collision-priority, disabled-poison, no-write-through and negative checks
   remain. Use the pinned `FIRTOOL` path if not on PATH.
3. `GSIM_CXX=clang++-19 python3 -B simulator/gsim/resident_late_exclusion.py --tag UNIQUE-resident --build-run`
   compares production binary/predecoded-head versions against the pre-change
   component equations and an independent host ROB walk. About 1.16 million
   vectors cover every mask/head, directed resident positions, empty/sole/two
   owners, wrap, issued/reuse, all 64 mismatching tag bits, stale index and absent
   pending owner. Oracle-mismatch and invalid-issued negatives must reject.
4. Reuse the batch's matched short CPU/ownership/memory checks. The selector-only
   test is not end-to-end memory ordering or NEMU qualification. Existing
   `ResidentMemoryPairGsim` can supply the actual RAM/AGU/staged tuple boundary
   check if the batch does not already cover it.

The final native census should confirm unchanged PRF addresses/data ports,
unchanged memory stage registers, only one fresh AGU, and no current `issued`
input in the fresh rank/source cone. Check both execution payload D/CE and
ownerReady/stagedIndex-to-stagedMemoryAddress after the one combined place run.
