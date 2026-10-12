# Final board entry: source/configuration contract

The single explicit `fpga/next/board_final.py` entry binds one reviewed CPU native-option manifest, its SHA-256, the complete exporter configuration SHA-256, reviewed export source closure SHA-256, native MAC T1, and JTAG USER2. The selected profile for this revision is the published ABC46 plus `--shared-lane1-owner-match` and `--direct-rank1-memory-source-ids` (48 native options), over publication `503f47c0f83411895b92bdd766e5c33ababf8bad`, tree `51af502db9c15961150f76fc46f709d0400b75c7`. The entry binds completed CPU, native and same-object NEMU qualification and fails closed if those reviewed identities change. The three-option memory-preparation/drain/shadow candidate is excluded. The actual native profile/fabric snapshots have 156 core fields, 66 profile fields and zero fixture overrides. The final selection binds those actual products and byte-identical CPU products; preflight expectations cannot qualify the selection.

The historical `fpga/next/board_t1.py` path remains the exact ABC46 + T1 rollback entry. Its Python implementation and JSON profile are unchanged. The generic `export.py` tri-speed path still defaults to T1 OFF. The new entry explicitly selects T1 ON through the existing physical-top generic and does not add a CPU emitter option or change hardware/CSR semantics.

## Supported commands

```sh
# Read-only preflight: no output directory, elaboration, or FPGA execution.
python3 fpga/next/board_final.py --output build/final-board

# Future authorized native export only; does not synthesize or implement.
python3 fpga/next/board_final.py --output build/final-board --emit

# Read-only verification against the exact reviewed source and profile.
python3 fpga/next/board_final.py --verify-export build/final-board
```

No manual CPU option list is accepted by this entry. The JSON profile includes every selected native option, CPU100 and full-capacity configuration binding. The native exporter remains the only route that constructs the hardware command and stages the real tri-speed and BSCAN artifacts.

## Required physical consumer

The actual `board/native-mac-mode.tcl` is staged by the unchanged `board_t1.stage` helper. Sourcing it alone does not run synthesis. A future authorized physical flow must explicitly source it and call `valence_native_mac_synth_design` with the board part and other reviewed synthesis arguments. That entry owns the exact top and `NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=1`; top/generic overrides are rejected. The same staged file provides `valence_native_mac_assert_mode u_rgmii`, a read-only mapped mode audit that still must be executed on the actual synthesized netlist.

The existing exact USER2 post-synthesis guard, BSCAN timing/audit contract, tri-speed constraints, and source-matched reports remain required. Three-rate MAC qualification still covers 10/100/1000; reset/CDC/RDC, clocks, PHY behavior, complete constraints, STA and board acceptance remain separate. CPU100 is an unchanged target, not a newly measured frequency result. No local `run_route` script is modified or automatically redirected by exporting.

## Binding and validation scope

`export.py` includes the final entry, final profile and chosen CPU manifest in the normal source inventory. The entry checks the reviewed source closure (excluding its own self-referential entry/profile files) and uses the exporter’s existing full-profile hash gate before any emitter execution. After a native export, it validates the exact CPU argv, complete profile, complete source inventory, staged T1 mode, tri-speed sources and rates, USER2 source/artifact hashes, required USER2 gate, RTL inventory and synthesis filelist. It writes `board/final-board-profile.json` and binds that file into the export receipt. Any binding failure leaves the receipt failed.

The focused Python suite uses a clearly marked synthetic emitter fixture and the real exporter/staging helpers. Its Tcl test executes the exact staged consumer against a `synth_design` mock and checks the complete command and rejected overrides. These checks establish source/configuration/consumer wiring only. They are not CPU, native RTL, NEMU, FPGA synthesis, mapped topology, STA, physical generic-consumption, PHY or board evidence. The retained CPU results are Sv39 191,618 and Bare 194,153 inclusive cycles, both exactly matching the original ABC baseline. The entry-only bridge does not rerun CPU, native RTL or NEMU. Its retained-evidence checker additionally requires complete Sv39/Bare parity in all 12 metric/raw sections, the actual full-board native receipt, and the completed NEMU receipt linked through its strict projection to the exact qualified CPU object hashes. NEMU covers two short physical integer M-mode inputs and PC/GPR/memory negative controls; it is not VM, FP, CSR, permission, concurrent DMA or performance coverage.

```sh
python3 fpga/next/test_board_final.py
python3 fpga/next/test_board_t1.py
```
