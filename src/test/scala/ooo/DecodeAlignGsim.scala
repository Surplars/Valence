package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class DecodeAlignGsim(parallelBitLegality: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val pc = Input(UInt(64.W))
        val bitLegal = Input(Bool())
        val bitDecodedLegal = Output(Bool())
        val equal = Output(UInt(4.W))
        val classLegal = Output(UInt(4.W))
    })
    val bitQualifier = Module(new ParallelBitLegality)
    bitQualifier.io.instruction := io.instruction
    io.bitDecodedLegal := bitQualifier.io.legal
    val equal = Wire(Vec(4, Bool()))
    val classLegal = Wire(Vec(4, Bool()))
    for (mode <- 0 until 4) {
        val legacy = Module(new IntegerDecode((mode & 1) != 0, (mode & 2) != 0))
        val current = Module(new IntegerDecode((mode & 1) != 0, (mode & 2) != 0, true, parallelBitLegality))
        for (d <- Seq(legacy, current)) { d.io.instruction := io.instruction; d.io.pc := io.pc }
        equal(mode) := legacy.io.decoded.asUInt === current.io.decoded.asUInt &&
            legacy.io.legal === current.io.legal
        val helper = Module(new ParallelIntegerLegality((mode & 1) != 0, (mode & 2) != 0))
        helper.io.instruction := io.instruction
        helper.io.bitLegal := io.bitLegal
        classLegal(mode) := helper.io.legal
    }
    io.equal := equal.asUInt
    io.classLegal := classLegal.asUInt
}
object DecodeAlignGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DecodeAlignGsim(args.drop(1).contains("parallel-bit-legality")), Array("--target-dir", args.head))
}
class FetchAlignmentGsim(width: Int) extends Module {
    val io = IO(new Bundle {
        val packet0 = Input(UInt(64.W))
        val packet1 = Input(UInt(64.W))
        val packet2 = Input(UInt(64.W))
        val present = Input(UInt(3.W))
        val errors = Input(UInt(6.W))
        val pages = Input(UInt(6.W))
        val offset = Input(UInt(3.W))
        val valid = Output(UInt(4.W))
        val errorsOut = Output(UInt(4.W))
        val pagesOut = Output(UInt(4.W))
        val instruction0 = Output(UInt(32.W))
        val instruction1 = Output(UInt(32.W))
        val instruction2 = Output(UInt(32.W))
        val instruction3 = Output(UInt(32.W))
        val fault0 = Output(UInt(5.W))
        val fault1 = Output(UInt(5.W))
        val fault2 = Output(UInt(5.W))
        val fault3 = Output(UInt(5.W))
    })
    val a = Module(new ParallelFetchAlignment(width))
    a.io.packets := VecInit(Seq(io.packet0, io.packet1, io.packet2))
    a.io.present := io.present
    for (i <- 0 until 3) {
        a.io.errors(i) := io.errors(2 * i + 1, 2 * i)
        a.io.pages(i) := io.pages(2 * i + 1, 2 * i)
    }
    a.io.pcOffset := io.offset
    io.valid := VecInit(a.io.instructions.map(_.valid)).asUInt
    io.errorsOut := a.io.errorsOut.asUInt
    io.pagesOut := a.io.pagesOut.asUInt
    for ((data, i) <- Seq(io.instruction0, io.instruction1, io.instruction2, io.instruction3).zipWithIndex)
        data := (if (i < width) a.io.instructions(i).bits else 0.U)
    for ((fault, i) <- Seq(io.fault0, io.fault1, io.fault2, io.fault3).zipWithIndex)
        fault := (if (i < width) a.io.faultOffsets(i) else 0.U)
}
object FetchAlignmentGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchAlignmentGsim(args(1).toInt), Array("--target-dir", args.head))
}
