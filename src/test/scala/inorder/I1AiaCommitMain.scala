package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._
import soc.ip.interrupt.{Imsic, ImsicCsrRequest, ImsicParams}

/** Real CPU/IMSIC commit path. Gates delay transport, never emulate CSR state or retirement. */
class I1AiaCommitHarness(profile: String = "compact5") extends Module {
    val cuts = profile == "fpga8"
    val p = FiveStageConfig(withM = false, withUser = true, withSupervisor = true, withAia = true,
        pipelineProfile = profile, fpgaTimingCuts = cuts, earlyMemoryIssue = true,
        overlapDataRetirement = cuts, pmpEntries = if (cuts) 4 else 0, externalFenceICompletion = true)
    val io = IO(new Bundle {
        val instructionRequest = Decoupled(UInt(64.W))
        val instructionResponse = Flipped(Decoupled(new FiveStageFetchResponse))
        val dataRequest = Decoupled(new FiveStageDataRequest(p))
        val dataResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val retire = Valid(new FiveStageRetire(p))
        val instructions = Output(UInt(64.W))
        val privilege = Output(UInt(2.W))
        val fenceReady = Input(Bool())
        val fenceValid = Output(Bool())
        val fenceDrained = Output(Bool())
        val invalidateInstruction = Output(Bool())
        val recovery = Output(Bool())
        val offReadAddress = Input(UInt(12.W))
        val offReadLegal = Output(Bool())
        val requestGate = Input(Bool())
        val responseGate = Input(Bool())
        val requestValid = Output(Bool())
        val requestReady = Output(Bool())
        val request = Output(new ImsicCsrRequest)
        val responseValid = Output(Bool())
        val responseReady = Output(Bool())
        val responseData = Output(UInt(64.W))
        val responseError = Output(Bool())
        val msiValid = Input(Bool())
        val msiFile = Input(Bool())
        val msiIdentity = Input(UInt(32.W))
        val msiWithCsr = Input(Bool())
        val msiReady = Output(Bool())
        val msiResponseValid = Output(Bool())
        val msiResponseError = Output(Bool())
        val interrupts = Output(UInt(2.W))
    })
    val core = Module(new FiveStageCore(p))
    val imsic = Module(new Imsic(ImsicParams(identities = 127)))
    io.instructionRequest <> core.io.instructionRequest
    core.io.instructionResponse <> io.instructionResponse
    io.dataRequest <> core.io.dataRequest
    core.io.dataResponse <> io.dataResponse
    io.retire := core.io.retire
    io.instructions := core.io.instructions
    io.privilege := core.io.translation.privilege
    core.io.fenceIFlushReady.get := io.fenceReady
    io.fenceValid := core.io.fenceIFlush.get
    io.fenceDrained := core.io.fenceIFetchDrained.get
    io.invalidateInstruction := core.io.invalidateInstructionCache
    io.recovery := core.io.clearReservation
    // Only legality is observed. Constant inputs allow unrelated state to be pruned.
    val off = Module(new FiveStageMachineState(p.copy(withAia = false, pmpEntries = 0,
        overlapDataRetirement = false)))
    off.io.readAddress := io.offReadAddress
    io.offReadLegal := off.io.readLegal
    off.io.write.valid := false.B
    off.io.write.bits.address := 0.U
    off.io.write.bits.data := 0.U
    off.io.retire := false.B
    off.io.trap.valid := false.B
    off.io.trap.bits.pc := 0.U
    off.io.trap.bits.cause := 0.U
    off.io.trap.bits.tval := 0.U
    off.io.mret := false.B
    off.io.sret := false.B
    off.io.sfence := false.B
    off.io.time := 0.U
    off.io.externalIrq := false.B
    off.io.supervisorExternalIrq := false.B
    off.io.timerIrq := false.B
    off.io.softwareIrq := false.B
    off.io.fpRetire := false.B
    off.io.fpFlags := 0.U
    core.io.time := 0.U
    core.io.externalIrq := imsic.io.interrupts(0)
    core.io.supervisorExternalIrq.get := imsic.io.interrupts(1)
    core.io.timerIrq := false.B
    core.io.softwareIrq := false.B
    val aia = core.io.aia.get
    imsic.io.csrRequest.valid := aia.request.valid && io.requestGate
    imsic.io.csrRequest.bits := aia.request.bits
    aia.request.ready := imsic.io.csrRequest.ready && io.requestGate
    aia.response.valid := imsic.io.csrResponse.valid && io.responseGate
    aia.response.bits := imsic.io.csrResponse.bits
    imsic.io.csrResponse.ready := aia.response.ready && io.responseGate
    io.requestValid := aia.request.valid
    io.requestReady := aia.request.ready
    io.request := aia.request.bits
    io.responseValid := imsic.io.csrResponse.valid
    io.responseReady := imsic.io.csrResponse.ready
    io.responseData := imsic.io.csrResponse.bits.data
    io.responseError := imsic.io.csrResponse.bits.error
    // Collision stimulus is qualified by the real CSR fire, with no prediction from the host.
    val msiWindow = !io.msiWithCsr || imsic.io.csrRequest.fire
    imsic.io.mmio.request.valid := io.msiValid && msiWindow
    imsic.io.mmio.request.bits.address := Mux(io.msiFile, "h28000000".U, "h24000000".U)
    imsic.io.mmio.request.bits.write := true.B
    imsic.io.mmio.request.bits.data := io.msiIdentity
    imsic.io.mmio.request.bits.size := 2.U
    imsic.io.mmio.request.bits.byteEnable := 15.U
    io.msiReady := imsic.io.mmio.request.ready && msiWindow
    imsic.io.mmio.response.ready := true.B
    io.msiResponseValid := imsic.io.mmio.response.valid
    io.msiResponseError := imsic.io.mmio.response.bits.error
    io.interrupts := imsic.io.interrupts
}

object I1AiaCommitMain extends App {
    require(args.length == 2, "output directory and compact5/balanced7/fpga8 profile required")
    require(Set("compact5", "balanced7", "fpga8").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new I1AiaCommitHarness(args(1)), Array("--target-dir", args(0)))
}
