package inorder

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Fixed M/Bare context: exercise physical admission independently of CPU decode. */
class I1HypervisorPhysicalFixture extends Module {
    val p = FiveStageConfig(withUser = true, withSupervisor = true, withSv39 = true, withH = true,
        withC = true, physicalAddressBits = 36, pipelineProfile = "fpga8", fpgaTimingCuts = true)
    val io = IO(new Bundle {
        val address = Input(UInt(64.W)); val size = Input(UInt(2.W))
        val vector = Input(Bool()); val write = Input(Bool()); val requestValid = Input(Bool())
        val requestReady = Output(Bool()); val physicalReady = Input(Bool())
        val physicalValid = Output(Bool()); val physicalAddress = Output(UInt(64.W))
        val physicalWrite = Output(Bool()); val returnValid = Input(Bool())
        val returnData = Input(UInt(64.W)); val returnError = Input(Bool()); val returnReady = Output(Bool())
        val replyReady = Input(Bool()); val replyValid = Output(Bool()); val replyData = Output(UInt(64.W))
        val replyError = Output(Bool()); val replyPageFault = Output(Bool()); val replyGuestFault = Output(Bool())
        val walkSeen = Output(Bool()); val owner = Output(Bool())
    })
    val unit = Module(new I1HypervisorTranslation(p, instruction = false))
    unit.io.context := 0.U.asTypeOf(unit.io.context)
    unit.io.context.privilege := 3.U; unit.io.context.dataPrivilege := 3.U
    unit.io.context.pmpAllOff := true.B
    unit.io.entries := DontCare; unit.io.invalidate := false.B
    unit.io.request.valid := io.requestValid
    unit.io.request.bits := 0.U.asTypeOf(unit.io.request.bits)
    unit.io.request.bits.address := io.address; unit.io.request.bits.size := io.size
    unit.io.request.bits.write := io.write; unit.io.request.bits.mask := 255.U
    unit.io.request.bits.guest.get.vector := io.vector
    io.requestReady := unit.io.request.ready
    unit.io.physical.request.ready := io.physicalReady
    io.physicalValid := unit.io.physical.request.valid
    io.physicalAddress := unit.io.physical.request.bits.address
    io.physicalWrite := unit.io.physical.request.bits.write
    unit.io.physical.response.valid := io.returnValid
    unit.io.physical.response.bits := 0.U.asTypeOf(unit.io.physical.response.bits)
    unit.io.physical.response.bits.data := io.returnData
    unit.io.physical.response.bits.error := io.returnError
    io.returnReady := unit.io.physical.response.ready
    unit.io.response.ready := io.replyReady
    io.replyValid := unit.io.response.valid; io.replyData := unit.io.response.bits.data
    io.replyError := unit.io.response.bits.error; io.replyPageFault := unit.io.response.bits.pageFault
    io.replyGuestFault := unit.io.response.bits.guest.get.pageFault
    unit.io.walk.request.ready := false.B
    unit.io.walk.response.valid := false.B
    unit.io.walk.response.bits := 0.U.asTypeOf(unit.io.walk.response.bits)
    io.walkSeen := unit.io.walk.request.valid; io.owner := unit.io.registeredOwner
}

object I1HypervisorPhysicalMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1HypervisorPhysicalFixture, Array("--target-dir", args.head))
}
