# Qualified three-proof-row native source delivery

## Exact delivery

This source delta starts at dev 8f6b6678e73d21eb1009af62c18a33216adbc505.
The already-published lifecycle/corrected74 changes are retained. Only later
76/77/R3 changes are applied. IntegerBackend.scala and AreaFourthResourceMain.scala
are legitimate later modifications of published paths; no old package is reapplied.
The six historical73/74/75/76/TimingClosure/combined JSON contracts stay byte-identical.
Defaults stay unchanged; this is an explicit candidate entry. Route B is excluded.

## Exact native parameters and inputs

Use fpga/next/three-proof-row-native-recipe.json. It records all 95 named profile
values and pins the complete178-field core and ordered95/178 field references.
ThreeProofRowNativeProfile.scala is the exact explicit constructor used by the
existing native export. There is no old option list, extra toggle, or hidden override.
Proof rows are3, early-load credits2, and LSU owners4. Issue width remains2.

The five files under fpga/next/three-proof-row-native-reference are immutable
qualified CPU metadata. They are mandatory runtime comparison inputs to the native
entry, not executable models or regenerated RTL. Do not replace them with current
output, because that would turn equivalence into self-comparison.

Run entrypoints from the repository root with the pinned Scala2.13.17/Chisel7.3.0,
Java21 and firtool1.135.0 toolchain. After a separately validated compilation,
the exact main and arguments are:

    ooo.ThreeProofRowNativeConfigMain fpga/next/three-proof-row-native-reference

The pure check does not elaborate hardware. The optional native emitter contract is:

    ooo.ThreeProofRowNativeMain <fresh-absolute-native-output> <repository-root>/fpga/next/three-proof-row-native-reference

The emitter requires exactly those two arguments and no hardware configuration
arguments. It compares all field names/order/types/values and the complete derived
profile against qualified CPU metadata. Both the common/MAC audit and post-close
BSCAN/loader audit must pass. Never substitute an older FpgaNextMain option list
or an older Python board/physical exporter.

Native MAC/raw handoff, BSCAN chain2 and RAM loader are enabled; standalone TAP is
disabled. CPU/AON/UART/DDR UI frequencies are100/50/50/250MHz. For future physical
staging, soc_top_fpga_next_ddr requires NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=1 and
NATIVE_MAC_REGISTER_SELECTED_HALF=1 explicitly; its defaults are zero. The native
Scala emitter does not apply these wrapper generics. No board launcher is supplied
or qualified by this delivery.

## Separate evidence boundaries

The original three-row fullCPU qualification passed seven positives and eight exact
negative controls under ASan/UBSan. Sv39 COPY inclusive cycles changed175072 to167439
with fixed accepted traffic; Bare remained173171. This is the qualified isolated
R3 CPU evidence, not a new run of this combined portable publication package.
The earlier query77 results describe two proof rows and remain separate.

The actual native export compiled and returned success with the full178/95/common
fabric comparison and native boundary audit. Its original wrapper receipt then
failed byte-for-byte resource equality because firtool added an exact38-byte
header and removed one final LF. The original failure is retained. Separate read-only
finalization and independent export-result review have now passed, preserving
that original failed wrapper receipt. These results cover the exact qualified
class closure and unchanged native entry, not the portable helper versions.

The portable77 helper versions add fail-closed live-ABI guards relative to the
helpers reused in that export. The priorTimingClosureFields compatibility branch
also changes: it may first project the query77 field only when literally false,
and still requires both named timing switches literally false. Enabled fields
cannot be silently dropped. This safely extends the historical comparison to
the live178/95 product; it is more than an added assertion. The bounded combined-source gate therefore compiles those helpers,
ProfileAbi77, the necessary profile adapters, the unchanged native3 and a new pure
configuration checker against source-identical qualified production classes.
The bounded gate has now passed independent review: eleven fresh test sources
compiled, and the pure178/95 field/value/order/derived comparison passed with17
existing R3 configuration negatives and two enabled-query historical-projection
negatives. Its source manifest, execution receipt and independent result-review
hashes are recorded in the recipe. This r2 revision changes only documentation
and recipe metadata after that run; all70 other payload files remain identical.
No native export, fullCPU execution or physical tool was rerun. Historical report
checks retain their own evidence. A clean full-repository Mill build and an
automatic physical pipeline are not claimed. No production source was modified
by the portability gate or this documentation revision.

