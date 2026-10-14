# Explicit Young + resident + held CPU native entry

> Historical 71-option entry and evidence. Its original 175/92 constructor/source checks intentionally do not accept the current 177/94 source. For this round's explicit physical candidate use [the ready/raw73 entry](timing-ready73-native-entry.md), which retains registered load-result readiness, resident reuse, held forwarding and RAW MAC while leaving frozen checked flow OFF. Do not reinterpret the historical figures below as current73 qualification or bypass the old guards.

Use the named entry below for the bounded, CPU-tested combination. The default selected profile and the older standalone resident/held entries do not select this combination.

From the repository root, preflight without emitting RTL:

```sh
python3 fpga/next/board_combined_cpu.py --output build/fpga-next/young-resident-held-r1
```

For an explicit native export suitable for subsequent local Vivado staging:

```sh
python3 fpga/next/board_combined_cpu.py --output build/fpga-next/young-resident-held-r1 --emit
```

The output directory must be fresh. Export does not invoke Vivado, generate a bitstream, or change Git. It preserves the existing native board wrapper, resource/file-list, BSCAN chain 2, native MAC local-pad reset release and selected-half staging. Use the resulting `receipt.json` and `rtl/combined-cpu-entry.json` to verify the selected configuration before running any implementation. The existing experimental tri-speed option does not establish physical, CDC, or PHY qualification.

The exact native option vector is the original ordered Young69, then `--resident-memory-payload-reuse`, then `--held-alu-issue-forwarding`, totaling 71 options. The named wrapper accepts only `--output` and `--emit`, so capacities or raw-MAC options cannot silently override this profile. The full constructed products are fixed at 175 core and 92 platform fields: 100 MHz, issue width 2, ROB16, PRF48, LSU4, one resident memory selector and two execution stages. Younger-load seal deferral, resident payload reuse, and held-ALU forwarding are all true; `triSpeedRawClockHandoff` is false.

The native Scala entry verifies the complete measured profile, exact ordered options, all core/backend/ledger products, resident selector structure, and raw-MAC constructor before reporting success. Python independently checks the complete native readback. Missing files, changed option order, duplicate options, unknown values, capacity changes, or type substitutions fail closed. Existing standalone entries and their literal-false historical projection limits are unchanged.

A constructor-only native board gate is also available, without RTL generation:

```sh
mill -i IonSoC.test.runMain ooo.CombinedCpuFeaturesConstructorMain build/fpga-next/young-resident-held-constructors-r1
```

This builds the actual resident/held-OFF and combined/held-ON board constructors and writes their complete profiles/audits. ON differs only in heldAluIssueForwarding; both retain resident and younger enabled. It does not run a CPU model or Vivado.

## Evidence and limits

The unchanged production bytes were tested in the original combination gate with one 36-TU GSIM model: COPY Bare 179,571 and Sv39 191,618 cycles, all 105 fields, seven COPY negative controls, same-object NEMU/PMP with three controls, and one actual held-ALU causal capture with value/owner controls. All nineteen bounded executions passed. COPY shows no cycle gain. Resident reuse retains the component reduction from four to two memory operand readers and from two to one fresh AGUs. Held forwarding removes the completion-ready term from the lane-0 promise; other readiness/capture paths remain.

The named profile source records this bounded CPU evidence separately from native export and physical qualification. Stronger held cancellation/reuse/rollback, mixed-priority and descendant-overlap witnesses remain NOT_REACHED, and broad held integration remains INCOMPLETE. No routed timing, mapped LUT/FF, Fmax, board, CDC, PHY, full ISA, or Linux claim follows from this entry.
