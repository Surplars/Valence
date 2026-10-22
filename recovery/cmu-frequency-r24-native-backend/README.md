# r24 native FPGA clock backend, cloud transaction evidence

This receipt covers the FPGA backend source in this branch, not the separately
integrated Scala CMU/platform candidate. Source hashes and base commit are in
receipt.json. Production sources and native local instructions are under
fpga/common/dynamic. No Vivado, xsim, Verilator, user-computer operation,
bitstream, or remote publication was performed for this evidence.

Result: PASS_BEHAVIORAL_ONLY_NATIVE_QUALIFICATION_PENDING.

* 28 combined domain behavior checks, including independent CPU/fabric50→100→50,
  retained state, AON continuity, unsupported55 rejection, readback mismatch,
  delayed/permanently missing DRDY, lock failure/loss, close-tail loss,
  backpressure, boot50 restoration and cold reset with old DRP in flight.
* Missing raw clock, missing managed clock, fresh-close token, and one-AON-cycle
  disable/reopen observer checks pass.
* Five standalone DRP reset boundaries pass: unsampled DEN, completion during
  reset, completion exactly at reset-exit, reset after timeout, permanent loss.
* Two DRDY fault checks pass: stretched DRDY delays new DEN; stuck-high
  DRDY reports an error and fails closed after the bounded quiet deadline.
* Fake closure, fake resume and wrong-rate negative controls each fail on the
  expected oracle. These are the only expected nonzero execution exits.
* Vendor-directed TB syntax/oracle smoke passes under the behavioral model with
  VENDOR_PRIMITIVES=0. It is explicitly not a vendor primitive run.
* 81 existing/new FPGA Python contract tests pass, including static profiles and
  explicit dynamic topology selection. Five specific Tcl mock contract checks cover exact pre-synthesis targets and
  rejection of relaxed CPU/fabric, changed fixed frequency and lost UI-master
  relationships. These are not native Vivado timing runs.
* Actual generated CommonMachinePlatform from the platform worker passes shell
  port_check (162 ports,118 connections), including all38 backend pin directions
  and widths. Header and source hash are saved separately. This emit has
  hardwareClocks=false; production emit and combined functional simulation are
  still pending. It does not qualify hardwareClocks=true or actual primitives.

Independent source review caught and corrected three actual implementation
holes before freezing: close-tail lock loss was exempted too early; restart
witnesses could persist across a short disable; DRP ownership was forgotten on
common cold reset. A fourth boundary correction prioritizes simultaneous DRDY
at reset-exit. Each has explicit regression coverage. Register-map review used
AMD XAPP888 v1.8 tables1/2/14/15; no M/D/lock/filter words are written.

Qualification remains absent: actual UNISIM behavior and frequency/glitch
checks, integrated CMU/fixed-MAC epoch fault matrix, mapped CDC/RDC/CE timing,
CPU300/fabric250 stress-target timing, all admitted runtime rate scenarios,
board implementation and firmware/physical acceptance. Encoded50/100 are not
production-supported points. The software whitelist is still empty and
boot50-dynamic board signoff is blocked. Static production profiles retain their
existing independent qualification state and are not upgraded by this receipt.

The dynamic board flow now loads synthesis_targets.xdc BEFORE synth_design.
It overrides only CPU/fabric output timing targets to300/250MHz, validates they
were present (does not silently fix a relaxed synthesis afterward), and checks
fixed rates and UI-rooted relationships again after optimization. Boot50 MMCM
parameter evidence is written separately from stress-clock reports; no target
report is represented as an actual300/250MHz runtime output measurement.

A later production-dynamic-r1 emit also passes the actual production=True port
check (162/118 and38 backend directions/widths) with hardwareClocks=true,
programmableRom=false and the explicit boot50-dynamic/runtime metadata. Its
header and separate hash-bound receipt are saved. The whole emission source
closure and manifest freeze were not accepted: the new TriSpeedManagedGmac
parent hash remains unadmitted pending the platform owner's source/form review.
Its existing control-form oracle passes, but that alone does not authorize
upgrading the old hash whitelist or any hardware qualification claim.
