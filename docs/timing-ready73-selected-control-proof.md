# Ready73 selected-control source lemma

The native ready73 export introduces one additional, complete source form to `board_t1.source_control_lemma`. Admission compares the entire encoder/parent/physical-adapter hash dictionary against a reviewed whole dictionary. It never accepts independent per-file lists.

| Complete file | SHA-256 |
|---|---|
| `rtl/TriSpeedRgmiiTx.sv` | `6374714496e0b23b174ac542027eefc59370c13cd5a0eb85de9af58e77af79a7` |
| `rtl/TriSpeedManagedGmac.sv` | `5be26d593e5462db4028983ab63e7ffe3b0e58bc1e133242629b2e945c1c3d9b` |
| `board/native_rgmii_trispeed_quarter.sv` | `32b96761f2019806b6e03d9d885595449d2b057a30b6bb9ca204a34162ce96fc` |

Encoder and physical adapter bytes equal the original reviewed form. The complete new parent retains the identical `TriSpeedRgmiiTx encode` instance: RAW TX clock, the same RAW reset release, and direct rise/fall output connections. The complete parent changes only RAW-handoff wires/instance, TX byte-step consumption, RX tuple consumption and RX pending in the idle condition; it adds no driver or transform to encoder outputs. The fresh native bank, board, top and physical wrapper forwarding chain was separately checked.

In the complete encoder, rise/fall control bit4 both receive the identical scalar `enable` in the same unconditional non-reset branch of the same positive-clock/asynchronous-positive-reset process. Both reset to zero. `enable = byteStart ? io_gmiiEnable & ~(|rateGap) : heldEnable`. Different payload nibble expressions do not affect bit4. RAW-handoff feedback may alter a later shared enable value; it cannot make the two control D values differ. Equality holds after reset and at every subsequent capture.

The unchanged adapter resets selected low/high state to zero together. At low phase both capture equal encoder control values. At high phase, selected-half mode assigns old high to low while high holds; otherwise both hold. Therefore equality is inductive from reset. The existing selected-mode16 vectors remain, and the companion test enumerates both mode choices over32 reset/phase/source/equal-prior states. This is not a proof for arbitrary unequal initial state.

Run `python3 fpga/next/test_timing_ready73_control_lemma.py` for25 explicit hash-admission controls, including both complete forms, per-file mutation/missing-file rejection, all eight old/new combinations and unreviewed bank forms. Encoder/adapter bytes are identical between old/new forms, so the eight combinations reduce to two complete byte triples; there are no distinguishable mixed triples to reject. Unknown hashes remain rejected. Supply `--export <fresh-native-export>` to additionally verify full real bytes and the complete direct connection/control proof. Hash-only fixtures are labeled and are not RTL behavior.

The source lemma grants only the narrow selected-control dead-fall quotient. `native_mac_roles.tcl` still independently checks the actual mapped encoder clock/reset/FF chain, permitted control-fall shape and low/high equations. No timing constraint, clock exception, false path, reset recovery/removal requirement or RAW/managed hold obligation changes. Source admission is not mapped topology, timing, CDC, PHY or board qualification.
