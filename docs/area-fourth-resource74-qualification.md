# Fourth resource candidate: bounded multiplier and shared address state

## Candidate contract

This candidate extends the prior three-resource baseline (commit `086ca3ac1637f2fac6e325efdf81573de7494dc2`, tree `e76ab6b9f86531e5ee6f693730e3a9d0fc27b1e7`). It keeps all 177 core fields and 94 profile fields and adds one ordered option, `--shared-memory-address-state`, after the unchanged historical73 options. The complete core/profile/derived-storage delta is sharedMemoryAddressState false to true.

The IntegerBackend bounded-multiplier guard now additionally requires sharedMemoryAddressState. Its existing R16, physical48, full64-token, two-wide and registered-operand constraints remain. The generic PipelinedMultiply constructor remains default OFF. Other matching shared=true profiles are not qualified by this report.

## Verification and evidence provenance

The initial combined candidate used fresh HardFloat, production and test classes and one fresh CPU model with 37 compiled C++ translation units. Seven positives and eight designated negatives passed, with fresh read-only observation bindings and original independent host/guest/service/reference inputs. All seven positive stdout and event files matched both historical and third-resource baselines byte-for-byte. Twenty floating-point conversion cases and retained-load-proof CSR checks ran against those same model objects, including one FP expected-literal corruption and two CSR host-checker negatives. These supplemental negatives are not DUT mutants.

Independent review found the initial multiplier guard also enabled historical73. The corrected source was freshly compiled into separate HardFloat, production and test classes. All nine freshly emitted exact74 FIR/audit/options files and all 307 native output files are byte-identical to the initial tested fourth candidate. No normalization was used. This equality binds corrected exact74 source to the existing tested model and runtime evidence; it does not pretend those runtime commands were rerun from corrected classes.

Fresh historical73 emission from corrected classes verifies sharedMemoryAddressState=false, multiplier tags retained, and separate loadBeat/loadLanes state retained. This is configuration/structure verification only, not new historical73 runtime or complete behavioral qualification.

Corrected qualification receipt SHA-256: `740af40dd4241bec3f6ae9744cbf2b965d03ae6937f117d14e4b2cb8cee774be`.
Raw equality receipt SHA-256: `031d73ead38b7ac1f7481b9eb51fe3c2875a6bbeb5b31c9499c2137fb05aff03`.

## Cycle observations

All matched differences are zero. COPY kernel plus clean-tail is 179571 cycles bare and 191618 Sv39 (drain remains 3). NEMU hot/compressed is 1883/967 cycles. PMP short/word is 1401/1401. Held capture/acceptance remains at 780/781. FP20 is 6151 cycles. CSR completes at 1714 cycles with its retained certificate at cycle 823.

## Structural observations and limits

Native structure removes multiplier pipeline tags and separate loadBeat/loadLanes registers while retaining 16 full-width storeAddress and 16 byte-lane registers. Prior three resource changes and complete constructor audits remain. Only IntegerBackend.sv and PipelinedMultiply.sv change among RTL files versus the third-resource candidate; top/MAC/JTAG files remain byte-identical. JTAG chain 2 is preserved.

No mapped area, synthesis, placement/routing, timing, physical board, CDC or PHY qualification is claimed. No Vivado, bitstream or full regression was run. Native text/register removal does not establish mapped-resource savings. The published exact73 contract remains unchanged.

Independent corrected-source/equivalence review: PASS. Review receipt SHA-256: `2356bcee0fed01d6cda6ec5e19d368da0d3a57bef696034633085cc41968937a`.
