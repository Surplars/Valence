package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.axi.{Axi4ClockDomainBoundary, Axi4MemoryPort}
import soc.ip.bus.CdcResetRelease
import soc.ip.timer.FixedTimebaseBoundary
import soc.platform._

/** Test-only gate at a genuine timer reply. Source request, timer state and
  * destination owner remain intact under backpressure. */
class RuntimeFixedTimebaseBoundary extends FixedTimebaseBoundary(runtimeObservation = true) {
    val holdLocalReply = IO(Input(Bool()))
    val localReplyBlocked = IO(Output(Bool()))
    mmio.destination.response.valid := timer.io.mmio.response.valid && !holdLocalReply
    timer.io.mmio.response.ready := mmio.destination.response.ready && !holdLocalReply
    localReplyBlocked := timer.io.mmio.response.valid && holdLocalReply
}

/** Eight-clock integration fixture: real I1/private caches/Home, packet DMA,
  * debug and network owners plus production DDR transport and fixed timer MMIO.
  * Only the external AXI memory endpoint remains an explicit testbench model.
  * Observation and response-backpressure controls never synthesize completion.
  */
class CommonI1RuntimeFixedFixture extends CommonI1RuntimeNetworkFixture {
    override def makeFabric(): CommonMachineFabric =
        new RuntimeNetworkTestFabric(boundary, testRomWords, fixedTimer = true)
    val ddrClock = IO(Input(Clock()))
    val timebaseClock = IO(Input(Clock()))
    val fixed = IO(new Bundle {
        val holdTimerResponse = Input(Bool())
        val holdTimerLocalReply = Input(Bool())
        val timerLocalReplyBlocked = Output(Bool())
        val timerResponseBlocked = Output(Bool())
        val timerRequestFire = Output(Bool())
        val timerResponseFire = Output(Bool())
        val timerRequestAddress = Output(UInt(64.W))
        val timerRequestWrite = Output(Bool())
        val timerRequestData = Output(UInt(64.W))
        val timerResponseData = Output(UInt(64.W))
        val timerResponseError = Output(Bool())
        val timerFabricIdle = Output(Bool())
        val timerLocalIdle = Output(Bool())
        val timerIrq = Output(Bool())
        val timerSnapshot = Output(UInt(64.W))
        val ddrFabricEmpty = Output(Bool())
        val ddrLocalEmpty = Output(Bool())
        val ddrFabricOwnersIdle = Output(Bool())
        val ddrLocalOwnersIdle = Output(Bool())
        val ddrFabricReady = Output(Bool())
        val ddrLocalReady = Output(Bool())
        val timerFabricReady = Output(Bool())
        val timerLocalReady = Output(Bool())
        val ddrQualified = Output(Valid(UInt(boundary.maintenanceEpochBits.W)))
        val timerQualified = Output(Valid(UInt(boundary.maintenanceEpochBits.W)))
        val ddrRetirementPermit = Output(Bool())
        val timerRetirementPermit = Output(Bool())
        val ddrBusy = Output(Bool())
        val timerBusy = Output(Bool())
        val fault = Output(Bool())
    })
    val ddrCrossing = Module(new Axi4ClockDomainBoundary(32, fabric.fpga.ddr.axiIdWidth))
    ddrCrossing.fabricClock := fabricClock
    ddrCrossing.ddrClock := ddrClock
    ddrCrossing.commonColdReset := commonColdReset
    ddrCrossing.fabric <> fabric.io.ddrAxi.get
    ddrAxi <> ddrCrossing.ddr
    // Hold real external responses at the UI edge, not a fabricated fabric edge.
    ddrCrossing.ddr.r.valid := ddrAxi.r.valid && !packet.holdAxiReadResponse
    ddrAxi.r.ready := ddrCrossing.ddr.r.ready && !packet.holdAxiReadResponse
    ddrCrossing.ddr.b.valid := ddrAxi.b.valid && !packet.holdAxiWriteResponse
    ddrAxi.b.ready := ddrCrossing.ddr.b.ready && !packet.holdAxiWriteResponse
    packet.axiReadResponseBlocked := ddrAxi.r.valid && packet.holdAxiReadResponse
    packet.axiWriteResponseBlocked := ddrAxi.b.valid && packet.holdAxiWriteResponse
    packet.axiReadResponseFire := fabric.io.ddrAxi.get.r.fire
    packet.axiWriteResponseFire := fabric.io.ddrAxi.get.b.fire

