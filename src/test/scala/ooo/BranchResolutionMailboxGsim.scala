package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class BranchResolutionMailboxGsim extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64)
    val io = IO(new Bundle {
        val head = Input(UInt(4.W))
        val present = Input(UInt(2.W))
        val resolved = Input(UInt(2.W))
        val killed = Input(UInt(2.W))
        val flush = Input(Bool())
        val cancelHeld = Input(Bool())
        val outputReady = Input(Bool())
        val index0 = Input(UInt(4.W))
        val index1 = Input(UInt(4.W))
        val tag0 = Input(UInt(64.W))
        val tag1 = Input(UInt(64.W))
        val pc0 = Input(UInt(64.W))
        val pc1 = Input(UInt(64.W))
        val target0 = Input(UInt(64.W))
        val target1 = Input(UInt(64.W))
        val outputValid = Output(Bool())
        val outputIndex = Output(UInt(4.W))
        val outputTag = Output(UInt(64.W))
        val outputPc = Output(UInt(64.W))
        val outputTarget = Output(UInt(64.W))
        val capture = Output(UInt(2.W))
        val winner = Output(UInt(2.W))
        val duplicate = Output(UInt(2.W))
        val occupied = Output(Bool())
        val canCapture = Output(Bool())
    })
    val mailbox = Module(new BranchResolutionMailbox(p))
    mailbox.io.head := io.head
    mailbox.io.sourceResolved := io.resolved
    mailbox.io.killed := io.killed
    mailbox.io.flush := io.flush
    mailbox.io.cancelHeld := io.cancelHeld
    mailbox.io.out.ready := io.outputReady
    for (lane <- 0 until 2) {
        mailbox.io.offer(lane).valid := io.present(lane)
        mailbox.io.offer(lane).bits.token.index := Seq(io.index0, io.index1)(lane)
        mailbox.io.offer(lane).bits.token.tag := Seq(io.tag0, io.tag1)(lane)
        mailbox.io.offer(lane).bits.pc := Seq(io.pc0, io.pc1)(lane)
        mailbox.io.offer(lane).bits.target := Seq(io.target0, io.target1)(lane)
    }
    io.outputValid := mailbox.io.out.valid
    io.outputIndex := mailbox.io.out.bits.token.index
    io.outputTag := mailbox.io.out.bits.token.tag
    io.outputPc := mailbox.io.out.bits.pc
    io.outputTarget := mailbox.io.out.bits.target
    io.capture := mailbox.io.capture
    io.winner := mailbox.io.winner
    io.duplicate := mailbox.io.duplicate
    io.occupied := mailbox.io.occupied
    io.canCapture := mailbox.io.canCapture
}

object BranchResolutionMailboxGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new BranchResolutionMailboxGsim, Array("--target-dir", args.head))
}
