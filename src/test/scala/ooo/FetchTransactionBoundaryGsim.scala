package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** The actual production boundary with an independent host-controlled engine. */
class FetchTransactionBoundaryGsim(tokenBits: Int = 64) extends Module {
    val io = IO(new Bundle {
        val requestValid = Input(Bool())
        val requestReady = Output(Bool())
        val address = Input(UInt(64.W))
        val mask = Input(UInt(2.W))
        val satp = Input(UInt(64.W))
        val sum = Input(Bool())
        val mxr = Input(Bool())
        val privilege = Input(UInt(2.W))
        val responseReady = Input(Bool())
        val responseValid = Output(Bool())
        val responseData = Output(UInt(64.W))
        val responseErrors = Output(UInt(2.W))
        val responsePages = Output(UInt(2.W))
        val commandValid = Output(Bool())
        val commandReady = Input(Bool())
        val commandToken = Output(UInt(64.W))
        val commandAddress = Output(UInt(64.W))
        val commandMask = Output(UInt(2.W))
        val commandSatp = Output(UInt(64.W))
        val commandSum = Output(Bool())
        val commandMxr = Output(Bool())
        val commandPrivilege = Output(UInt(2.W))
        val resultValid = Input(Bool())
        val resultReady = Output(Bool())
        val resultToken = Input(UInt(64.W))
        val resultData = Input(UInt(64.W))
        val resultErrors = Input(UInt(2.W))
        val resultPages = Input(UInt(2.W))
        val idle = Output(Bool())
    })
    val boundary = Module(new InstructionFetchTransactionBoundary(tokenBits = tokenBits))
    boundary.io.upstream.request.valid := io.requestValid
    boundary.io.upstream.request.bits := io.address
    boundary.io.upstream.requestMask := io.mask
    io.requestReady := boundary.io.upstream.request.ready
    boundary.io.upstream.response.ready := io.responseReady
    io.responseValid := boundary.io.upstream.response.valid
    io.responseData := boundary.io.upstream.response.bits
    io.responseErrors := boundary.io.upstream.responseError
    io.responsePages := boundary.io.upstream.responsePageFault
    boundary.io.vmState := 0.U.asTypeOf(new VmCsrState)
    boundary.io.vmState.satp := io.satp
    boundary.io.vmState.sum := io.sum
    boundary.io.vmState.mxr := io.mxr
    boundary.io.privilege := io.privilege
    io.commandValid := boundary.io.command.valid
    boundary.io.command.ready := io.commandReady
    io.commandToken := boundary.io.command.bits.token
    io.commandAddress := boundary.io.command.bits.virtualAddress
    io.commandMask := boundary.io.command.bits.requestMask
    io.commandSatp := boundary.io.command.bits.satp
    io.commandSum := boundary.io.command.bits.sum
    io.commandMxr := boundary.io.command.bits.mxr
    io.commandPrivilege := boundary.io.command.bits.privilege
    boundary.io.result.valid := io.resultValid
    boundary.io.result.bits.token := io.resultToken
    boundary.io.result.bits.data := io.resultData
    boundary.io.result.bits.accessFaults := io.resultErrors
    boundary.io.result.bits.pageFaults := io.resultPages
    io.resultReady := boundary.io.result.ready
    io.idle := boundary.io.idle
}

object FetchTransactionBoundaryGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchTransactionBoundaryGsim(args.lift(1).map(_.toInt).getOrElse(64)), Array("--target-dir", args.head))
}
