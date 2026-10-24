package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.platform._
import soc.core.ooo.CommitRecord
import soc.ip.bus.{CdcLevel, CdcResetRelease}

/** Test-only real A1 + Home + APLIC/IMSIC with independent CPU/fabric/AON clocks.
  * There is no fabricated drain proof, clock-gate acknowledgement or backend.
  * Stalls affect actual protocol replies without manufacturing or dropping them.
  */
class CommonA1RuntimeCdcFixture(val testRomWords: Int = 64, testTimer: Boolean = false) extends RawModule {
    require(testRomWords >= 64 && isPow2(testRomWords))
    val boundary = CommonCpuTilePortParams(runtimeMaintenance = true,
        runtimeCancellation = true, runtimeInterruptHold = true)
    val config = CommonCpuProfile.A1.fpga
    val p = config.coreParams
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        // Test programming, physical interrupt sources and stalls are fabric-domain.
        val start = Input(Bool())
        val timerTick = if (testTimer) Some(Input(Bool())) else None
        val program = Input(Valid(new Bundle { val index = UInt(log2Ceil(testRomWords).W); val data = UInt(32.W) }))
        val sources = Input(UInt(64.W))
        val holdMsiReply = Input(Bool())
        val holdReleaseAck = Input(Bool())
        val holdCompletion = Input(Bool())
        val msiReplyBlocked = Output(Bool())
        val releaseAckBlocked = Output(Bool())
        val completionBlocked = Output(Bool())
        // AON requester ports. Tokens are external opaque transaction identities.
        val requests = Vec(2, Flipped(Decoupled(UInt(32.W))))
        val resume = Vec(2, Flipped(Decoupled(new CommonRuntimeAonStatus(boundary))))
        val cancel = Vec(2, Flipped(Decoupled(new CommonRuntimeAonStatus(boundary))))
        val held = Output(Vec(2, Valid(new CommonRuntimeAonStatus(boundary))))
        val result = Vec(2, Decoupled(new CommonRuntimeAonResult(boundary)))
        val busy = Output(Bool())
        val timeoutSelected = Output(Bool())
        val cleanupFault = Output(Bool())
        val epochExhausted = Output(Bool())
        val activeLane = Output(UInt(1.W))
        val activeEpoch = Output(UInt(8.W))
        val activeToken = Output(UInt(32.W))
        // CPU-domain observations and external architectural stop.
        val externalStop = Input(Bool())
        val holdCpuCompletion = Input(Bool())
        val cpuCompletionBlocked = Output(Bool())
        val tileHeld = Output(Valid(UInt(8.W)))
        val retire = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap = Output(Bool())
        val msiAccepted = Output(UInt(32.W))
        val msiAccepted11 = Output(UInt(32.W))
        val msiAccepted12 = Output(UInt(32.W))
        val msiAccepted13 = Output(UInt(32.W))
        val releaseBeats = Output(UInt(32.W))
        val coherentAcquires = Output(UInt(32.W))
        val cpuResumed = Output(UInt(32.W))
        // Fabric-domain observations. Cross-domain counters are compared only
        // after the actual protocol has reached a stable checkpoint in the TB.
        val fabricHeld = Output(Valid(UInt(8.W)))
        val fabricIdle = Output(Bool())
        val msiReplied = Output(UInt(32.W))
        val fabricPrepares = Output(UInt(32.W))
        val fabricResumes = Output(UInt(32.W))
        val fabricCancels = Output(UInt(32.W))
        val fabricTerminals = Output(UInt(32.W))
        val fabricTerminalValid = Output(Bool())
        val fabricTerminalReady = Output(Bool())
        val cpuLinkReady = Output(Bool())
        val fabricLinkReady = Output(Bool())
        val cpuTransportEmpty = Output(Bool())
        val fabricTransportEmpty = Output(Bool())
    })
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    val started = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        val sticky = RegInit(false.B)
        when(io.start) { sticky := true.B }
        when(sticky) { assert(io.start, "boot enable may fall only during coordinated reset") }
        sticky
    }
    val startCrossing = Module(new CdcLevel)
    startCrossing.clockIn := cpuClock; startCrossing.resetIn := cpuRelease.resetOut
    startCrossing.levelIn := started
    val tileReset = (cpuRelease.resetOut.asBool || !startCrossing.levelOut).asAsyncReset
    val tile = withClockAndReset(cpuClock, tileReset) {
        Module(new CommonA1CpuTile(config, boundary))
    }
    tile.io.hold := io.externalStop
    tile.io.inspectRegister := 0.U
    // Test-only factory keeps the original default fixture unchanged while a
    // dedicated architectural fixture can interpose real protocol backpressure.
    def makeFabric(): CommonMachineFabric = new CommonMachineFabric(boundary = boundary,
        features = CommonPlatformFeatures(ethernetControl = false, networkDma = false,
            jtagDownload = false, clockManagement = false), ramBytes = 65536,
        externalDdr = false, romWords = testRomWords, programmable = true,
        externalUart = false, ramResponseDelay = 7)
    val fabric = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(makeFabric())
    }
    val crossing = Module(new CommonCpuClockBoundary(boundary, depth = 16))
    crossing.cpuClock := cpuClock; crossing.fabricClock := fabricClock
    crossing.commonColdReset := commonColdReset
    crossing.cpu <> tile.io.bus
    // Delaying the queued fabric completion at its actual CPU consumer tests
    // the distinction between fabricHeld and the later CPU-held proof.
    tile.io.bus.fabricDrainedEpoch.valid := crossing.cpu.fabricDrainedEpoch.valid && !io.holdCpuCompletion
    crossing.cpu.fabricDrainedEpoch.ready := tile.io.bus.fabricDrainedEpoch.ready && !io.holdCpuCompletion
    io.cpuCompletionBlocked := crossing.cpu.fabricDrainedEpoch.valid && io.holdCpuCompletion
    fabric.io.tile <> crossing.fabric
    fabric.io.transportCpuEmptySynchronized := crossing.cpuEmptyInFabric
    fabric.io.fabricTransportEmpty := crossing.fabricTransportEmpty
    fabric.io.program.get := io.program
    fabric.io.ramProgram.foreach { program =>
        program.valid := false.B
        program.bits := 0.U.asTypeOf(program.bits)
    }
    fabric.io.ddrReady.foreach(_ := true.B)
    fabric.io.sources := io.sources(CommonPlatformAbi.interruptSources - 1, 0)
    fabric.io.timerTick := io.timerTick.getOrElse(false.B)
    fabric.io.uartRx := true.B

    // Real fabric-domain reply owners remain live while test backpressure holds.
    fabric.io.tile.msi.response.valid := crossing.fabric.msi.response.valid && !io.holdMsiReply
    crossing.fabric.msi.response.ready := fabric.io.tile.msi.response.ready && !io.holdMsiReply
    io.msiReplyBlocked := crossing.fabric.msi.response.valid && io.holdMsiReply
    val blockedRelease = (0 until boundary.coherentClients).map { i =>
        val source = fabric.io.tile.coherent(i).d
        val destination = crossing.fabric.coherent(i).d
        val allow = !io.holdReleaseAck || source.bits.opcode =/= 6.U
        destination.valid := source.valid && allow
        source.ready := destination.ready && allow
        source.valid && !allow
    }
    io.releaseAckBlocked := blockedRelease.reduce(_ || _)
    crossing.fabric.fabricDrainedEpoch.valid := fabric.io.tile.fabricDrainedEpoch.valid && !io.holdCompletion
    fabric.io.tile.fabricDrainedEpoch.ready := crossing.fabric.fabricDrainedEpoch.ready && !io.holdCompletion
    io.completionBlocked := fabric.io.tile.fabricDrainedEpoch.valid && io.holdCompletion

    def makeRuntime(): CommonRuntimeEpochBoundary = new CommonRuntimeEpochBoundary(boundary,
        drainTimeoutCycles = 4096, cleanupTimeoutCycles = 16384)
    val runtime = Module(makeRuntime())
    runtime.aonClock := alwaysOnClock; runtime.cpuClock := cpuClock
    runtime.fabricClock := fabricClock; runtime.commonColdReset := commonColdReset
    runtime.io.requests <> io.requests; runtime.io.resume <> io.resume
    runtime.io.cancel <> io.cancel; io.held := runtime.io.held; io.result <> runtime.io.result
    io.busy := runtime.io.busy; io.timeoutSelected := runtime.io.timeoutSelected
    io.cleanupFault := runtime.io.cleanupFault; io.epochExhausted := runtime.io.epochExhausted
    io.activeLane := runtime.io.activeLane; io.activeEpoch := runtime.io.activeEpoch
    io.activeToken := runtime.io.activeToken
    runtime.io.cpuHeld := tile.io.runtimeHeld.get
    runtime.io.fabricHeld := fabric.io.runtimeHeld.get
    runtime.io.cpuLinkReady := crossing.cpuLinkReady
    runtime.io.cpuTransportEmpty := crossing.cpuTransportEmpty
    runtime.io.fabricEmptyInCpu := crossing.fabricEmptyInCpu
    runtime.io.fabricLinkReady := crossing.fabricLinkReady
    runtime.io.fabricTransportEmpty := crossing.fabricTransportEmpty
    runtime.io.cpuEmptyInFabric := crossing.cpuEmptyInFabric
    runtime.io.fabricAllObligationsIdle := fabric.io.allObligationsIdle
    fabric.io.externalMaintenance <> runtime.io.externalMaintenance
    fabric.io.runtimeResume.get <> runtime.io.runtimeResume
    fabric.io.runtimeCancel.get <> runtime.io.runtimeCancel
    runtime.io.runtimeComplete <> fabric.io.runtimeComplete.get

    io.cpuLinkReady := crossing.cpuLinkReady; io.fabricLinkReady := crossing.fabricLinkReady
    io.cpuTransportEmpty := crossing.cpuTransportEmpty
    io.fabricTransportEmpty := crossing.fabricTransportEmpty
    io.tileHeld := tile.io.runtimeHeld.get; io.fabricHeld := fabric.io.runtimeHeld.get
    io.retire := tile.io.commit; io.trap := tile.io.trap.valid
    io.fabricIdle := fabric.io.allObligationsIdle
    io.fabricTerminalValid := fabric.io.runtimeComplete.get.valid
    io.fabricTerminalReady := fabric.io.runtimeComplete.get.ready
    withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val accepted = RegInit(0.U(32.W))
        val identities = RegInit(VecInit(Seq.fill(3)(0.U(32.W))))
        val releases = RegInit(0.U(32.W))
        val acquires = RegInit(0.U(32.W))
        val resumed = RegInit(0.U(32.W))
        when(tile.io.bus.msi.request.fire) {
            accepted := accepted + 1.U
            for (i <- 0 until 3) {
                when(tile.io.bus.msi.request.bits.data === (11 + i).U) {
                    identities(i) := identities(i) + 1.U
                }
            }
        }
        releases := releases + PopCount(tile.io.bus.coherent.map(c => c.c.fire && c.c.bits.opcode === 7.U))
        acquires := acquires + PopCount(tile.io.bus.coherent.map(_.a.fire))
        when(tile.io.bus.maintenanceResumed.get.fire) { resumed := resumed + 1.U }
        io.msiAccepted := accepted; io.msiAccepted11 := identities(0)
        io.msiAccepted12 := identities(1); io.msiAccepted13 := identities(2)
        io.releaseBeats := releases; io.coherentAcquires := acquires; io.cpuResumed := resumed
    }
    withClockAndReset(fabricClock, fabricRelease.resetOut) {
        val replied = RegInit(0.U(32.W))
        val prepares = RegInit(0.U(32.W))
        val resumes = RegInit(0.U(32.W))
        val cancels = RegInit(0.U(32.W))
        val terminals = RegInit(0.U(32.W))
        when(fabric.io.tile.msi.response.fire) { replied := replied + 1.U }
        when(fabric.io.externalMaintenance.fire) { prepares := prepares + 1.U }
        when(fabric.io.runtimeResume.get.fire) { resumes := resumes + 1.U }
        when(fabric.io.runtimeCancel.get.fire) { cancels := cancels + 1.U }
        when(fabric.io.runtimeComplete.get.fire) { terminals := terminals + 1.U }
        assert(!fabric.io.msiError, "real MSI completion returned an error")
        io.msiReplied := replied; io.fabricPrepares := prepares; io.fabricResumes := resumes
        io.fabricCancels := cancels; io.fabricTerminals := terminals
    }
}
object CommonA1RuntimeCdcMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new CommonA1RuntimeCdcFixture, Array("--target-dir", args(0)))
}
object CommonA1RuntimeCdcNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonA1RuntimeCdcFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

