# R35 measured setup follow-up

Evidence: `r35-routed-native-summary-20261023.zip`, SHA256
`7ff672941b8069a5f7b5cf82d16bd8cd6798d67c2a46ed42f5a47392acf4eacb`.
The R35 routed checkpoint retains WHS +0.010 ns with zero hold failures. These
changes have NOT yet been routed and do not establish a new maximum frequency.
CPU300/fabric250 constraints stay unchanged.

## Actual old/new worst paths

- CPU: R34 memPacket address to resume FIFO issue CE: data 4.771 ns,
  skew -0.275 ns, slack -1.949 ns. R35 TLB fastReadTag[14] through
  dt.ready/physical.valid, data-cache quiescent, privateDrained/runtimeHeld,
  to runtime cpuObservation held[3]: 20 LUT levels, data 5.742 ns
  (logic 1.492, routing 4.250), skew -0.309, slack -2.869.
- Fabric: R34 staged TX length through descriptor arithmetic to txSent CE:
  data 5.835 ns with 11 CARRY8s, skew -0.095, slack -2.167. R35 crossing
  FIFO2.valid through scalar data selection, descriptor allowed, global legal
  write, same-edge STOP priority, launch to txAddress[22] CE: 20 LUT levels,
  no CARRY8, data 6.415 ns (logic 1.736, routing 4.679), skew -0.013,
  slack -2.665.
- Recovery: R34 AON reset to raw-reset stage had short 0.245 ns data but
  -3.557 ns skew. R35 is a DIFFERENT path: cpuRelease/release_0_reg[2] to
  icache replacement_26 CLR, 5.020 ns data, of which 4.940 ns is one net
  routing with fanout 5,984. Skew -0.108; slack -2.038.

Thus the reported regression is not evidence that the two old cuts failed,
nor predominantly a clock-root/skew regression. Other deep control cones and
reset distribution now limit the reported minimum slack.

## Exact TX STOP control cut

Packet DMA now supplies the queue with the original control request fire,
qualified only by window, known offset, 64-bit size, full byte mask and write.
Queue derives STOP from that qualifier, full data == 16, offset == 240 and
registered enabled. At this offset all unrelated RX/TX register legality
clauses are vacuous, and command16 legality is exactly enabled.

The original fully checked write still controls every MMIO state mutation,
POST, POP, staging field, response, and STOP latch. Only same-edge cancellation
and launch inhibition use the narrower equivalent predicate. A live assertion
compares it against the old accepted legal STOP every cycle. No acceptance
point, queue stage, latency, reply order, capacity or packet bandwidth changes.
Unaccepted STOP must not inhibit launch; accepted invalid commands and disabled
STOP must not acquire an owner or cancel a packet. POST and STOP cannot both be
one accepted register beat, but POST remains able to coincide with an older
pending descriptor launch. Completion/POP behavior is unchanged.

Checks: independent Python law covers 196,608 access cases and 3,145,728 priority
combinations. This is not HDL simulation. The existing GSIM queue-event fixture
now exercises the new input and includes unaccepted STOP, illegal command and
disabled STOP cases, in addition to STOP-vs-launch, concurrent POST/launch,
completion/POP, high addresses and adjacent field-write/POST cases. Combined
Scala compile and these HDL checks are pending integration, not claimed passed.

## CPU deliberately unchanged

Do not register runtimeHeld blindly: final-close commitment and sticky fault
monitor use live private/probe emptiness. A delayed true can hide a new probe.
A mailbox-only snapshot moves almost the entire long cone to its own register,
with little demonstrated benefit. Separating TLB request-owner predicates from
cache/probe-owner predicates needs a dedicated correctness proof and is not
included in the functional DVFS/performance batch. CPU setup remains unresolved.

## Bounded reset physical experiment, next combined implementation only

1. Start from the newly combined placed candidate, preserve an immutable baseline
   checkpoint. Do not modify the accepted R35 routed checkpoint or relax timing.
2. Re-identify the *actual* worst recovery source and load pins, not a wildcard
   assumption. Record source REF_NAME, ASYNC_REG/DONT_TOUCH, connected net(s),
   fanout, load clock domains, locations, and max/min recovery/removal paths.
   Stop if the driver is no longer the CPU release final stage, if multiple
   drivers are found, or if loads cross unrelated clock/reset domains.
3. Inspect the installed Vivado version's documented physical fanout-replication
   options before selecting a targeted optimization. The release pipeline is
   marked ASYNC_REG; do not clear that attribute, bypass the final stage, or
   replicate independent asynchronous synchronizer chains. Such chains could
   deassert on different cycles. A legal physical replication must retain the
   same final-stage D/clock/PRE and synchronous deassertion behavior and leave
   the first synchronizing stages intact. If Vivado protects this driver and
   cannot prove that transformation, stop and report rather than forcing it.
4. At most one selective physical optimization and incremental route as part of
   the already planned combined implementation. No broad blind MAX_FANOUT,
   reset false paths, multicycle exceptions, or extra reset latency.
5. Compare both setup/recovery and hold/removal with baseline, all CPU/fabric
   and RX lane constraints unchanged. Reject the experiment on any newly
   negative hold/removal, unrouted net, DRC failure, CDC/reset topology change,
   or worse combined result. Preserve baseline and report the exact limiting
   path if the selective optimization is unsupported or ineffective.

This is an unexecuted bounded plan, not a claim that Vivado can replicate this
ASYNC_REG driver or that recovery has been fixed.
