package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class IssueSelectionGsim(entries: Int, parallelRanks: Boolean = false) extends Module {
    val p = OooParams(robEntries = entries)
    val io = IO(new Bundle {
        val eligible = Input(UInt(32.W))
        val head = Input(UInt(5.W))
        val first = Output(UInt(32.W))
        val second = Output(UInt(32.W))
        val firstValid = Output(Bool())
        val secondValid = Output(Bool())
        val firstIndex = Output(UInt(5.W))
        val secondIndex = Output(UInt(5.W))
        val firstPayload = Output(UInt(64.W))
        val secondPayload = Output(UInt(64.W))
    })
    val selector = Module(new CircularIssueSelector(p, parallelRanks))
    selector.io.eligible := io.eligible(entries - 1, 0)
    selector.io.head := io.head(p.robBits - 1, 0)
    io.first := selector.io.first
    io.second := selector.io.second
    io.firstValid := selector.io.firstValid
    io.secondValid := selector.io.secondValid
    io.firstIndex := selector.io.firstIndex
    io.secondIndex := selector.io.secondIndex
    def payload(i: Int): UInt = (BigInt("d63af091c472b805", 16) ^ (BigInt(i + 1) * BigInt("100010001", 16))).U(64.W)
    val payloads = (0 until entries).map(payload)
    io.firstPayload := CircularIssueSelector.selectPayload(selector.io.first, payloads)
    io.secondPayload := CircularIssueSelector.selectPayload(selector.io.second, payloads)
}
object IssueSelectionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new IssueSelectionGsim(args(1).toInt,
        args.drop(2).contains("parallel-ranks")), Array("--target-dir", args.head))
}