class CommonA1WfiRuntimeFixture extends CommonA1RuntimeCdcFixture(256, testTimer = true) {
    val trapCause = IO(Output(UInt(64.W)))
    trapCause := tile.io.trap.bits.cause
}
object CommonA1WfiRuntimeMain extends App {
    ChiselStage.emitSystemVerilogFile(new CommonA1WfiRuntimeFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

/** Real shared atomic owners with test-only backpressure, no fabricated reply. */
class CommonA1AtomicRuntimeFixture extends CommonA1RuntimeCdcFixture(256) {
    override def makeFabric(): CommonMachineFabric = new RuntimeAtomicTestFabric(boundary, testRomWords)
    val observe = IO(new RuntimeArchitecturalObservations)
    val atomicObservations = fabric.asInstanceOf[RuntimeAtomicTestFabric].observe
    atomicObservations.holdAtomicRead := observe.holdAtomicRead
    atomicObservations.holdAtomicWrite := observe.holdAtomicWrite
    atomicObservations.holdMemoryResponse := observe.holdMemoryResponse
    atomicObservations.holdAtomicResult := observe.holdAtomicResult
    for ((name, field) <- atomicObservations.elements if !name.startsWith("hold")) {
        observe.elements(name) := field
    }
    observe.trapPc := tile.io.trap.bits.pc
    observe.trapCause := tile.io.trap.bits.cause
    // This is the exported held proof, not an independent internal-state oracle.
    // The bench additionally verifies that both retirement lanes remain quiet.
    observe.architecturalStopped := tile.io.runtimeHeld.get.valid
}
object CommonA1AtomicRuntimeMain extends App {
    ChiselStage.emitSystemVerilogFile(new CommonA1AtomicRuntimeFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
