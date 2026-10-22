# r18 managed MAC control park candidate

Status: final native component batch PASS: four independent clock-ratio scenarios plus one extended owner/fault scenario, and four observation-corruption negative controls. No runtime endpoint is connected by this stage.

The optional runtimeControlPark parameter defaults false in ManagedPeripheralBank and TriSpeedManagedGmac. Its controlPark result covers only the MAC source-clock control tail, not UART, legacy CMU, four drain classes, CPU/DMA/Home, DDR, actual gate feedback or DRP. All fixture clocks run. The pin-level PHY is a digital external register responder, not a physical PHY/timing claim.

## Drain versus retention

- New register requests are backpressured at the MAC frontend. An offer made before park remains irrevocable through acceptance; its payload/valid stability is asserted. Already accepted responses always retain their original consumer handshake. CSR drain includes that offer, frontend ownership and same-cycle acceptance.
- Configuration drain requires no dirty image and both consumed-image mailbox acknowledgments.
- PHY park freezes only startup/idle timers. Existing complete policy sequences continue, including page restoration/readback. restartPending is retained. An existing PHY fault prevents phyParked because a failed transaction can leave a non-default page; fault is observable and release permits the original initialization retry. No fabricated completion or forced reset is used.
- MDIO drain requires serializer plus response idle and the real arbiter's active and denied-response owners idle. Media transition must settle separately.
- Four statistics consumers pause, while counters and complete mailbox images retain events. CSR additions use delta.fire, not held valid. Statistics pending reports the destination mailbox view only, not all unsent source increments. It is observable but deliberately does not prevent control park under continuous dropped raw traffic. The existing fewer-than-2^32-increments-per-field-between-consumption bound still applies.
- Packet RX/TX admission is the separate existing r16 interface. Physical pre-admission drops remain counted, not promised lossless. Software stop votes are not cleared by runtime release.

## Integration prerequisites

This is a real component composition, not r10 AON/epoch terminal integration. A future sequencer must close producers and account for requests accepted upstream before parking the frontend. Parking while such an accepted CPU/transport request still needs first presentation here can deadlock its drain; the fixture's direct RegisterPort boundary does not prove that upstream ordering. No whole-system ACK is inferred.

Service-dependent liveness remains: replies, destination clocks and media tails must progress. A nonzero PHY fault conservatively prevents park until the requester releases and existing recovery runs. Runtime cancellation here is release of component votes, not proof of tagged AON cancellation.

MDIO/PHY/watchdog timing still uses elaboration-time source cpuHz; actual frequency switching requires a separate fixed-control or rate-aware solution. No software-recompute assumption or timing relaxation is introduced. Hardware-default-50 goal and CPU300/fabric250 performance targets remain unchanged.

## Reproduction limits and initial attempts

The exact default PHY scheduling waits (startup 5,000,000 and poll 10,000,000 source cycles) did not reach link within the 300-second wall-clock budget. That attempt is preserved as TIMEOUT with unchanged input hashes, not a functional PASS. The test subclasses then shorten only these scheduling waits to 256 and 512 cycles. MDIO divider/bit timing, full page operations, two-poll debounce and all other state-machine timeout constants remain unchanged. The generated comparison changes only the PHY wait-counter width, two thresholds and corresponding zero/increment constants; the other 57/58 modules, including the serializer, are byte-identical. Parameter elaboration checks cover minimum (1,1), chosen (256,512), and rejection of zero/negative waits.

Earlier fixture attempts rejected a stale assertion-name anchor and Icarus packed-array lowering. Neither reached simulation. Fresh emitter disallowPackedArrays resolves the latter without editing generated RTL. Original receipts/logs remain separate.

Both initial and post-factory production-default performance300-static emissions remain 248/248 SV byte-identical to the r16 production-default reference; no normalization is used. This establishes default emitted-text preservation, not formal equivalence or physical timing.

Clock-ratio tests deliberately vary digital edge spacing independently. The 100 MHz / 1.25 MHz values describe the elaborated MDIO divider configuration, not a claim that every stressed test waveform has the nominal physical frequency. Raw ingress overflow stimulation temporarily runs the RX source faster than its drain path; this is digital overflow/retention testing, not legal RGMII electrical timing. Odd-nibble/10–100 Mbps negotiation coverage remains outside this stage.

Later intermediate attempts are also retained: final-r1 passed nominal/rx-fast but the source-fast test checked a physical RX tail after insufficient source-clock waiting. The bench was corrected to wait actual raw-TX edges without changing its expected counts. final-r2 then passed those three ratios but near-ratio did not activate the required skipped-frame coverage event (overflow occurred, skip count was zero). That is retained as FAILED coverage, not waived or relabeled data loss. These intermediate failures remain preserved. The final waveform uses one raw-RX idle cycle so a new SOF actually overlaps retained poison EOF. All four final clock ratios exercise four skipped-frame events and eight overflow events without relaxing the coverage assertions.

## Final native evidence

`final-native/receipt.json` records five positive cases and four independently rejected observation corruptions. All four ratios deliver exactly two RX payloads/status records and two complete TX frames, including independent GMII preamble, payload and FCS checks. Actual raw ingress records eight overflow events and four whole-frame skips while packet admission is closed; CSR totals match the separately observed source event ledger. This deliberately overloaded, short-IFG input is a digital retention test, not a promise to preserve every wire frame.

The extended case preserves an old software MDIO offer across PHY policy ownership, drains the complete page sequence, holds the real CSR reply, and demonstrates observable no-ACK failure on a nonzero page blocking park. Release allows the original initialization recovery without reset. A forbidden software MDIO write follows the actual arbiter denied-response path exactly once, does not reach the pins, and its held CSR response prevents park; an allowed ID read then succeeds. The real composite MDIO response consumer is always ready, so this does not claim externally stalled MDIO-response coverage.

The four negative controls corrupt only observed second RX payload, CSR-drained observation, statistics readback, and second TX payload. The ordinary independent checkers reject each; no direct fatal substitutes for the oracle. Seventeen inline production assertion sites are enabled. Independent verification matched 321 source hashes, 61 input hashes, seven tool hashes, compiled VVP, preprocessed production assertions and every case log. Final receipt SHA256: `9dda5663d7dd92cb65f4a5ad0f58ff7420b8ab7bb134128e59409f14ae490118`.

The same native runner reproduces the batch with fresh output and the source-bound emission receipt: `python3 simulator/cdc/test_managed_runtime_control.py out/cmu-frequency-r18/managed-r4-rtl <fresh-output> --emission-receipt out/cmu-frequency-r18/managed-r4-emission.json --ratios --extended --iverilog <installed-iverilog> --vvp <installed-vvp>`. The test fixture emitter is `soc.ip.ManagedRuntimeControlMain`; the fixed external PHY pin model is an independent digital register responder. Generated RTL and simulator binaries are not committed.

This stage does not qualify tagged AON cancellation, whole-system terminal consumption, DDR/timebase transactions, UART/CMU controls, stopped-clock IRQ preservation, gate feedback, dynamic MDIO/PHY timing, DRP, native physical timing, or board behavior. Production runtime defaults and the rate whitelist remain unchanged.
