package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import scala.collection.immutable.ListMap

class RawFetchPorts(width: Int) extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until width).map(lane =>
        s"lane$lane" -> Valid(new RawFetchInstruction)): _*)
    def at(lane: Int): ValidIO[RawFetchInstruction] =
        elements(s"lane$lane").asInstanceOf[ValidIO[RawFetchInstruction]]
}

class RawSuccessorPorts(width: Int) extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until width).map(lane =>
        s"lane$lane" -> Valid(new RawFetchSuccessor)): _*)
    def at(lane: Int): ValidIO[RawFetchSuccessor] =
        elements(s"lane$lane").asInstanceOf[ValidIO[RawFetchSuccessor]]
}

class RegisteredFetchPacketGsim(width: Int, compressed: Boolean, parallel: Boolean = false,
    hints: Int = 8, splitCursor: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val supply = Input(new RawFetchPorts(width))
        val pause = Input(Bool())
        val consumed = Input(UInt(log2Ceil(width + 1).W))
        val flush = Input(Valid(UInt(64.W)))
        val expectedNext = Input(Valid(UInt(64.W)))
        val train = Input(new RawSuccessorPorts(width))
        val invalidate = Input(Bool())
        val captured = Output(UInt(width.W))
        val instructions = Output(new RawFetchPorts(width))
        val pc = Output(UInt(64.W))
        val nextPc = Output(UInt(64.W))
        val occupancy = Output(UInt(log2Ceil(2 * width + 1).W))
    })
    val reservoir = Module(new RegisteredFetchPacket(width, compressed, BigInt("80000000", 16),
        parallel, hints, splitCursor))
    reservoir.io.supply := VecInit((0 until width).map(io.supply.at))
    reservoir.io.pause := io.pause
    reservoir.io.consume := VecInit((0 until width).map(_.U < io.consumed))
    reservoir.io.flush := io.flush
    reservoir.io.expectedNext := io.expectedNext
    // Exercise both comparator arms with the legacy independent full-PC oracle.
    // The deliberately wrong unused alternative must never affect cancellation.
    reservoir.io.validation.foreach { validations =>
        for (lane <- 0 until width) {
            val taken = io.expectedNext.bits(3)
            validations(lane).predicts := taken
            validations(lane).sequentialPc := Mux(taken, ~io.expectedNext.bits, io.expectedNext.bits)
            validations(lane).predictedPc := Mux(taken, io.expectedNext.bits, ~io.expectedNext.bits)
        }
    }
    reservoir.io.train := VecInit((0 until width).map(io.train.at))
    reservoir.io.invalidate := io.invalidate
    io.captured := reservoir.io.captured.asUInt
    io.pc := reservoir.io.fetchPc
    io.nextPc := reservoir.io.nextFetchPc
    io.occupancy := reservoir.io.occupancy
    for (lane <- 0 until width) io.instructions.at(lane) := reservoir.io.instructions(lane)
}

object RegisteredFetchPacketGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RegisteredFetchPacketGsim(args.lift(1).map(_.toInt).getOrElse(2),
        !args.contains("plain"), args.contains("parallel-validation"),
        if (args.contains("hints32")) 32 else 8, args.contains("split-cursor")), Array("--target-dir", args.head))
}
