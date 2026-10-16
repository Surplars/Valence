# Historical 223453b read-only checkpoint inspection

Verified 2026-10-16 using RapidWright 2025.1.3, the installed exact ZU15EG device,
and the source-only runner in `scripts/cloud/rapidwright_inspect/`.
This is historical placement inspection, **not validation of newer dev code**.

## Provenance and integrity

- Commit: `223453bae0185dcc59b9ea5414ddb266e1f5af93`.
- Original stage: Fully Placed, Vivado 2025.1 build 6140274, physical-r2.
- DCP: 83,857,374 bytes; SHA-256
  `6b2d34c47326d130b4fde46552d9870aaad5ad7e7d608f48aca4cb686cff5928`.
- Readable EDIF: 301,409,838 bytes; SHA-256
  `19e8d63c6555cbd642f5d067a2bbc6f19f2bffbe28433d9537873a668ad7c4a4`.
- Original manifest SHA-256:
  `8ada9a130649422e73c85a28ced2c804b60cbfac327a6413889eceac36fc81cf`.
- Uploaded ZIP SHA-256:
  `1cd2fc61edc61e708f04906cad2c01a0b2254e857d1ccef437ce8c0cdcc3110d`.
- Conversation Library source ID: `libfile_5254f9d921e8819194a36c55da5056fe`.
- All 38 original manifest members passed byte-count and SHA-256 checks before
  inspection and remained unchanged afterward. Original manifest retained.
- Export Tcl and successful completion log show opening this same checkpoint,
  writing readable EDIF/effective XDC and reports, then closing it. No new
  implementation was performed. The earlier failed export is retained as
  provenance and is not used as the successful export.

## Actual read results

| Field | Result |
|---|---|
| Part | xczu15eg-ffvb1156-2-i |
| Design and EDIF top | soc_top_fpga_next_ddr |
| Physical cells | 358,689 |
| Physical nets | 410,772 |
| Site instances | 36,202 |

The full DCP and EDIF loaded without dropping unsupported IP or netlist content.

### RGMII reset

`u_rgmii/serializer_reset` is cited in
`read-only-export-r2/rgmii_reset_setup.rpt`, line 80.
EDIF yields one source and 20 sinks, all mapped to placed physical cells.
Source `u_rgmii/pad_release.pad_release_reset_reg/Q` is at
`SLICE_X95Y43/EFF`; the report endpoint
`u_rgmii/previous_clock_reg/CLR` is at `SLICE_X116Y137/AFF`.
Other loads include fabric CLR/PRE and serializer OSERDES RST pins.

### CPU data net

`u_soc/board/platform/core/core/core/backend/bareOrdinaryRam2` is cited in
`read-only-export-r2/setup_paths.rpt`, line 198. It is the largest estimated
net-delay segment on the first CPU setup path, from privilege register bit 1 to
staged memory-address register bit 47. It is not a globally longest-wire claim.
EDIF yields one source and 33 sinks, all mapped to placed physical cells.
Source `io_posted_starting_INST_0_i_15/O` is at `SLICE_X61Y327/G6LUT`;
the report-path sink `planner_i_88/I0` is at `SLICE_X33Y327/A6LUT`.
Other loads include memoryCanonical and planner LUT inputs.

## Limits

Both selected physical nets contain zero stored inter-site pins/PIPs despite
15/29 associated site instances. Therefore RapidWright's stored site-pin
fanout of zero is not logical fanout; the 20/33 EDIF sink counts are the useful
fanouts and agree with the matched reports. Endpoint queries did not synthesize
missing pins or routing. The supplied route-status report contains 256,476
unrouted nets and 19 nets with routing gaps. No routed path can be reconstructed
for the selected nets from absent PIPs.

No Vivado, downloads, router, netlist modification, checkpoint write, timing
model or STA ran in this cloud inspection. Java was bounded to a 4 GiB heap,
two active CPUs and a 600-second analysis timeout. Placement geometry and
pre-route timing estimates do not establish WNS, hold, Fmax or timing closure.

The portable repository entry was rerun successfully on the same full inputs;
its receipt records 38 source-manifest files verified and `inputs_preserved: true`.
The RapidWright read timer was 14.068 seconds. Endpoint fanouts remained 20/33.
The runner has explicit tool/output roots and optional JDK location; no workspace
path is embedded. Actual checkpoint data and generated results remain outside Git.
