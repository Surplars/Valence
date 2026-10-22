package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcLevel, CdcMailbox, CdcResetRelease}
import soc.ip.debug.{DebugDmiAdmissionBoundary, DebugDmiAdmissionTerminal, DebugDmiPort}

/** Opt-in sequencing of the real DMI admission owner around a runtime epoch.
  *
  * The fabric-side prepare is an offer until the old DMI transport and loader
  * owners have drained. Only a matching debug-clock proof permits that prepare
  * to reach the CPU/fabric runtime machinery. The DMI release decision is not
  * sent until the REAL fabric terminal says that the CPU has resumed.
  *
  * This joins two retained terminals, not two sampled idle bits. The upstream
  * runtime boundary may peek at upstreamComplete to copy it to AON, but must
  * withhold ready until retirementPermit. Its terminalConsumedAtAon receipt
  * releases the copied DMI terminal; that mailbox's consumption ACK releases
  * the original DMI terminal. A further debug-to-fabric retirement receipt then
  * permits the original fabric terminal to retire. No new epoch can overtake
  * either real owner. Connect to CommonRuntimeEpochBoundary with its external
  * retirement barrier enabled; ordinary Decoupled ready alone is insufficient.
  *
  * Short source-link loss is captured with asynchronous assertion in BOTH
  * local domains, independently of clock phase. An active epoch fails closed
  * until common cold reset. Link loss never resets a loader or runtime owner.
  * This is an admission protocol, not permission to gate or change a clock.
  */
