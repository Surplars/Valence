package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.platform._
import soc.ip.debug.DebugDmiPort

/** Stalls suppress BOTH valid and ready at the real protocol edge. Payloads,
  * RAM owners, arbiter, AtomicDataMemory, Home and all replies remain genuine.
  */
class RuntimeDebugObservations extends Bundle {
    val holdMemoryRequest = Input(Bool())
    val holdMemoryResponse = Input(Bool())
    val holdControlResponse = Input(Bool())
    val memoryRequestBlocked = Output(Bool())
    val memoryResponseBlocked = Output(Bool())
    val controlResponseBlocked = Output(Bool())
    val memoryRequestFire = Output(Bool())
    val memoryRequestAddress = Output(UInt(64.W))
    val memoryRequestData = Output(UInt(64.W))
    val memoryRequestWrite = Output(Bool())
    val memoryRequestSize = Output(UInt(3.W))
    val memoryRequestByteEnable = Output(UInt(8.W))
    val memoryResponseFire = Output(Bool())
    val memoryResponseData = Output(UInt(64.W))
    val memoryResponseError = Output(Bool())
    val controlRequestFire = Output(Bool())
    val controlRequestAddress = Output(UInt(64.W))
    val controlRequestData = Output(UInt(64.W))
    val controlRequestWrite = Output(Bool())
    val controlResponseFire = Output(Bool())
    val controlResponseError = Output(Bool())
    val dmiOwnersIdle = Output(Bool())
    val controlOwnersIdle = Output(Bool())
}
class RuntimeDebugTestFabric(boundaryParams: CommonCpuTilePortParams, words: Int,
    externalMemory: Boolean = false, networkAdmission: Boolean = false, fixedTimer: Boolean = false)
    extends CommonMachineFabric(boundary = boundaryParams,
        features = CommonPlatformFeatures(ethernetControl = networkAdmission, networkDma = networkAdmission,
            jtagDownload = true, clockManagement = false), ramBytes = 1024 * 1024,
        externalDdr = externalMemory, romWords = words, programmable = true,
        externalUart = false, ramResponseDelay = 7, runtimeDebugAdmission = true,
        runtimeNetworkAdmission = networkAdmission, externalTimer = fixedTimer) {
    val observe = IO(new RuntimeDebugObservations)
    val loader = jtagLoader.get
    val memoryPeer = debugArbiter.get.io.clients(1)
    memoryPeer.request.valid := loader.io.memory.request.valid && !observe.holdMemoryRequest
    loader.io.memory.request.ready := memoryPeer.request.ready && !observe.holdMemoryRequest
    loader.io.memory.response.valid := memoryPeer.response.valid && !observe.holdMemoryResponse
    memoryPeer.response.ready := loader.io.memory.response.ready && !observe.holdMemoryResponse
    val controlPeer = registers("jtag")
    controlPeer.response.valid := loader.io.control.response.valid && !observe.holdControlResponse
    loader.io.control.response.ready := controlPeer.response.ready && !observe.holdControlResponse
    observe.memoryRequestBlocked := loader.io.memory.request.valid && observe.holdMemoryRequest
    observe.memoryResponseBlocked := memoryPeer.response.valid && observe.holdMemoryResponse
    observe.controlResponseBlocked := loader.io.control.response.valid && observe.holdControlResponse
    observe.memoryRequestFire := loader.io.memory.request.fire
    observe.memoryRequestAddress := loader.io.memory.request.bits.address
    observe.memoryRequestData := loader.io.memory.request.bits.data
    observe.memoryRequestWrite := loader.io.memory.request.bits.write
    observe.memoryRequestSize := loader.io.memory.request.bits.size
    observe.memoryRequestByteEnable := loader.io.memory.request.bits.byteEnable
    observe.memoryResponseFire := loader.io.memory.response.fire
    observe.memoryResponseData := loader.io.memory.response.bits.data
    observe.memoryResponseError := loader.io.memory.response.bits.error
    observe.controlRequestFire := loader.io.control.request.fire
    observe.controlRequestAddress := loader.io.control.request.bits.address
    observe.controlRequestData := loader.io.control.request.bits.data
    observe.controlRequestWrite := loader.io.control.request.bits.write
    observe.controlResponseFire := loader.io.control.response.fire
    observe.controlResponseError := loader.io.control.response.bits.error
    observe.dmiOwnersIdle := io.debugDmiOwnersIdle.get
    observe.controlOwnersIdle := io.debugControlOwnersIdle.get
}
class CommonI1RuntimeDebugFixture(debugRomWords: Int = 256) extends CommonI1RuntimeCdcFixture(debugRomWords) {
    override def makeFabric(): CommonMachineFabric = new RuntimeDebugTestFabric(boundary, testRomWords)
    override def makeRuntime(): CommonRuntimeEpochBoundary = new CommonRuntimeEpochBoundary(boundary,
        drainTimeoutCycles = 4096, cleanupTimeoutCycles = 16384, externalRetirementBarrier = true)
    val debugClock = IO(Input(Clock()))
    val debugLinkUp = IO(Input(Bool()))
    val debug = IO(Flipped(new DebugDmiPort(7)))
    val debugBusy = IO(Output(Bool()))
    val debugFault = IO(Output(Bool()))
    val debugLineProbes = IO(Output(UInt(32.W)))
    val debugLineProbeDataBeats = IO(Output(UInt(32.W)))
    val debugHeld = IO(Output(Valid(UInt(boundary.maintenanceEpochBits.W))))
    val observe = IO(new RuntimeDebugObservations)
    val observations = fabric.asInstanceOf[RuntimeDebugTestFabric].observe
    observations.holdMemoryRequest := observe.holdMemoryRequest
    observations.holdMemoryResponse := observe.holdMemoryResponse
    observations.holdControlResponse := observe.holdControlResponse
    for ((name, field) <- observations.elements if !name.startsWith("hold")) {
        observe.elements(name) := field
    }
    val sequencer = Module(new CommonDebugRuntimeSequencer(boundary))
    sequencer.fabricClock := fabricClock
    sequencer.debugClock := debugClock
    sequencer.commonColdReset := commonColdReset
    sequencer.source <> debug
    sequencer.sourceLinkUp := debugLinkUp
    fabric.io.jtagDmi.get <> sequencer.destination
    fabric.io.jtagLinkUp.get := sequencer.destinationLinkUp
    sequencer.destinationOwnersIdle := fabric.io.debugDmiOwnersIdle.get
    sequencer.upstreamPrepare <> runtime.io.externalMaintenance
    fabric.io.externalMaintenance <> sequencer.downstreamPrepare
    sequencer.downstreamComplete <> fabric.io.runtimeComplete.get
    runtime.io.runtimeComplete <> sequencer.upstreamComplete
    sequencer.terminalConsumedAtAon := runtime.io.terminalConsumedAtAon.get
    runtime.io.retirementPermit.get := sequencer.retirementPermit
    runtime.io.retirementFault.get := sequencer.fault
    debugBusy := sequencer.busy
    debugFault := sequencer.fault
    debugHeld := sequencer.debugHeld
    // The guest dirties a guard word in this very line before debug writes its
    // neighboring word. Observe real CPU-side probes and dirty-data beats.
    withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val probes = RegInit(0.U(32.W))
        val dataBeats = RegInit(0.U(32.W))
        probes := probes + PopCount(tile.io.bus.coherent.map(c =>
            c.b.fire && c.b.bits.address === "h80202000".U))
        dataBeats := dataBeats + PopCount(tile.io.bus.coherent.map(c =>
            c.c.fire && c.c.bits.opcode === 5.U && c.c.bits.address === "h80202000".U))
        debugLineProbes := probes
        debugLineProbeDataBeats := dataBeats
    }
}
object CommonI1RuntimeDebugNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonI1RuntimeDebugFixture,
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