    val fixedTimer = Module(new RuntimeFixedTimebaseBoundary)
    fixedTimer.holdLocalReply := fixed.holdTimerLocalReply
    fixed.timerLocalReplyBlocked := fixedTimer.localReplyBlocked
    fixedTimer.fabricClock := fabricClock
    fixedTimer.timebaseClock := timebaseClock
    fixedTimer.commonColdReset := commonColdReset
    val timerPort = fabric.io.externalTimerRegisters.get
    fixedTimer.registers <> timerPort
    timerPort.response.valid := fixedTimer.registers.response.valid && !fixed.holdTimerResponse
    fixedTimer.registers.response.ready := timerPort.response.ready && !fixed.holdTimerResponse
    fabric.io.externalTimerIrq.get := fixedTimer.irq
    fabric.io.externalTimeSnapshot.get := fixedTimer.timeSnapshot
    fixed.timerResponseBlocked := fixedTimer.registers.response.valid && fixed.holdTimerResponse
    fixed.timerRequestFire := timerPort.request.fire
    fixed.timerResponseFire := timerPort.response.fire
    fixed.timerRequestAddress := timerPort.request.bits.address
    fixed.timerRequestWrite := timerPort.request.bits.write
    fixed.timerRequestData := timerPort.request.bits.data
    fixed.timerResponseData := timerPort.response.bits.data
    fixed.timerResponseError := timerPort.response.bits.error
    fixed.timerFabricIdle := fixedTimer.fabricMmioIdle.get
    fixed.timerLocalIdle := fixedTimer.timebaseMmioIdle.get
    fixed.timerIrq := fixedTimer.irq
    fixed.timerSnapshot := fixedTimer.timeSnapshot
    fixed.ddrFabricEmpty := ddrCrossing.fabricTransportEmpty
    fixed.ddrLocalEmpty := ddrCrossing.ddrTransportEmpty
    fixed.ddrFabricReady := ddrCrossing.fabricLinkReady
    fixed.ddrLocalReady := ddrCrossing.ddrLinkReady
    fixed.timerFabricReady := fixedTimer.fabricReady.get
    fixed.timerLocalReady := fixedTimer.timebaseReady.get

    val ddrRelease = Module(new CdcResetRelease)
    ddrRelease.clockIn := ddrClock
    ddrRelease.asyncReset := commonColdReset
    // Independent accepted-transaction owners supplement BOTH FIFO empties.
    // Partial W bursts are owned even before AW or WLAST. B alone retires AW
    // and the accepted W burst; an accepted AR stays owned until accepted RLAST.
    def ownersIdle(port: Axi4MemoryPort, clock: Clock, reset: AsyncReset): Bool =
        withClockAndReset(clock, reset) {
            val reads = RegInit(0.U(8.W))
            val writes = RegInit(0.U(8.W))
            val writeTails = RegInit(0.U(8.W))
            val partialWrite = RegInit(false.B)
            val readDone = port.r.fire && port.r.bits.last
            val writeTail = port.w.fire && port.w.bits.last
            when(port.ar.fire =/= readDone) { reads := Mux(port.ar.fire, reads + 1.U, reads - 1.U) }
            when(port.aw.fire =/= port.b.fire) { writes := Mux(port.aw.fire, writes + 1.U, writes - 1.U) }
            when(writeTail =/= port.b.fire) { writeTails := Mux(writeTail, writeTails + 1.U, writeTails - 1.U) }
            when(port.w.fire) { partialWrite := !port.w.bits.last }
            when(port.ar.fire && !readDone) { assert(reads =/= 255.U, "fixed fixture accepted AR owner overflow") }
            when(port.aw.fire && !port.b.fire) { assert(writes =/= 255.U, "fixed fixture accepted AW owner overflow") }
            when(writeTail && !port.b.fire) { assert(writeTails =/= 255.U, "fixed fixture accepted WLAST owner overflow") }
            when(readDone) { assert(reads =/= 0.U || port.ar.fire, "fixed fixture RLAST without accepted AR owner") }
            when(port.b.fire) {
                assert(writes =/= 0.U || port.aw.fire, "fixed fixture B without accepted AW owner")
                assert(writeTails =/= 0.U || writeTail, "fixed fixture B before accepted WLAST")
            }
            reads === 0.U && writes === 0.U && writeTails === 0.U && !partialWrite &&
                !port.ar.fire && !port.aw.fire && !port.w.fire
        }
    fixed.ddrFabricOwnersIdle := ownersIdle(fabric.io.ddrAxi.get, fabricClock, fabricRelease.resetOut)
    fixed.ddrLocalOwnersIdle := ownersIdle(ddrCrossing.ddr, ddrClock, ddrRelease.resetOut)

