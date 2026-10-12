# Preserved prephase contract evidence

These original files are byte-identical to the qualified prephase source/bench/
mutator at published commit `12beb29a75252f29b7ec29e4ba98b6906e904602`:

- `ValenceBscanDebugPort.sv`: SHA256 `3fe23b64f8a40c3bdd77ca0120e52fff7a73501a8968ec92cdbfa1939bc56b39`
- `bscan_qualification_tb.sv`: SHA256 `6edf97f39681aa468f39b01e520cba13b64dd0705dd8c6dcceb5c0c348e7a9f2`
- `bscan_qualification_mutations.py`: SHA256 `cb89b6ef82a48ef1cd375f882bd07e25b6ed2d11def34cab71831b465bdd8f14`
- `qualified-mutations-receipt.json`: SHA256 `557ce2c5ce571cd05b99a464c33630b16817abc430a47e8404d5928d08c5f3bc`

The preserved mutator is historical source evidence; its original module-relative
imports refer to the old tree layout. The receipt preserves all nine original
oracle outcomes. The current serial runner separately compiles the original
bench against the phased production source and requires the exact old immediate
late-revoke failure. That row is `PRESERVED_OLD_CONTRACT_COUNTEREXAMPLE`; it is
never counted as a current passing behavioral control.

The old `sampled_overrun` mutation only changed admission and retained a raw
visible-error cone. Its old failure remains evidence of the changed contract.
Current source/Tcl tests reject that residual raw cone, and distinct functional
controls test the new sampling/independent sticky/CLEAR/reset behavior.
