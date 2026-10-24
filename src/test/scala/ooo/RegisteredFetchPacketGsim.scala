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
    hints: Int = 8, splitCursor: Boolean = false, bankedHints: Boolean = false,
    circularPayload: Boolean = false, compareLegacy: Boolean = false) extends Module {
    require(!compareLegacy || circularPayload, "paired reservoir comparison requires the circular candidate")
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
        parallel, hints, splitCursor, bankedHints, circularPayload = circularPayload))
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
    if (compareLegacy) {
        // This peer is a same-cycle compatibility check, not the behavioral
        // oracle: the host still owns its independent deque/ISA successor model.
        val legacy = Module(new RegisteredFetchPacket(width, compressed, BigInt("80000000", 16),
            parallel, hints, splitCursor, bankedHints))
        legacy.io.supply := reservoir.io.supply
        legacy.io.pause := reservoir.io.pause
        legacy.io.consume := reservoir.io.consume
        legacy.io.flush := reservoir.io.flush
        legacy.io.expectedNext := reservoir.io.expectedNext
        legacy.io.validation.foreach(_ := reservoir.io.validation.get)
        legacy.io.train := reservoir.io.train
        legacy.io.invalidate := reservoir.io.invalidate
        assert(legacy.io.occupancy === reservoir.io.occupancy && legacy.io.fetchPc === reservoir.io.fetchPc &&
            legacy.io.nextFetchPc === reservoir.io.nextFetchPc && legacy.io.captured.asUInt === reservoir.io.captured.asUInt,
            "circular reservoir changed legacy cycle/credit/cursor behavior")
        for (lane <- 0 until width) {
            assert(legacy.io.instructions(lane).valid === reservoir.io.instructions(lane).valid,
                "circular reservoir changed legacy output presence")
            when(legacy.io.instructions(lane).valid) {
                assert(legacy.io.instructions(lane).bits.asUInt === reservoir.io.instructions(lane).bits.asUInt,
                    "circular reservoir changed a legacy instruction owner")
            }
        }
    }
    io.captured := reservoir.io.captured.asUInt
    io.pc := reservoir.io.fetchPc
    io.nextPc := reservoir.io.nextFetchPc
    io.occupancy := reservoir.io.occupancy
    for (lane <- 0 until width) io.instructions.at(lane) := reservoir.io.instructions(lane)
}

object RegisteredFetchPacketGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RegisteredFetchPacketGsim(args.lift(1).map(_.toInt).getOrElse(2),
        !args.contains("plain"), args.contains("parallel-validation"),
        if (args.contains("hints32")) 32 else 8, args.contains("split-cursor"), args.contains("banked-hints"),
        args.contains("circular-payload"), args.contains("compare-legacy")), Array("--target-dir", args.head))
}
