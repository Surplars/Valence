package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class RetireTimingGsim(balancedCompare: Boolean = true) extends Module {
    val io = IO(new Bundle {
        val left = Input(UInt(64.W))
        val right = Input(UInt(64.W))
        val pc = Input(UInt(64.W))
        val immediate = Input(UInt(64.W))
        val kind = Input(UInt(4.W))
        val short = Input(Bool())
        val equal = Output(Bool())
        val unsignedLess = Output(Bool())
        val signedLess = Output(Bool())
        val target = Output(UInt(64.W))
        val nextPc = Output(UInt(64.W))
        val data = Output(UInt(64.W))
        val legal = Output(Bool())
        val misaligned16 = Output(Bool())
        val misaligned32 = Output(Bool())
    })
    val c = Module(new BalancedBranchCompare)
    c.io.left := io.left
    c.io.right := io.right
    io.equal := c.io.equal
    io.unsignedLess := c.io.unsignedLess
    io.signedLess := c.io.signedLess
    val branches = Seq(true, false).map { align16 =>
        val b = Module(new BranchUnit(align16, balancedCompare = balancedCompare))
        b.io.left := io.left; b.io.right := io.right; b.io.pc := io.pc
        b.io.immediate := io.immediate; b.io.kind := io.kind; b.io.shortInstruction := io.short
        b
    }
    io.target := branches.head.io.target
    io.nextPc := branches.head.io.nextPc
    io.data := branches.head.io.data
    io.legal := branches.head.io.legal
    io.misaligned16 := branches.head.io.misaligned
    io.misaligned32 := branches(1).io.misaligned
}

object RetireTimingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RetireTimingGsim(!args.drop(1).contains("carry-compare")),
        Array("--target-dir", args.head))
}

object RetirePacketCoreGsimMain extends App {
    val profile = if (args.drop(1).contains("staged-word-destination")) "staged-word-destination"
        else if (args.drop(1).contains("staged-rank-legality")) "staged-rank-legality"
        else if (args.drop(1).contains("staged-decode-align")) "staged-decode-align"
        else if (args.drop(1).contains("staged-sensitive-paths")) "staged-sensitive-paths"
        else if (args.drop(1).contains("staged-frontend-select")) "staged-frontend-select"
        else if (args.drop(1).contains("staged-execute-select")) "staged-execute-select"
        else if (args.drop(1).contains("staged-recovery-control")) "staged-recovery-control"
        else if (args.drop(1).contains("staged-fetch-control")) "staged-fetch-control"
        else if (args.drop(1).contains("staged-fetch-address")) "staged-fetch-address"
        else if (args.drop(1).contains("staged-return")) "staged-return"
        else if (args.drop(1).contains("staged-payload")) "staged-payload"
        else if (args.drop(1).contains("staged-preparation")) "staged-preparation"
        else if (args.drop(1).contains("staged-redirect")) "staged-redirect" else "staged-retire"
    val p = BoardSocConfig.timingParams(profile).copy(memoryEntries = 4, branchPredictorEntries = 64)
    ChiselStage.emitCHIRRTLFile(new IntegerCoreGsim(p), Array("--target-dir", args.head))
}
