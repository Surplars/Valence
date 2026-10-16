# Slice2 full BootROM static stack qualification

The complete TUI + posted-RX netboot + JTAG firmware, unchanged 8KiB stack, has a conservative **1280 B static frame-sum envelope** for monitor execution including trap recovery. Remaining reserved stack space is6912 B. This is a static bound under the assumptions below, not measured high-water usage or blanket payload/interrupt safety.

## Evidence and result

GCC14.2.0+19, original -Os full firmware configuration plus only -fstack-usage and -fdump-ipa-cgraph. All emitted BootROM C stack qualifiers are `static`; no dynamic/VLA entries. Largest individual frames are288 B (board_netboot_receive and nb_tftp_receive). firmware_crc_update is a leaf with0 B stack. Full ROM SHA256 remains d7cbab6e9f9639aac3ebab2c5be6d1a202ab15cd888c103dec5349a6720b1082, byte-identical to the previously qualified slice2 full image.

| Entry or component | Conservative frame sum B |
|---|---:|
| reset → boot_main envelope |1264|
| boot_trap → boot_recover envelope |1280|
| board_netboot_pending subtree |1024|
| nb_tftp_receive subtree |736|
| verify callback subtree |80|
| verify_image subtree including quiescence/failure output |368|
| tui_progress subtree |112|
| firmware_crc_update |0|
| monitor_run_diagnostic through saved monitor frame |176|

The conservative graph includes **every initialized nb_ops callback at every protocol indirect call**, even combinations that cannot happen (for example send_frame → prepare_verify). It also sums caller frames across tail calls after their real frame may have been released. Therefore the maximum witness in analysis.json is an overapproximation path, not a claimed feasible trace or measured peak. No graph recursion remains after treating assembly stack transitions explicitly.

Relevant normal-entry chains, whose frames are not simultaneously all live across successive phases:
- Stream CRC: boot_main16 + boot_loop224 + board_netboot_receive288 + nb_tftp_receive288 + nb_crc_update0 + firmware_crc_update0 =816 B.
- Optional protocol verify callback: same816 + verify80 =896 B (the current pending-finalCRC path deliberately skips this inner verifier).
- Final verification/progress: boot_main16 + boot_loop224 + verify_image112 + tui_progress64 + tui_number48 =464 B.
- Final verifier quiescence/failure-output subtree gives16+224+368 =608 B. CRC processing and progress calls are sequential, not nested inside the CRC function.
- Trap-recovery entry adds16 B relative to boot_main for corresponding paths.

The actual reserved monitor stack is[0xffffa000,0xffffc000). A1280 B envelope reaches0xffffbb00, still inside it. Globals end0xffff9ec0 leaves320 B before the reserved stack; that globals headroom is not substituted for stack space.

## Boundaries and assumptions

- Source audit identifies one stack-local nb_ops initializer with targets now/send/recv/store/verify/protocol_stage/received_frame/prepare_verify. Analysis assumes these pointers and control flow are not corrupted. Unrecognized indirect-call functions cause failure.
- Three boot_loop indirect `jr` sites are compiler switch jump tables, not calls. Script decodes all51 signed entries and checks they remain within boot_loop. Addresses and assembly manual review are bound to the exact ROM SHA; another compiler/build must be requalified.
- run_image saves128 B on the monitor stack, sets sp to __app_stack_top, and jumps to an external payload. External payload and independent diagnostic runtime stack are excluded; the saved monitor frame is included. Their safety requires separate qualification. Diagnostic builder uses a separate16KiB payload stack.
- _start and boot_trap disable mie and clear mstatus MIE/MPRV. boot_trap resets sp to __boot_stack_top before boot_recover, so normal interrupted frames are discarded rather than added. Arbitrary nested faults during recovery, externally re-enabled interrupts, NMI-like platform behavior, and invalid payload returns are not proved by this static analysis.
- All finite sums assume the emitted static frame metadata is correct and no unmodeled assembly changes sp. The three hand-written entry/switch functions are manually accounted for. No target stack-canary run was performed.

## Reproduce

Provide the existing pinned six CoreMark files required by build_monitor_diag.py in simulator/build/coremark-src, then:

    python3 fpga/firmware/build_stack_usage.py --out /path/to/isolated/output --prefix /path/to/riscv64-unknown-elf-
    python3 fpga/firmware/audit_stack_usage.py --out /path/to/isolated/output

The first command uses the original build.py and required full options without editing it, captures every compiler command, writes .su and linked disassembly, then audits. The standalone experiment is crc-slice2-stack-r1; its reproduce/ run exercised this committed portable entrypoint. Raw .su and analysis.json are retained under docs/validation/crc-slice2-stack-r1. Negative mutations ROM drift, dynamic qualifier and missing frame are rejected. No DUT compilation or target simulation is involved.

## Canary option and cost

The existing frozen CRC CPU fixture deliberately rejects UART MMIO and lacks a complete interactive full-ROM netboot environment. It cannot cheaply provide an end-to-end full-ROM netboot canary result unchanged. A canary experiment would require a reviewed full-ROM UART/GMAC stimulus host and a precise post-initialization stack fill/measurement hook (or monitor SP tracking), while preserving live stack contents, DMA ownership and final verification. The recent tiny CRC16-row CPU run alone took roughly4minutes; a full firmware interaction cannot be responsibly promised that cost. No such long run or hardware/ABI change was started. A bounded SP observer plus a short scripted full-ROM workload is a future option once those host peripheral contracts exist.

## Independent-review hardening

The initial script printed a stack limit without enforcing it and treated every same-function branch target as internal control flow. Those tooling gaps are now closed without changing the fixed-ROM result:

- Every emitted function is traversed for cycles, not only report roots. The complete frame-sum envelope must be <=8192 B; negative frame metadata is also rejected.
- JAL/JALR link behavior is decoded from the instruction rd field. A linked self-call creates a graph cycle and fails; an ordinary same-function jump stays internal. Cross-function tail jumps remain conservatively charged as calls.
- The production CLI binds the ROM plus the reviewed disassembly and every BootROM .su file to stack_usage_snapshot.json. Only absolute source directory prefixes and the disassembler ELF filename are normalized; frame sizes, qualifiers, source positions and instruction data remain hashed. Additional/missing metadata files fail binding. This is deliberately a fixed-GCC14.2 artifact qualification, not a generic proof for arbitrary builds.
- Reanalysis of both already-produced build directories gives the unchanged1264/1280 B results. No ROM/CPU rebuild was needed.

Reproduce the added focused tests:

    python3 fpga/firmware/test_stack_usage.py --out /path/to/qualified/output

Nine cases cover ROM/metadata mismatch, dynamic/missing frame, exactly8192 B (PASS),8193 B (reject), direct self-JAL and self-JALR (reject), and internal jump (PASS). Semantic negative tests call the internal analyzer after deliberately editing a copied fixture; they do not merely stop at the snapshot hash gate. The production CLI has no flag to bypass snapshot validation. Results are in hardening-tests.json.