## Source-only limits

No generated RTL, model, binary, class, object or Git metadata is included. The
portable recipe fixes all configuration inputs, but is not a tested one-command
clean-build/native/board launcher. Prior source recipes and immutable reference
metadata are retained so a future bounded clean-build gate can be reviewed without
guessing parameters or silently importing an old179/96 Route B configuration.

## Verified local physical preflight and unresolved inputs

The verified local task01a13dc0-0f41-753e-8a60-ec559960d007 observed target
xczu15eg-ffvb1156-2-i and Vivado2025.1 at
E:\Xilinx\2025.1\Vivado\bin\vivado.bat. Windows had22.7GiB free and no heavy
Vivado process. Recheck both conditions before any separately authorized launch.

The existing /home/openion/Valence dev1e90af9 worktree has seven modified files
and one untracked file. The inorder worktree is heavily dirty. DO NOT TOUCH
either worktree: no clean/reset/switch/overlay/build. Use a new independent
candidate directory for any future local staging.

The old reference directory is
/mnt/e/VM/Share/Valence-rtl/Valence-final52-b1bb5d8-20261013-r1. It contains
board/board_ddr.xdc, pl_ddr4_pins.xdc, ip-build/board_ip.xpr with ROM/clock/CDC
XCI, and mig/ZU15EG.srcs/sources_1/ip/ddr4_0/ddr4_0.xci. Its observed DDR4
physical width is32bits and AXI width64bits, with CPU100/AON50/MAC125MHz.
These are available reference inputs, not a qualified current board package.

Final52 lacks a firmware directory, although its ROM XCI refers to
firmware/bootrom.coe. Older coe/bin/elf/even/odd/contract files exist under
/mnt/e/VM/Share/Valence-rtl/Valence-maxperf-1e90af9-20261012-r1/firmware.
Final ROM selection and exact hashes remain REQUIRED before IP regeneration.
Do not select those older files blindly or infer compatibility from their presence.

Old place scripts bind an older hierarchy, and the prior MAC-topology check failed.
They are not a trusted current physical recipe. Future staging must explicitly
consume NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=1 and
NATIVE_MAC_REGISTER_SELECTED_HALF=1 and establish current hierarchy/IP/firmware
compatibility. This preflight adds no execution scope; the current gate remains
fresh test-tool compilation plus a pure config check, with no RTL or physical work.

## Additional physical compatibility boundaries

All309 historical IP artifact hashes match their old inventory. This proves old
artifact integrity only; compatibility with this native export is still unproved.
The older ROM binary is67,280bytes with SHA-256
ee7c2e5fb86d50dad55df532aeb7ccb1d0b91cb37b0b7042d03b446eee362d79;
its COE SHA-256 is
ca0c9a52825208dc93d16e38a6f43a83e3c997b3e425d7cabe8828da23b0b61b.
Its old contract declares CPU100MHz, UART460800baud, DDR2GiB and JTAG RAM enabled,
with a128KiB ROM range[0x80000000,0x80020000). These hashes identify available
old content; they do not select it for the new candidate or prove compatibility.

The actual current InstructionRom.sv instantiates blk_mem_gen_0 with two32-bit
ports and15-bit word addresses over that128KiB range. Actual ROM contents remain
external. A final explicit ROM choice, bin/COE hashes and compatible firmware
contract must be bound before IP regeneration. Do not silently adopt the old ROM.

The historical final52 wrapper exposes only one physical generic and is unusable
for this delivery. Use the latest repository fpga/next/soc_top_fpga_next_ddr.sv
with both explicit generics pinned by the recipe.

Historical script assumptions requiring replacement or revalidation include:
- scripts/discover_roots.tcl: assumes FpgaNextSocTop hierarchy
- run_place:38, board_controls:60/69/111 and final_board_inventory:4/22: old GMAC
- rom_init_snapshot:3: old ROM hierarchy
- trispeed_quarter_constraints:62–65: expects12 selected-half registers but saw11

Do not merely change12 to11. Establish the current selected-half register
topology contract, exact hierarchy bindings and clock/constraint applicability.
Use a new independent staging directory and fresh synthesized hierarchy. Do not
copy historical implementation/hierarchy-roots.tcl into the candidate.
