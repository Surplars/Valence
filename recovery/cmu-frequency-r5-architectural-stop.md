# I1 architectural-stop endpoint, not CMU clock-gating support

This isolated stage adds `externalQuiesce=false` constructor options to the real
I1 core, cached core and common I1 tile. Disabled configurations retain their old
ports and behavior. No platform/CMU command is connected, no runtime frequency
whitelist is opened, and A1 does not implement this endpoint.

When enabled, the CPU-domain four-phase level protocol is:
1. Raise `quiesceRequest` and hold it until `architecturalStopped` is observed.
2. Unexecuted IF/ID work is discarded. Already offered fetch requests remain
   stable until accepted; their replies are consumed as killed. No new frontend
   work enters RF/EX. Existing backend owners continue through real completion,
   including stores/AMOs, MDU, AIA and external FENCE.I maintenance.
3. `architecturalStopped` requires empty pipeline and fetch offer/response owners
   plus no pending WB recovery. It means no instruction retirement, trap or core
   memory request, NOT dirty-cache publication or whole-system drain.
4. Deassert the request only after acknowledgment. The release edge is a bubble,
   then fetch restarts from the architectural next PC including final committed
   branch/trap/xRET recovery. Early request withdrawal is a protocol assertion.

IRQ trap entry is inhibited while stopping/held and on the release edge; IRQ
sources and CSR state are not reset or cleared. Level IRQ and upstream IMSIC
pending semantics remain intact. This is not a new promise to latch arbitrary
one-cycle interrupt pulses that the existing platform does not retain.

Coherence probes, responses, GrantAck, uncached adapters, cache/translation
maintenance and the time/MSI paths are not frozen. Further private-cache owner,
Home/DDR/fabric drain, epoch, safe gating, official MMCM configuration/DRP and
relock integration remain necessary before a complete rate-change ACK is safe.
Transport-empty and architecturalStopped must not substitute for that ACK.

The frozen performance implementation at366a643 remains a separate source
revision. This change does not establish its physical timing or board results.
Final runtime policy remains hardware default50MHz, optional U-Boot and supported
BootROM-to-Linux boot; software need not raise frequency before Linux can boot.

## Focused validation scope

The directed single-clock GSIM harness instantiates the real fpga8 core with
iterative M, A, delayed external FENCE.I and four PMP entries. Independent raw
instruction words and explicit PC/result/side-effect ledgers check stop offsets
through a finite DIV/store/AMO/load/branch/FENCE/ECALL/MRET program plus pending
software IRQ. It is not a replacement for full cached/coherent-system testing,
FP or IMSIC/AIA transaction coverage, DMA probes, asynchronous clock control or
physical timing. A wrong-result oracle must fail. Existing failed attempts are
preserved separately and are not retroactively labeled passing.

Run from the repository after sourcing the prepared environment:
`GSIM_CXX=clang++-19 python simulator/gsim/i1_external_quiesce.py --tag FRESH_TAG`.
Run only the affected Scala elaboration tests:
`mill --no-server IonSoC.test.testOnly inorder.I1ExternalQuiesceSpec platform.CommonCpuTilesSpec`.

## Directed trace finding: legacy grouped one-hot recovery

The first enabled stop sweep exposed a latent legacy recovery-PC issue at ECALL:
trap target0x80000100 was recorded as0x8000012c by OR-ing the old sequential PC.
`I1ExecuteDatapath.operand` groups four values as3+1; Chisel's singleton `Mux1H`
returns its payload without gating it. The generated FIR and GSIM C++ both show
an unconditional OR of the fourth value, not a simulator edge artifact.

This isolated endpoint uses an explicit trap/mret/sret/sequential Mux only for
its enabled architectural restart register. The disabled legacy datapath is
preserved for comparison with the frozen performance run. This is not a claim
that the legacy helper is correct: its other callers and broader repair need a
separate reviewed stage. Original failure receipts and the offset199 trace are
retained under build/gsim/i1-external-quiesce-20261021-precise-stop-v2.
