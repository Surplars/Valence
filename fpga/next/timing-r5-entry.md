# r5 physical entry

This stages the unique r5 native emission without re-elaboration and launches the
unchanged ready73 synthesis/optimization/placement Tcl. No old CPU qualification
is inherited. Parameter identity remains the exact 177 core / 94 platform fields,
73 ordered options, USER2 BSCAN, reset release and selected-half RAW MAC modes.

Keep generated evidence and outputs outside Git. Only these five new entry files
belong in `fpga/next`. Do not modify the old source bridge or qualification.
The frozen compile source manifest, compiler receipt and native receipt are pinned
separately from the five-file final release inventory. Adding these non-RTL files
does not require CPU rebuilding. Unknown source additions are rejected.

Prepare an evidence directory containing exact `source-freeze-r1.json`,
`compile.json` (from `build/receipts/compile.json`), and `native-emission-r1.json`.
Then run:

    python fpga/next/board_timing_r5.py --source /source --native /native-r1 \
      --evidence /r5-input-evidence --output /fresh/r5-export

Staging verifies all frozen input leaves, exact native file bytes, full actual
constructors, matched wrapper ports and the existing MAC source control lemma.
It is not CPU, mapped topology, CDC, route or board qualification.

After the genuine r5 component + seven positive + eight negative qualification
receipt exists, use the same reviewed local binding contract documented in
`docs/timing-ready73-physical-driver.md`. Set `READY73_EXPORT` to this r5 export;
retain board/IP/package/clock/control CDC inputs and exact discovered USER2 cells.
The legacy variable names are intentionally retained to reuse the Tcl unchanged.

    python fpga/next/run_timing_r5.py --source /source --export /fresh/r5-export \
      --qualification /evidence/qualification.json --binding /reviewed/binding.tcl \
      --vivado /path/to/vivado --output /fresh/r5-physical

The exact cloud-verified qualification receipt SHA is pinned for this candidate.
Its 36 compiled object hashes were checked on the build executor; the physical
consumer does not need those object files. It requires the small receipt evidence
and the actual native RTL. The qualification must hash-check its `evidence_files` relative
to its own directory. Missing/pending/failing receipts, changed native bytes,
changed release files, stale source identity and wrong actual parameters fail
before launching Vivado. All original source, live synthesis-session, MAC,
USER2, BSCAN and timing-constraint gates remain active. Completion means only
fresh synth/opt/place observation. No bitstream is generated and no timing PASS
is manufactured. Test entry gates with `python fpga/next/test_timing_r5_entry.py`.
