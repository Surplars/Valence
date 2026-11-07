# Actual APLIC to OoO retirement chain

This fixture closes the source-to-processor path in one DUT:

physical source pin -> M/S CommonInterruptFabric -> MachineCore MSI port ->
real IMSIC -> real two-issue OoO pipeline and ROB -> architectural trap/CSR claim.

Unlike the earlier committed-MSU fixture, no committed instruction or trap is
injected by the testbench. Instructions are fetched from a test ROM and execute
through the actual decoder, execution units, system unit and ROB. The harness
checks every retired PC, instruction, register result and next PC against an
independent instruction interpreter, including JAL when the success sentinel and
its following loop retire in the same cycle.

## Deliberate scope

- The program uses Bare instruction addresses. It does not qualify translated
  fetch, G-stage memory faults, guest OS boot, board integration or FPGA timing.
- The harness initializes APLIC registers over their real MMIO ports while the
  CPU is held. CPU instructions configure H/IMSIC CSRs and perform claims. This
  is not a test of CPU load/store access to the APLIC register window.
- There is exactly one physical rising edge and one real MSI in each scenario.
  Larger queues, multiple simultaneous sources and parameter limits retain
  their separate component receipts; this finite chain does not replace them.
- The wrapper is rebound to the clean core's completed, validated full build.
  The runner freezes and hashes its prepared classes, checks all 369 compiled
  Scala source identities against the build's before/after manifests, and
  compiles only the new wrapper. It does not claim to recompile the CPU itself.

## Three real programs

1. Guest file1 selected by VGEIN, delivering a VS external interrupt.
2. Guest file3 selected by VGEIN, verifying the route is not hardwired to guest1.
3. Guest file2 pending while VGEIN selects file1. hgeie routes SGEIP to HS while
   the guest executes. The HS handler retires reads of hgeip and the empty
   currently selected file, changes VGEIN to2, claims the real guest interrupt,
   observes TOPEI/hgeip become zero, and returns to the guest.

Each program also exercises two precise guest-to-HS synchronous exceptions and
returns. Guest IRQs use the actual VS cause translation; the HS summary path
checks the actual SGEI cause. No guest IRQ, interrupt identity or trap result is
substituted by the harness.

The source remains asserted after its rising edge, so the exact one-MSI and
one-interrupt assertions also reject repeated edge delivery. Requests and real
MSI responses are independently held. During every held cycle, the harness
checks valid and payload stability, and each scenario must observe a nonzero
number of genuinely held requests and responses.

## Finite results

All scenarios pass with ASan and UBSan enabled:

- guest1 to VS: 98 retirements, 3 traps, 1,101 checks; 11 held request cycles and
  4 held response cycles.
- guest3 to VS: 98 retirements, 3 traps, 1,101 checks; 11 held request cycles and
  4 held response cycles.
- inactive guest2 to HS: 111 retirements, 3 traps, 1,218 checks; 8 held request
  cycles and 8 held response cycles.

Total: 307 retirements, 9 traps and 3,420 checks. A deliberately wrong destination
oracle fails with its expected diagnostic. Logged `cycles` values are zero-based
execution-loop positions and exclude reset, ROM loading and initial MMIO setup;
they are not processor performance measurements.

The first run exposed a test-oracle omission: it lacked JAL semantics and failed
when the tail loop retired with the success sentinel. The corrected oracle
checks the JAL, rather than dropping the second retirement.

## Reproduction

After the clean integration tree completes its full system build and tests:

```sh
python3 simulator/gsim/aia_retiring_core_acceptance.py \
  --output build/aia-retiring/fresh \
  --core-root /path/to/validated-clean-integration \
  --gsim "$GSIM" --cxx "$GSIM_CXX"
```

The runner checks source/class/dependency fingerprints before and after use and
never writes into the supplied core tree. An optional `--link-permit-file` gates
native compilation when sharing limited build resources; it has no RTL effect.

The core build used here includes the separately verified MSU correction for
RV64 odd EIP/EIE selectors accessed from VS-mode. That CSR exception matrix is
not part of these three interrupt programs and must retain its own receipt.
