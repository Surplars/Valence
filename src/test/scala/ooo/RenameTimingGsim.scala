package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class RenameTimingGsim(parallelRanks: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val freeLow = Input(UInt(64.W))
        val freeHigh = Input(UInt(32.W))
        val fresh = Input(UInt(6.W))
        val candidates2 = Output(UInt(48.W))
        val candidates4 = Output(UInt(48.W))
        val candidates6 = Output(UInt(48.W))
        val available2 = Output(UInt(6.W))
        val available4 = Output(UInt(6.W))
        val available6 = Output(UInt(6.W))
        val current = Input(UInt(48.W))
        val wakeValid = Input(UInt(3.W))
        val wakeIds = Input(UInt(24.W))
        val reserveValid = Input(UInt(2.W))
        val reserveIds = Input(UInt(16.W))
        val next = Output(UInt(48.W))
    })
    for ((width, registers, result, valid) <- Seq((2, 48, io.candidates2, io.available2),
        (4, 64, io.candidates4, io.available4), (6, 96, io.candidates6, io.available6))) {
        val selector = Module(new RenameDestinationCandidates(width, registers, parallelRanks))
        selector.io.free := Cat(io.freeHigh, io.freeLow)(registers - 1, 0)
        selector.io.fresh := io.fresh(width - 1, 0)
        result := Cat(selector.io.destination.reverse.map(_.pad(8)))
        valid := selector.io.available
    }
    val update = Module(new PhysicalReadyUpdate(48, 3, 2))
    update.io.current := io.current
    for (i <- 0 until 3) {
        update.io.wake(i).valid := io.wakeValid(i)
        update.io.wake(i).bits := io.wakeIds(8 * i + 5, 8 * i)
    }
    for (i <- 0 until 2) {
        update.io.reserve(i).valid := io.reserveValid(i)
        update.io.reserve(i).bits := io.reserveIds(8 * i + 5, 8 * i)
    }
    io.next := update.io.next
}

object RenameTimingGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RenameTimingGsim(args.drop(1).contains("parallel-ranks")), Array("--target-dir", args.head))
}

object RenamePacketCoreGsimMain extends App {
    // The shared bare-core harness requires four/eight LSU slots and 64 predictor
    // entries. This wrapper tests mixed-length packet behavior, not board IPC.
    val p = BoardSocConfig.timingParams("staged-rename").copy(memoryEntries = 4, branchPredictorEntries = 64)
    ChiselStage.emitCHIRRTLFile(new IntegerCoreGsim(p), Array("--target-dir", args.head))
}