    val ddrQualifier = Module(new CommonFixedDomainEpochQualifier(boundary))
    val timerQualifier = Module(new CommonFixedDomainEpochQualifier(boundary))
    for (qualifier <- Seq(ddrQualifier, timerQualifier)) {
        qualifier.fabricClock := fabricClock
        qualifier.commonColdReset := commonColdReset
        qualifier.prepare.valid := fabric.io.externalMaintenance.fire
        qualifier.prepare.bits := fabric.io.externalMaintenance.bits.epoch
        qualifier.fabricHeld := fabric.io.runtimeHeld.get
        qualifier.completion.valid := runtime.io.runtimeComplete.valid
        qualifier.completion.bits := runtime.io.runtimeComplete.bits
        qualifier.terminalConsumedAtAon := runtime.io.terminalConsumedAtAon.get
        qualifier.terminalRetired := runtime.io.runtimeComplete.fire
    }
    ddrQualifier.fixedClock := ddrClock
    // Match the optional production platform predicates exactly. The independent
    // fixture owner counters above are observation/oracle ONLY, never proof inputs.
    val fixedDdrFabricIdle = ddrCrossing.fabricTransportEmpty && ddrCrossing.fabricLinkReady &&
        !fabric.io.ddrAxi.get.aw.valid && !fabric.io.ddrAxi.get.w.valid && !fabric.io.ddrAxi.get.ar.valid
    val fixedTimerFabricIdle = fixedTimer.fabricMmioIdle.get && fixedTimer.fabricReady.get
    ddrQualifier.fabricAllObligationsIdle := fabric.io.allObligationsIdle && fixedDdrFabricIdle
    ddrQualifier.localIdle := ddrCrossing.ddrTransportEmpty && !ddrCrossing.ddr.aw.valid &&
        !ddrCrossing.ddr.w.valid && !ddrCrossing.ddr.ar.valid && !ddrCrossing.ddr.b.valid && !ddrCrossing.ddr.r.valid
    // This fixture's explicit AXI endpoint is ready after common reset, matching
    // CommonMachinePlatform's ddrLinkReady && io.ddrReady with io.ddrReady=true.
    ddrQualifier.linkReady := ddrCrossing.ddrLinkReady
    timerQualifier.fixedClock := timebaseClock
    timerQualifier.fabricAllObligationsIdle := fabric.io.allObligationsIdle && fixedTimerFabricIdle
    timerQualifier.localIdle := fixedTimer.timebaseMmioIdle.get
    timerQualifier.linkReady := fixedTimer.timebaseReady.get
    fixed.ddrQualified := ddrQualifier.qualified
    fixed.timerQualified := timerQualifier.qualified
    fixed.ddrRetirementPermit := ddrQualifier.retirementPermit
    fixed.timerRetirementPermit := timerQualifier.retirementPermit
    fixed.ddrBusy := ddrQualifier.busy
    fixed.timerBusy := timerQualifier.busy
    fixed.fault := ddrQualifier.fault || timerQualifier.fault
    val ddrMatches = ddrQualifier.qualified.valid && ddrQualifier.qualified.bits === fabric.io.runtimeHeld.get.bits
    val timerMatches = timerQualifier.qualified.valid && timerQualifier.qualified.bits === fabric.io.runtimeHeld.get.bits
    // This gates only r10 observation, NEVER the real fabric drain path or data.
    runtime.io.fabricHeld.valid := fabric.io.runtimeHeld.get.valid && fixedDdrFabricIdle &&
        fixedTimerFabricIdle && ddrMatches && timerMatches
    runtime.io.retirementPermit.get := sequencer.retirementPermit && network.io.retirementPermit &&
        ddrQualifier.retirementPermit && timerQualifier.retirementPermit
    runtime.io.retirementFault.get := sequencer.fault || fixed.fault
}
object CommonI1RuntimeFixedNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonI1RuntimeFixedFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

/** Explicit opt-in full-platform topology emission, not a gate/rate backend. */
object CommonRuntimeFixedPlatformMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonMachinePlatform(CommonCpuProfile.I1Performance300,
        programmable = true, hardwareClocks = false, vivadoMemories = false,
        independentDdrClock = true, independentTimebaseClock = true, independentDebugClock = true,
        runtimeDebugAdmission = true, runtimeNetworkAdmission = true, runtimeFixedQualification = true),
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
