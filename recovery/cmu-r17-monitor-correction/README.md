# r17 observation-monitor correction

## Result and scope

Three corrected observation-side negatives reached the intended ordinary checker
on the exact historical r17 emitted RTL. No positive simulation was rerun. The
eight historical positive runs remain valid within their original historical
scope. This correction is **monitor-sensitivity evidence**, not qualification of
current production sources or a physical CDC, clock-gating, DRP, PHY, or board.

The evidence is in `replay-r1/receipt.json` and its four logs. The simulator binary
is retained only in `out/cmu-r17-monitor-correction/replay-r1/`. The working-tree
change is limited to `simulator/gsim/common/i1_runtime_network_tb.sv`; the original
native runner, production/Scala sources, emitted RTL, guest, and historical
receipts were not modified. No Mill, Verilator, Vivado, install, or remote upload
was performed. Remote publication is not authorized by this local correction.

| Corrected control | Ordinary rejection | Return code | Seconds |
| --- | --- | --- | --- |
| RX case 0, negative 1 | `NETWORK_ORACLE_PAYLOAD RX word=0 byte=0` | 1 | 12.919 |
| RX case 0, negative 3 | `NETWORK_ORACLE_GUARD ... got=55667789 expected=55667788` | 1 | 15.989 |
| TX case 3, negative 1 | `NETWORK_ORACLE_PAYLOAD TX byte=23 got=2e expected=2f` | 1 | 13.373 |

Compilation took 9.654 seconds. Every simulator process uses VVP `-i` for
unbuffered output. Every native process has a 180-second limit, a continuously
checked 4 GiB free-space floor, and unconditional process-group cleanup and child
reaping in `finally`. No process timed out or breached the disk floor; minimum
observed free space was 28,310,929,408 bytes. Each negative had exactly one fatal,
at the corrected testbench's intended ordinary check, and no positive PASS marker.

## Exact historical claim being corrected

The baseline is `out/cmu-frequency-r17/native-r3/receipt.json`, SHA256
`f72c3ef0c0ad8207c1ac5ceda6bece8ce16ff44f059736dae78d2b1a97703634`.
Its exact testbench, preserved as `baseline_tb.source.sv`, has SHA256
`b1a2d8eed6689c5333bbaa1ba78d0beb0ad9fb8deef802ab856f95374c2b8903`.

- Baseline line 619 flips `expectedPacketWord` for RX negative 1. Line 728
  similarly flips `expectedWireByte` in the TX branch. Those are reference-value
  corruptions consumed by the ordinary payload checker, not observation-side
  corruption. The old native receipt ran the RX case 0 branch, not the TX branch.
- Baseline line 918 changes the expected guard to `GUARD_DATA ^ 1` for negative
  3. The ordinary comparison rejects it, but the diagnostic prints the original
  constant, producing `got=55667788 expected=55667788`. This is a misleading
  diagnostic for a legitimate reference-corruption control, not evidence of
  observed RAM corruption.
- These old negatives are **not** direct force-fatal controls and do not bypass
  the ordinary predicate. They establish ordinary checker sensitivity to an
  incorrect reference. They do **not** establish the previously described
  observation-side injection. The correction narrows that claim, not the eight
  historical positive results. Negative 2 already changes only the local
  `observedPrepares` count and is unchanged and not rerun.

The old receipt and affected logs are copied byte-for-byte here, never rewritten
or converted into new acceptance evidence. All old native-directory files,
including all eight positive logs, all three negative logs, the original binary,
guest artifacts, snapshots, and receipt, were hashed before and after execution
and remained unchanged.

## Correction and default-mode preservation

The corrected source is preserved as `corrected_tb.source.sv`, SHA256
`ae58516f80bd100c0bf0bb7da294650f0d1041219339712d4ed65856cd7e7959`.
`monitor-only.patch` is the complete diff:

- RX samples the real packet request data into `observedPacketWord` and flips
  only bit 0 of that sample in word 0 for negative 1. `expectedPacketWord` remains
  the unmodified result of `packet_word`.
- TX samples `gmiiTxData` into `observedWireByte` and flips only bit 0 at wire
  position 23 for negative 1. Expected bytes and CRC computation are unchanged.
- Guard negative 3 flips bit 0 of the local RAM-read sample's guard word. The
  ordinary comparison and diagnostic use the original `GUARD_DATA` constant.

No DUT signal, RAM storage, handshake, gate, or production state is changed by
these injections. They corrupt local observations immediately before the normal
checker, so they do not claim detection of a physically injected hardware fault.

`positive-mode-proof.json` and `positive-mode.tokens` preserve a narrow static
equivalence check. `replay.py:positive_projection` explicitly specializes the
changed negative-1/3 expressions to negative=0, folds only the new immediate
blocking observation copies back to their sources, then removes comments and
normalizes whitespace outside strings. Every remaining token of both complete
testbenches, including diagnostic strings, is identical. The two projected
SHA256 values are both
`bad8e38fc4e7e4c913c803596ce4492d52b04e96e74c9ecda4286f1d4356af20`.
The unchanged negative-2 expression remains identically present on both sides.
This is source-equivalence evidence, not a new positive simulation or general
formal-equivalence result.

## Historical binding and reproduction

The replay validates the old emission receipt
`out/cmu-frequency-r17/network-r2-emission.json`, SHA256
`313d4115842b83b99025ecae65c4d7b227957325b1a3862a4eefd22993f8554b`,
and all **204** original RTL files in `network-r2-rtl`, requiring exact inventory
equality with both receipts. It reuses the original compile command with only the
output binary and testbench path substituted. Original assertion flags and the
original guest-symbol include directory are unchanged. The original preprocessed
assertion inventory, complete compiler chain, guest ELF/bin/hex/symbols, and
original simulation binary hashes are validated. The new binary SHA256 is
`ecfb1b9e510be54909675bc46dc9e5b295f346b553ebff7cf54be4d54eab6aa7`.

All 258 bound inputs were rechecked after the replay. Nine current emission
source files differ from the original inventory; the exact paths and old/current
hashes are disclosed in the new receipt. The strict current-source checks of the
original runner were not weakened or bypassed. Historical RTL is deliberately
not presented as current-source qualification.

Read-only verification, with no simulation:

```sh
source scripts/cloud/env.sh
python3 recovery/cmu-r17-monitor-correction/verify.py
```

Reproduction, choosing a fresh output directory while retaining the frozen
historical inputs and toolchain:

```sh
source scripts/cloud/env.sh
mkdir -p out/cmu-r17-monitor-correction
python3 -u recovery/cmu-r17-monitor-correction/replay.py \
  --output out/cmu-r17-monitor-correction/replay-r2
```

Missing or drifted inputs fail validation. They are not silently regenerated.
The publication-sized bundle contains only this directory's source, JSON,
patch, token proof, and log files. No simulator binaries, generated RTL, or
`__pycache__` should be published. This documentation does not authorize upload.
