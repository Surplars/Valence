# Pending-store owner-match reuse

`PendingVirtualStoreProof` reuses each row's current full owner-match predicate
when accepting its translated store result. No feature flag, constructor, port,
state capacity, arbitration or cycle boundary changes. Existing flags retain their
meaning.

A granted row is immutable through its one-stage translation result: admission
writes only free rows, while the granted row is inflight. The descriptor's full
token, epoch, virtual address, size, mask and write kind equal the row's fields.
An assertion checks that invariant; physical address is deliberately excluded
because it comes from the new translation. The result still checks inflight
state, full token, epoch, current owner, clear and consume. Permission/shape
failure still releases the row. Existing cancellation, binding and same-edge
cleanup priorities remain intact.

## Qualification

Relative to published `cbd94b45805fbe22f659da270646b246675d0a3f`:

- Seven configuration checks pass. Paired real banks with one and two rows match
  the frozen old body across 233 and 259 directed cycles. The unchanged independent
  owner/PMP oracle checks transaction provenance and permission outcomes. All 17
  host-observation corruption controls fail through the ordinary parity checker;
  these are checker-sensitivity controls, not mutated-RTL tests or formal proof.
- One fresh 36-translation-unit board model passes serial combined ASan/UBSan
  runs with the identical complete constructor (56 profile, 149 core, 19 cache
  fields). Sv39 is 246,905 inclusive cycles and Bare is 260,694. Complete stdout,
  all 105 functional/performance fields, and raw AXI/supply events are identical
  to the published full-profile baseline; ROI, tail and inclusive deltas are zero.
- One native export, compared with the source/tool/profile-bound existing native
  baseline on the same R16, one-proof-row board, removes six translated-owner
  16-way reads totaling 144 selected bits
  and the repeated full-token/address/size/mask comparisons. Exact reachable
  state, ports and hierarchy are unchanged: 97,337 scalar register bits, 729,335
  array bits, 568 instances, 237,478 internal port bits and 353 top-level port bits.
  The existing row predicate gains a result consumer; native text shows four
  consumers. The two-row configuration has paired dynamic coverage only; this
  native cost result is not extrapolated across parameters. Mapped fanout,
  LUT/FF/BRAM/DSP, timing and performance gains are unmeasured.

The production file SHA-256 is
`972d2c1c0c0fdae301b392e4f2d8c26c622931d5c8979bee030b7e74cf3bc1e3`.
The focused receipt SHA-256 is
`8f1e3b7295231180cb589a8e9b535f43768643d4d390d6499de6d8131261bdc0`.
Board/native receipts, raw logs and generated models remain external recovery
evidence. This change does not claim physical implementation or broader traffic-law coverage.

## Focused reproduction

From the repository root, run each stage in order with a fresh output directory
and the pinned GSIM toolchain described in `simulator/gsim/README.md`:

```sh
python3 simulator/gsim/proof_owner_match_reuse.py STAGE \
  --output /path/to/fresh-output \
  --toolchain-root /path/to/toolchain \
  --activate /path/to/toolchain/activate.sh
```

Stages: `freeze`, `config`, `emit`, `generate`, `sanitized`. The paired wrapper,
frozen reference and C++ host are included in this change. The public runner
checks the normalized frozen reference body against SHA-256
`7d1a0ea99e7de286a3a2ee27a961240198e9081b8fbf715152e68f7dfcbfbdee`,
so it works without the private review commit's Git object. A no-Git-directory
fixture passes and a nonzero reference-body mutation is rejected. This is a
source-only runner portability bridge; the executed production, wrapper,
reference and host bytes are unchanged, and no model rerun is claimed for it.
