# Native performance300 integration evidence

Exact frozen production: **eada605956c65e24f0d15380a28243e1f6953281**. At completion it matched the current main production sources (the checked main HEAD and empty production diff are recorded in summary.json). This does not authorize signing off an older 366a643 physical-route checkpoint as the newer hardware.

## Actual results

Fresh Scala compile, emission and Icarus/VVP executable; unchanged guest passed all UART/DDR/FENCE.I/timer/MSI/signature conditions. All three negative controls were rejected by their precise HDL oracles, not by wall timeouts. The exact production ROM SHA256 9b7b73d044f0c6a457f5ed7c3ae2f332aa3b076d26ddf65bef577fe24278e80d passed all 53 serialized banner bytes in 2669.321 seconds: 671,891 CPU cycles and 56,969 retired instructions.

The new banner used an explicitly approved 3600-second wall budget, while retaining the same 1,000,000 CPU-cycle bound, clocks, ROM and full byte/coverage oracles. The earlier 366a643 run is preserved as FAIL: 45/53 correct bytes when its unchanged 2400-second wall budget expired. Its initial zero-AR-stall coverage failure is also retained. The host was strengthened to force two real DDR waiting edges per AR before its periodic mask; no coverage assertion was removed.

## Compact provenance

Run `python3 verify.py` to verify the exact decompressed new guest receipt, losslessly reconstruct the exact new banner receipt and validate every published simulation log against original receipt hashes. A single full source/classes/RTL/tool binding is retained in the gzip; the banner delta avoids copying that same large mapping twice. Old run summaries explicitly label omitted large maps and preserve their canonical section hashes plus original receipt hashes; their complete original receipts remain unchanged in the 366a643 frozen evidence tree. They are historical evidence, not a current source qualification.

## Reproduction

Use a clean eada605 worktree and the three reviewed simulator/gsim/common/cpu_boot runner/TB/README files from this change. Reuse only verified tools, unchanged guest inputs and the exact production ROM, never prior classes, emitted RTL, vvp or PASS. Compile IonSoC.test.compile, save its successful compile receipt, then run platform.CommonMachinePlatformMain with i1, --programmable, --clock-profile=performance300-static and that --compile-receipt. Exact emitted/compile commands, tool paths/hashes, guest sources and all native commands are retained in the receipts.

Run cpu_boot_native.py on a fresh output with --profile i1 --clock-profile performance300-static, the new emission/guest paths, --maxcycles 100000 and all three --negative uart/drop-b/drop-read flags (default 600-second command budgets). Then use its exact new vvp and receipt for --firmware-only, --firmware-bin, --timeout 3600 and the explicit --timeout-reason retained in the banner receipt. Banner retains the default 1,000,000-cycle bound. Source and class hashes must remain stable throughout. Do not omit original production assertions or lower hardware capacities.

## Scope

Native digital integrated boot evidence only, **not GSIM**, not complete packet/JTAG/reset/CMU coverage, not a fabricated common-platform-affected-short aggregate, and not physical timing, FPGA/board or Linux boot qualification. Board/route evidence must independently match the latest production closure.
