package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.platform._

/** Test-only protocol backpressure at actual atomic owner boundaries. No state
  * injection, fabricated responses or changes to production constructor paths.
  */
class RuntimeAtomicObservations extends Bundle {
    val holdAtomicRead = Input(Bool())
    val holdAtomicWrite = Input(Bool())
    val holdMemoryResponse = Input(Bool())
    val holdAtomicResult = Input(Bool())
    val atomicRequestFire = Output(Bool())
    val atomicOperation = Output(UInt(5.W))
    val atomicAddress = Output(UInt(64.W))
    val atomicData = Output(UInt(64.W))
    val atomicResponseFire = Output(Bool())
    val atomicResponseData = Output(UInt(64.W))
    val memoryRequestFire = Output(Bool())
    val memoryWrite = Output(Bool())
    val memoryData = Output(UInt(64.W))
    val memoryAddress = Output(UInt(64.W))
    val memoryResponseFire = Output(Bool())
    val memoryResponseData = Output(UInt(64.W))
    val atomicActive = Output(Bool())
    val reservationClear = Output(Bool())
    val atomicReadBlocked = Output(Bool())
    val atomicWriteBlocked = Output(Bool())
    val memoryResponseBlocked = Output(Bool())
    val atomicResultBlocked = Output(Bool())
}
class RuntimeArchitecturalObservations extends RuntimeAtomicObservations {
    val trapPc = Output(UInt(64.W))
    val trapCause = Output(UInt(64.W))
    val architecturalStopped = Output(Bool())
}
class RuntimeAtomicTestFabric(boundaryParams: CommonCpuTilePortParams, words: Int)
    extends CommonMachineFabric(boundary = boundaryParams,
        features = CommonPlatformFeatures(ethernetControl = false, networkDma = false,
            jtagDownload = false, clockManagement = false), ramBytes = 65536,
        externalDdr = false, romWords = words, programmable = true,
        externalUart = false, ramResponseDelay = 7) {
    val observe = IO(new RuntimeAtomicObservations)
    val holdRead = atomicActive && observe.holdAtomicRead && !atomic.io.memory.request.bits.write
    val holdWrite = atomicActive && observe.holdAtomicWrite && atomic.io.memory.request.bits.write
    val holdRequest = holdRead || holdWrite
    physicalRequests.io.upstream.request.valid := atomic.io.memory.request.valid && !drainStarted && !holdRequest
    atomic.io.memory.request.ready := physicalRequests.io.upstream.request.ready && !drainStarted && !holdRequest
    val holdResponse = atomicActive && observe.holdMemoryResponse
    atomic.io.memory.response.valid := physicalRequests.io.upstream.response.valid && !holdResponse
    physicalRequests.io.upstream.response.ready := atomic.io.memory.response.ready && !holdResponse
    val holdResult = atomicActive && observe.holdAtomicResult
    router.io.memory.response.valid := atomic.io.cpu.response.valid && !holdResult
    atomic.io.cpu.response.ready := router.io.memory.response.ready && !holdResult
    observe.atomicRequestFire := atomic.io.cpu.request.fire && atomic.io.cpu.request.bits.atomic
    observe.atomicOperation := atomic.io.cpu.request.bits.atomicOp
    observe.atomicAddress := atomic.io.cpu.request.bits.address
    observe.atomicData := atomic.io.cpu.request.bits.data
    observe.atomicResponseFire := atomicActive && atomic.io.cpu.response.fire
    observe.atomicResponseData := atomic.io.cpu.response.bits.data
    observe.memoryRequestFire := atomicActive && atomic.io.memory.request.fire
    observe.memoryWrite := atomic.io.memory.request.bits.write
    observe.memoryData := atomic.io.memory.request.bits.data
    observe.memoryAddress := atomic.io.memory.request.bits.address
    observe.memoryResponseFire := atomicActive && atomic.io.memory.response.fire
    observe.memoryResponseData := atomic.io.memory.response.bits.data
    observe.atomicActive := atomicActive
    observe.reservationClear := atomic.io.clearReservation
    observe.atomicReadBlocked := atomic.io.memory.request.valid && holdRead
    observe.atomicWriteBlocked := atomic.io.memory.request.valid && holdWrite
    observe.memoryResponseBlocked := physicalRequests.io.upstream.response.valid && holdResponse
    observe.atomicResultBlocked := atomic.io.cpu.response.valid && holdResult
}
class CommonI1RuntimeArchitecturalFixture extends CommonI1RuntimeCdcFixture(256) {
    override def makeFabric(): CommonMachineFabric = new RuntimeAtomicTestFabric(boundary, testRomWords)
    val observe = IO(new RuntimeArchitecturalObservations)
    val atomicObservations = fabric.asInstanceOf[RuntimeAtomicTestFabric].observe
    // Explicit named forwarding keeps the test-only interface reviewable.
    atomicObservations.holdAtomicRead := observe.holdAtomicRead
    atomicObservations.holdAtomicWrite := observe.holdAtomicWrite
    atomicObservations.holdMemoryResponse := observe.holdMemoryResponse
    atomicObservations.holdAtomicResult := observe.holdAtomicResult
    for ((name, field) <- atomicObservations.elements if !name.startsWith("hold")) {
        observe.elements(name) := field
    }
    observe.trapPc := tile.io.trapPc
    observe.trapCause := tile.io.trapCause
    observe.architecturalStopped := tile.io.architecturalStopped.get
}
object CommonI1RuntimeArchitecturalNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonI1RuntimeArchitecturalFixture,
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
