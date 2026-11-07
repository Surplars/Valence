package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

object SystemOwnerBoundariesConfig {
    val params = OooParams(robEntries = 16, tagBits = 64, commitWidth = 2, machineSystem = true,
        virtualMemoryLevels = 3, pmpEntries = 16, hypervisorExperiment = true,
        floatingPoint = FloatingPointConfig.fullFD)
}

class SystemOwnerBoundaryCompletion(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val exception = Bool()
}

/** Accepted helper events, not fetched instructions or actual backend handshakes.
  * The driver drains real native transfers before every completion and handoff.
  * Simultaneous exception/capture tests helper priority, not MSU reachability.
  * No architectural FP/counter consumer, cancellation or live-owner reset.
  */
class SystemOwnerBoundariesGsim extends Module {
    private val p = SystemOwnerBoundariesConfig.params
    val io = IO(new Bundle {
        val acceptedStart = Input(Valid(new ProtectedSystemStart(p)))
        val acceptedComplete = Input(Valid(new SystemOwnerBoundaryCompletion(p)))
        val commit0 = Input(Valid(new RobToken(p)))
        val commit1 = Input(Valid(new RobToken(p)))
        val integer = Flipped(new DataPort)
        val h = Flipped(new DataPort)
        val fp = Flipped(new DataPort)
        val memory = new DataPort
        val integerBusy = Input(Bool())
        val hBusy = Input(Bool())
        val fpMemoryBusy = Input(Bool())
        val postedBusy = Input(Bool())
        val prefetchBusy = Input(Bool())
        val busy = Output(Bool())
        val cpuBusy = Output(Bool())
        val ownerActive = Output(Bool())
        val ownerToken = Output(new RobToken(p))
        val contextMemoryEpoch = Output(Bool())
        val hMemoryEpoch = Output(Bool())
        val fpMemoryEpoch = Output(Bool())
        val domain = Output(UInt(2.W))
        val retired = Output(Bool())
        val retireMatches = Output(UInt(2.W))
    })

    val owner = Module(new ProtectedSystemOwner(p))
    val selector = Module(new MemoryDomainSelector(p))
    owner.io.start := io.acceptedStart
    owner.io.complete.valid := io.acceptedComplete.valid
    owner.io.complete.bits := 0.U.asTypeOf(new BackendCompletion(p))
    owner.io.complete.bits.token := io.acceptedComplete.bits.token
    owner.io.complete.bits.exception := io.acceptedComplete.bits.exception
    owner.io.commits(0) := io.commit0
    owner.io.commits(1) := io.commit1
    selector.io.hMemoryEpoch := owner.io.hMemoryEpoch
    selector.io.fpMemoryEpoch := owner.io.fpMemoryEpoch
    selector.io.integer <> io.integer
    selector.io.h.get <> io.h
    selector.io.fp.get <> io.fp
    io.memory <> selector.io.memory
    selector.io.integerBusy := io.integerBusy
    selector.io.hBusy := io.hBusy
    selector.io.fpMemoryBusy := io.fpMemoryBusy
    selector.io.postedBusy := io.postedBusy
    selector.io.prefetchBusy := io.prefetchBusy
    selector.io.guestFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    io.busy := selector.io.busy
    io.cpuBusy := selector.io.cpuBusy
    io.ownerActive := owner.io.active
    io.ownerToken := owner.io.token
    io.contextMemoryEpoch := owner.io.contextMemoryEpoch
    io.hMemoryEpoch := owner.io.hMemoryEpoch
    io.fpMemoryEpoch := owner.io.fpMemoryEpoch
    io.domain := selector.io.domain
    io.retired := owner.io.retired
    io.retireMatches := owner.io.retireMatches.asUInt
}

object SystemOwnerBoundariesGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new SystemOwnerBoundariesGsim, Array("--target-dir", args.head))
}
