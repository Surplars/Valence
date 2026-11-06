package spinor_integration

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.ip.bus.CdcMailbox

/** Tool semantics only: independent clocks, old-state sampling, RAM and real CDC IP. */
class GsimClockContract extends RawModule {
    val clockA = IO(Input(Clock())); val clockB = IO(Input(Clock()))
    val resetA = IO(Input(AsyncReset())); val resetB = IO(Input(Bool()))
    val coldReset = IO(Input(AsyncReset()))
    val enableA = IO(Input(Bool())); val enableB = IO(Input(Bool()))
    val deltaA = IO(Input(UInt(8.W))); val deltaB = IO(Input(UInt(8.W)))
    val countA = IO(Output(UInt(8.W))); val countB = IO(Output(UInt(8.W)))
    val seenA = IO(Output(UInt(8.W))); val seenB = IO(Output(UInt(8.W)))
    val a = withClockAndReset(clockA, resetA) { RegInit(0x39.U(8.W)) }
    val b = withClockAndReset(clockB, resetB) { RegInit(0xa7.U(8.W)) }
    val aa = withClockAndReset(clockA, resetA) { RegInit(0.U(8.W)) }
    val bb = withClockAndReset(clockB, resetB) { RegInit(0.U(8.W)) }
    withClockAndReset(clockA, resetA) { when(enableA) { a := a + deltaA; aa := b } }
    withClockAndReset(clockB, resetB) { when(enableB) { b := b + deltaB; bb := a } }
    countA := a; countB := b; seenA := aa; seenB := bb
    val addressA = IO(Input(UInt(4.W))); val addressB = IO(Input(UInt(4.W)))
    val writeA = IO(Input(Bool())); val writeB = IO(Input(Bool()))
    val readA = IO(Input(Bool())); val readB = IO(Input(Bool()))
    val dataA = IO(Input(UInt(64.W))); val dataB = IO(Input(UInt(64.W)))
    val asyncA = IO(Output(UInt(64.W))); val asyncB = IO(Output(UInt(64.W)))
    val syncA = IO(Output(UInt(64.W))); val syncB = IO(Output(UInt(64.W)))
    for ((clock, address, write, read, data, asyncOut, syncOut) <- Seq(
        (clockA, addressA, writeA, readA, dataA, asyncA, syncA),
        (clockB, addressB, writeB, readB, dataB, asyncB, syncB))) {
        withClock(clock) {
            val ordinary = Mem(16, UInt(64.W))
            val synchronous = SyncReadMem(16, UInt(64.W))
            when(write) { ordinary.write(address, data); synchronous.write(address, data) }
            asyncOut := ordinary.read(address)
            syncOut := synchronous.read(address, read)
        }
    }
    val mailboxIn = IO(Flipped(Decoupled(UInt(80.W))))
    val mailboxOut = IO(Decoupled(UInt(80.W)))
    val mailbox = Module(new CdcMailbox(80))
    mailbox.sourceClock := clockA; mailbox.destinationClock := clockB; mailbox.commonReset := coldReset
    mailbox.source <> mailboxIn; mailboxOut <> mailbox.destination
}
object GsimClockContractMain extends App {
    ChiselStage.emitCHIRRTLFile(new GsimClockContract, Array("--target-dir", args.head))
}
