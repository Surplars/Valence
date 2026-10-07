package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Production selectors and registered boundary, with scalar GSIM ports. */
class RegisteredHeadSelectionGsim extends Module {
    val p = OooParams(robEntries = 16, commitWidth = 2)
    val io = IO(new Bundle {
        val commits = Input(UInt(2.W))
        val eligible = Input(UInt(16.W))
        val issued = Input(Bool())
        val issuedIndex = Input(UInt(4.W))
        val mulEligible = Input(UInt(16.W))
        val divEligible = Input(UInt(16.W))
        val mulAvailable = Input(Bool())
        val divAvailable = Input(Bool())
        val head = Output(UInt(4.W))
        val headMask = Output(UInt(16.W))
        val first = Output(UInt(16.W))
        val second = Output(UInt(16.W))
        val memoryValid = Output(Bool())
        val memoryIndex = Output(UInt(4.W))
        val mulOwner = Output(UInt(16.W))
        val divOwner = Output(UInt(16.W))
        val mulGrant = Output(Bool())
        val divGrant = Output(Bool())
    })
    val head = RegInit(0.U(4.W))
    head := head + io.commits
    val boundary = Module(new RegisteredRobHeadMask(p))
    boundary.io.head := head
    boundary.io.commits := io.commits
    io.head := head
    io.headMask := boundary.io.afterHead
    val issue = Module(new CircularIssueSelector(p, parallelRanks = true, predecodedHead = true))
    issue.io.head := head
    issue.io.headMask.get := boundary.io.afterHead
    issue.io.eligible := io.eligible
    io.first := issue.io.first
    io.second := issue.io.second
    val memory = Module(new MemoryPreparationSelector(p, parallelRanks = true, predecodedHead = true))
    memory.io.head := head
    memory.io.headMask.get := boundary.io.afterHead
    memory.io.eligible := io.eligible
    memory.io.issued := io.issued
    memory.io.issuedIndex := io.issuedIndex
    io.memoryValid := memory.io.selectedValid
    io.memoryIndex := memory.io.selectedIndex
    val md = Module(new SplitMulDivSelector(p, predecodedHead = true))
    md.io.head := head
    md.io.headMask.get := boundary.io.afterHead
    md.io.eligible := VecInit(Seq(io.mulEligible, io.divEligible))
    md.io.available := VecInit(Seq(io.mulAvailable, io.divAvailable))
    io.mulOwner := md.io.owner(0)
    io.divOwner := md.io.owner(1)
    io.mulGrant := md.io.grant(0)
    io.divGrant := md.io.grant(1)
}

object RegisteredHeadSelectionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RegisteredHeadSelectionGsim, Array("--target-dir", args.head))
}