class CommonDebugRuntimeSequencer(p: CommonCpuTilePortParams, addressBits: Int = 7,
    emergencyAdmissionStop: Boolean = false) extends RawModule {
    require(p.runtimeMaintenance && p.runtimeCancellation && p.runtimeInterruptHold)
    require(addressBits > 0)

    val fabricClock = IO(Input(Clock()))
    val debugClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(new DebugDmiPort(addressBits)))
    val destination = IO(new DebugDmiPort(addressBits))
    val sourceLinkUp = IO(Input(Bool()))
    val destinationLinkUp = IO(Output(Bool()))
    val destinationOwnersIdle = IO(Input(Bool()))
    val upstreamPrepare = IO(Flipped(Decoupled(new CommonTileMaintenanceCommand(p))))
    val downstreamPrepare = IO(Decoupled(new CommonTileMaintenanceCommand(p)))
    val upstreamComplete = IO(Decoupled(new CommonRuntimeCompletion(p)))
    val downstreamComplete = IO(Flipped(Decoupled(new CommonRuntimeCompletion(p))))
    val terminalConsumedAtAon = IO(Input(Bool()))
    val retirementPermit = IO(Output(Bool()))
    val busy = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val debugHeld = IO(Valid(UInt(p.maintenanceEpochBits.W)))
    val emergencyStop = if (emergencyAdmissionStop) Some(IO(Input(Bool()))) else None
    val fixedFault = if (emergencyAdmissionStop) Some(IO(Output(Bool()))) else None

    private def release(clock: Clock, reset: AsyncReset): AsyncReset = {
        val r = Module(new CdcResetRelease)
        r.clockIn := clock
        r.asyncReset := reset
        r.resetOut
    }
    private val fabricReset = release(fabricClock, commonColdReset)
    private val debugReset = release(debugClock, commonColdReset)
    private val fatalStop = if (emergencyAdmissionStop) {
        val sync = Module(new CdcLevel)
        sync.clockIn := debugClock; sync.resetIn := debugReset; sync.levelIn := emergencyStop.get
        Some(sync.levelOut)
    } else None
    private val linkReset = (commonColdReset.asBool || !sourceLinkUp).asAsyncReset
    private val fabricLinkReset = release(fabricClock, linkReset)
    private val debugLinkReset = release(debugClock, linkReset)
    private def mailbox(width: Int, from: Clock, to: Clock): CdcMailbox = {
        val m = Module(new CdcMailbox(width))
        m.sourceClock := from
        m.destinationClock := to
        m.commonReset := commonColdReset
        m
    }
    private val prepare = mailbox(p.maintenanceEpochBits, fabricClock, debugClock)
    private val proof = mailbox(p.maintenanceEpochBits, debugClock, fabricClock)
    private val decision = mailbox((new CommonRuntimeCompletion(p)).getWidth, fabricClock, debugClock)
    private val terminal = mailbox((new CommonRuntimeCompletion(p)).getWidth, debugClock, fabricClock)
    private val retirement = mailbox(p.maintenanceEpochBits, debugClock, fabricClock)

    private val boundary = Module(new DebugDmiAdmissionBoundary(addressBits, p.maintenanceEpochBits))
    boundary.sourceClock := debugClock
    boundary.destinationClock := fabricClock
    boundary.commonColdReset := commonColdReset
    boundary.sourceLinkUp := sourceLinkUp
    boundary.destinationOwnersIdle := destinationOwnersIdle
    destination <> boundary.destination
    destinationLinkUp := boundary.destinationLinkUp
    source.response <> boundary.source.response
    boundary.source.request.bits := source.request.bits

    private val debugFault = Wire(Bool())
    private val fabricFault = Wire(Bool())
    private val debugFaultSync = Module(new CdcLevel)
    debugFaultSync.clockIn := fabricClock
    debugFaultSync.resetIn := fabricReset
    debugFaultSync.levelIn := debugFault
    private val fabricFaultSync = Module(new CdcLevel)
    fabricFaultSync.clockIn := debugClock
    fabricFaultSync.resetIn := debugReset
    fabricFaultSync.levelIn := fabricFault

    withClockAndReset(debugClock, debugReset) {
        val owned = RegInit(false.B)
        val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val proofSent = RegInit(false.B)
        val decisionReceived = RegInit(false.B)
        val canceled = RegInit(false.B)
        val terminalSent = RegInit(false.B)
        val copied = Reg(new DebugDmiAdmissionTerminal(p.maintenanceEpochBits))
        val failed = RegInit(false.B)
        val incoming = decision.destination.bits.asTypeOf(new CommonRuntimeCompletion(p))
        val decisionMatches = owned && incoming.epoch === epoch && !decisionReceived
        val terminalMatches = owned && decisionReceived && boundary.terminal.bits.epoch === epoch &&
            boundary.terminal.bits.canceled === canceled
        val matchingCopy = boundary.terminal.bits.asUInt === copied.asUInt
        val badPrepare = prepare.destination.valid && owned
        val badProof = boundary.held.valid && (!owned || boundary.held.bits =/= epoch)
        val badDecision = decision.destination.valid && !decisionMatches
        val badTerminal = boundary.terminal.valid && !terminalMatches
        val changedTerminal = terminalSent && (!boundary.terminal.valid || !matchingCopy)
        val protocolFault = badPrepare || badProof || badDecision || badTerminal || changedTerminal
        val healthy = !debugReset.asBool && !debugLinkReset.asBool && !failed && !boundary.fault &&
            !fabricFaultSync.levelOut && !protocolFault
        debugFault := failed || boundary.fault
        fixedFault.foreach(_ := RegNext(failed || boundary.fault, false.B))
        when((owned && debugLinkReset.asBool) || boundary.fault || fabricFaultSync.levelOut || protocolFault) {
            failed := true.B
        }
        // Responses still retire normally; only new source requests are barred.
        boundary.source.request.valid := source.request.valid && healthy && !fatalStop.getOrElse(false.B)
        source.request.ready := boundary.source.request.ready && healthy && !fatalStop.getOrElse(false.B)

        boundary.prepare.valid := prepare.destination.valid && !owned && healthy
        boundary.prepare.bits := prepare.destination.bits
        prepare.destination.ready := boundary.prepare.ready && !owned && healthy
        when(boundary.prepare.fire) {
            owned := true.B
            epoch := prepare.destination.bits
            proofSent := false.B
            decisionReceived := false.B
            canceled := false.B
            terminalSent := false.B
        }
        proof.source.valid := healthy && owned && !proofSent && boundary.held.valid && boundary.held.bits === epoch
        proof.source.bits := epoch
        when(proof.source.fire) { proofSent := true.B }

        val choose = healthy && decision.destination.valid && decisionMatches && proofSent
        boundary.cancel.valid := choose && incoming.canceled
        boundary.cancel.bits := incoming.epoch
        boundary.resume.valid := choose && !incoming.canceled
        boundary.resume.bits := incoming.epoch
        decision.destination.ready := healthy && decisionMatches && proofSent &&
            Mux(incoming.canceled, boundary.cancel.ready, boundary.resume.ready)
        when(decision.destination.fire) {
            decisionReceived := true.B
            canceled := incoming.canceled
        }

        // A sourceIdle level is a receipt only AFTER this exact copy fired.
        terminal.source.valid := healthy && boundary.terminal.valid && terminalMatches && !terminalSent
        terminal.source.bits := boundary.terminal.bits.asUInt
        when(terminal.source.fire) { terminalSent := true.B; copied := boundary.terminal.bits }
        val consumedAtFabric = terminalSent && terminal.sourceIdle
        retirement.source.valid := healthy && consumedAtFabric && boundary.terminal.valid &&
            terminalMatches && matchingCopy
        retirement.source.bits := epoch
        boundary.terminal.ready := healthy && consumedAtFabric && terminalMatches && matchingCopy &&
            retirement.source.ready
        when(boundary.terminal.fire) { owned := false.B; terminalSent := false.B }
        assert(boundary.terminal.fire === retirement.source.fire,
            "DMI terminal retirement lost its retained receipt")
    }

    withClockAndReset(fabricClock, fabricReset) {
        val owned = RegInit(false.B)
        val command = Reg(new CommonTileMaintenanceCommand(p))
        val lastEpoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val prepareSent = RegInit(false.B)
        val prepareAccepted = RegInit(false.B)
        val proved = RegInit(false.B)
        val decisionSent = RegInit(false.B)
        val completion = Reg(new CommonRuntimeCompletion(p))
        val terminalObserved = RegInit(false.B)
        val terminalReceiptSent = RegInit(false.B)
        val debugRetired = RegInit(false.B)
        val failed = RegInit(false.B)
        val incoming = terminal.destination.bits.asTypeOf(new CommonRuntimeCompletion(p))
        val offerMatches = upstreamPrepare.valid && upstreamPrepare.bits.asUInt === command.asUInt
        val completionMatches = downstreamComplete.valid && downstreamComplete.bits.epoch === command.epoch
        val matchingCopy = downstreamComplete.bits.asUInt === completion.asUInt
        val terminalMatches = owned && decisionSent && incoming.asUInt === completion.asUInt
        val proofMatches = owned && prepareSent && !proved && proof.destination.bits === command.epoch
        val retirementMatches = owned && terminalReceiptSent && !debugRetired &&
            retirement.destination.bits === command.epoch
        val changedOffer = owned && !prepareAccepted && !offerMatches
        val earlyCompletion = downstreamComplete.valid && (!owned || !prepareAccepted || !completionMatches)
        val changedCompletion = decisionSent && (!downstreamComplete.valid || !matchingCopy)
        val badProof = proof.destination.valid && !proofMatches
        val badTerminal = terminal.destination.valid && !terminalMatches
        val badRetirement = retirement.destination.valid && !retirementMatches
        val protocolFault = changedOffer || earlyCompletion || changedCompletion || badProof ||
            badTerminal || badRetirement
        val activeLinkFault = owned && fabricLinkReset.asBool
        val healthy = !fabricReset.asBool && !fabricLinkReset.asBool && !failed &&
            !debugFaultSync.levelOut && !protocolFault
        fabricFault := failed
        fault := failed || debugFaultSync.levelOut || activeLinkFault
        busy := owned
        when(activeLinkFault || debugFaultSync.levelOut || protocolFault) { failed := true.B }

        // Capture the stable offer, but do not acknowledge it or stop the CPU.
        when(!owned && healthy && upstreamPrepare.valid && upstreamPrepare.bits.epoch =/= 0.U &&
            upstreamPrepare.bits.epoch > lastEpoch) {
            owned := true.B
            command := upstreamPrepare.bits
            lastEpoch := upstreamPrepare.bits.epoch
            prepareSent := false.B
            prepareAccepted := false.B
            proved := false.B
            decisionSent := false.B
            terminalObserved := false.B
            terminalReceiptSent := false.B
            debugRetired := false.B
        }
        prepare.source.valid := healthy && owned && !prepareSent
        prepare.source.bits := command.epoch
        when(prepare.source.fire) { prepareSent := true.B }
        proof.destination.ready := healthy && proofMatches
        when(proof.destination.fire) { proved := true.B }
        debugHeld.valid := healthy && owned && proved && !decisionSent
        debugHeld.bits := command.epoch

        val forward = healthy && owned && proved && !prepareAccepted && offerMatches
        downstreamPrepare.valid := forward
        downstreamPrepare.bits := command
        upstreamPrepare.ready := forward && downstreamPrepare.ready
        when(upstreamPrepare.fire) { prepareAccepted := true.B }
        assert(upstreamPrepare.fire === downstreamPrepare.fire,
            "debug sequencing accepted a runtime prepare without forwarding it")

        // The CPU/fabric has really resumed before the DMI decision is sent.
        decision.source.valid := healthy && owned && prepareAccepted && completionMatches && !decisionSent
        decision.source.bits := downstreamComplete.bits.asUInt
        when(decision.source.fire) { decisionSent := true.B; completion := downstreamComplete.bits }
        when(healthy && terminal.destination.valid && terminalMatches) { terminalObserved := true.B }

        // Preserve the joined terminal while the upstream boundary copies it to
        // AON. The first receipt consumes only the COPY, never the fabric owner.
        // Once visible, retain valid and payload even on a later link fault.
        // The upstream boundary reports the sticky fault without withdrawing
        // an offered AON copy. retirementPermit blocks both real retirements.
        upstreamComplete.valid := owned && prepareAccepted && decisionSent && terminalObserved
        upstreamComplete.bits := completion
        terminal.destination.ready := healthy && terminalObserved && terminalMatches &&
            terminalConsumedAtAon && !terminalReceiptSent
        when(terminal.destination.fire) { terminalReceiptSent := true.B }
        retirement.destination.ready := healthy && retirementMatches
        when(retirement.destination.fire) { debugRetired := true.B }
        retirementPermit := healthy && owned && terminalObserved && terminalReceiptSent && debugRetired
        downstreamComplete.ready := upstreamComplete.valid && upstreamComplete.ready && retirementPermit
        when(upstreamComplete.fire && retirementPermit) {
            owned := false.B
            prepareSent := false.B
            prepareAccepted := false.B
            proved := false.B
            decisionSent := false.B
            terminalObserved := false.B
            terminalReceiptSent := false.B
            debugRetired := false.B
        }
        when(upstreamComplete.fire) {
            assert(retirementPermit, "runtime terminal consumed before debug retirement receipt")
        }
        assert(upstreamComplete.fire === downstreamComplete.fire,
            "debug sequencing retired only one side of the runtime terminal")
    }
}
