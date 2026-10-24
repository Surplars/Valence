package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class FetchCompletionLedgerGsim extends Module {
    val io = IO(new Bundle {
        val allocate = Input(Bool())
        val allocationReady = Output(Bool())
        val allocationSlot = Output(UInt(1.W))
        val token = Input(UInt(64.W))
        val terminal = Input(Bool())
        val complete = Input(Bool())
        val completeSlot = Input(UInt(1.W))
        val completeToken = Input(UInt(64.W))
        val data = Input(UInt(64.W))
        val errors = Input(UInt(2.W))
        val pages = Input(UInt(2.W))
        val resultReady = Input(Bool())
        val resultValid = Output(Bool())
        val resultToken = Output(UInt(64.W))
        val resultData = Output(UInt(64.W))
        val resultErrors = Output(UInt(2.W))
        val resultPages = Output(UInt(2.W))
        val idle = Output(Bool())
    })
    val ledger = Module(new FetchCompletionLedger)
    ledger.io.allocate.valid := io.allocate
    ledger.io.allocate.bits.token := io.token
    ledger.io.allocate.bits.terminal := io.terminal
    io.allocationReady := ledger.io.allocate.ready
    io.allocationSlot := ledger.io.allocationSlot
    ledger.io.completion.valid := io.complete
    ledger.io.completion.bits.slot := io.completeSlot
    ledger.io.completion.bits.token := io.completeToken
    ledger.io.completion.bits.data := io.data
    ledger.io.completion.bits.accessFaults := io.errors
    ledger.io.completion.bits.pageFaults := io.pages
    ledger.io.result.ready := io.resultReady
    io.resultValid := ledger.io.result.valid
    io.resultToken := ledger.io.result.bits.token
    io.resultData := ledger.io.result.bits.data
    io.resultErrors := ledger.io.result.bits.accessFaults
    io.resultPages := ledger.io.result.bits.pageFaults
    io.idle := ledger.io.idle
}
object FetchCompletionLedgerGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchCompletionLedgerGsim, Array("--target-dir", args.head))
}
