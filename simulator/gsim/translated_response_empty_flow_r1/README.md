# Matched translated-response empty-flow experiment

This source-only backup records a tested optional CPU parameter. Production defaults remain off. It does not install a board profile or establish FPGA timing closure.

## Result

With the same qualified 275-bit CPU configuration, Ethernet line DMA, final optimized BootROM RX guest, MAC/FIFO endpoint, DDR model and ACK-paced input policy, changing only `translatedResponseEmptyFlow` from false to true improves:

- Full 16 KiB image rate: 41.4823142 → 42.9630164 Mb/s, +3.56948%.
- Interior ACK4→ACK16 rate: 42.5739058 → 44.1228747 Mb/s, +3.63831%.
- Overall observed retirement IPC: 0.89784 → 0.93049.
- Payload CRC IPC: 1.04703 → 1.11559. CRC retains 139570 retired instructions and saves exactly 8192 cycles.

Actual CPU readback validates all 16384 payload bytes and the trailing sentinel after transfer timing. CRC, descriptor ownership, frame order and transaction conservation pass. The interior window covers 12288 image bytes, excluding header/first and final/EOF portions. Outgoing frames use a bounded test capture service; this is not a full TX-PHY, Linux or TCP result. Software phase activity does not uniquely assign stall causes, and no new per-load latency trace was collected. The earlier matched trace demonstrated overlapping hit requests; this result does not imply a one-at-a-time LSU. Physical timing and whole-core area remain unqualified.

## Exact historical source

The tested CPU base is 50cb0c5d4b17318904d6cf818ad23829821d5d93 plus the qualified Ethernet delta. The GitHub repository did not resolve that historical commit at backup time. `historical-qualified-source.tar.gz` therefore preserves the exact necessary source independently: 215 main Scala sources, 31 selected test/emitter sources, required resources and audit inputs, build descriptors, and HardFloat source/licenses. The deterministic archive has 281 source/input files plus its manifest. Its SHA256 is `9d9c10c2103d6b12651fa4dc155eeb0373eaa094cb8cf42a681d21c06c40754d`.

Historical members were checked against the qualified source-enforcement hashes; the seven Ethernet changes and three isolated experiment/audit overrides match their reviewed bindings. The snapshot is inert archival source, not current production RTL. It includes no experimental 824 source or generated model output. `HISTORICAL_SOURCE_HASHES.json` uses only relative archive/project paths. Internal execution manifests, absolute build paths and raw logs remain in the local sealed evidence package and are intentionally omitted here.

The current firmware candidate's local and published commits have identical trees, but the current CPU source is not established as equivalent to the historical tested closure. Among the six focused files, only MappedMachineCore differs, with three optional constructor/pass-through fields: earlyLoadPreparationDescriptor, virtualStoreOperandLookahead and bankedStoreData. The response-buffer wiring is unchanged. This narrow observation does not establish whole-CPU equivalence.

## Reproduction prerequisites and limitations

Extract the snapshot to an isolated tree. Preserve the separation between `historical-repo` and `isolated-experiment`. The latter contains the exact test-only audit expectations and emitter used for the candidate; original historical source remains separate. The selected emitter requires a fresh output directory and the qualified native reference JSON. EXPECTED_OFF/ON record the full compared configurations, but the historical native reference and external model tools still need to be provided from retained qualified inputs.

Required external tools/libraries include Java 21, Scala 2.13.17, Chisel 7.3.0 with its matching compiler plugin, dependencies described by the included build descriptors, HardFloat, the qualified GSIM generator, Clang 19 with ASan/UBSan, Icarus/vvp for the actual MAC/FIFO endpoint, and the RV64 guest cross-compiler. The exact guest/harness/endpoint generation and DDR service dependencies must also be restored and checked before a fresh performance replay. No binaries, classes, firmware images, FIR, generated simulator C++, or object files are included. Fresh-machine reproduction has not been run; this is not a one-command portable benchmark.

The focused authored Scala/C++ buffer and LSU fixtures are included. Their ownership/cancellation/error assertions and independent negative controls passed in the retained qualified environment. They also need the qualified build dependencies; copied source alone is not a new execution result.

The snapshot preserves HardFloat/SoftFloat license texts, HardFloat notices/patches and existing per-file notices. No root project LICENSE was found in the qualified snapshot. This backup does not invent a license or redistribute external tools/libraries.
