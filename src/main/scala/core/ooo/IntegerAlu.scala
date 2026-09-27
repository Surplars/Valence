package soc.core.ooo

import chisel3._
import chisel3.util._

object IntegerOp {
    val add      = 0.U(6.W)
    val sub      = 1.U(6.W)
    val xor      = 2.U(6.W)
    val or       = 3.U(6.W)
    val and      = 4.U(6.W)
    val sll      = 5.U(6.W)
    val srl      = 6.U(6.W)
    val sra      = 7.U(6.W)
    val slt      = 8.U(6.W)
    val sltu     = 9.U(6.W)
    val czeroEqz = 10.U(6.W)
    val czeroNez = 11.U(6.W)
    val sh1add   = 16.U(6.W)
    val sh2add   = 17.U(6.W)
    val sh3add   = 18.U(6.W)
    val addUw    = 19.U(6.W)
    val sh1addUw = 20.U(6.W)
    val sh2addUw = 21.U(6.W)
    val sh3addUw = 22.U(6.W)
    val slliUw   = 23.U(6.W)
    val andn     = 24.U(6.W)
    val orn      = 25.U(6.W)
    val xnor     = 26.U(6.W)
    val clz      = 27.U(6.W)
    val ctz      = 28.U(6.W)
    val cpop     = 29.U(6.W)
    val min      = 30.U(6.W)
    val minU     = 31.U(6.W)
    val max      = 32.U(6.W)
    val maxU     = 33.U(6.W)
    val sextB    = 34.U(6.W)
    val sextH    = 35.U(6.W)
    val zextH    = 36.U(6.W)
    val rol      = 37.U(6.W)
    val ror      = 38.U(6.W)
    val orcB     = 39.U(6.W)
    val rev8     = 40.U(6.W)
    val bclr     = 41.U(6.W)
    val bset     = 42.U(6.W)
    val binv     = 43.U(6.W)
    val bext     = 44.U(6.W)
}

/** Combinational RV64 integer datapath; decoding and reserved encodings belong to the frontend. One result per cycle
  * per instance. W operations include base add/sub/shifts and B counts/rotates.
  */
class IntegerAlu extends Module {
    val io = IO(new Bundle {
        val operation = Input(UInt(6.W))
        val word      = Input(Bool())
        val left      = Input(UInt(64.W))
        val right     = Input(UInt(64.W))
        val result    = Output(UInt(64.W))
        val legal     = Output(Bool())
    })
    val shift      = Mux(io.word, Cat(0.U(1.W), io.right(4, 0)), io.right(5, 0))
    val subtract   = io.operation === IntegerOp.sub
    val sum        = io.left + Mux(subtract, ~io.right, io.right) + subtract
    val shiftInput = Mux(io.word, Cat(Fill(32, io.operation === IntegerOp.sra && io.left(31)), io.left(31, 0)), io.left)
    val bitManip   = Module(new IntegerBitManip)
    bitManip.io.operation := io.operation
    bitManip.io.word      := io.word
    bitManip.io.left      := io.left
    bitManip.io.right     := io.right
    val result = MuxLookup(io.operation, bitManip.io.result)(
        Seq(
            IntegerOp.add      -> sum,
            IntegerOp.sub      -> sum,
            IntegerOp.xor      -> (io.left ^ io.right),
            IntegerOp.or       -> (io.left | io.right),
            IntegerOp.and      -> (io.left & io.right),
            IntegerOp.sll      -> (io.left << shift)(63, 0),
            IntegerOp.srl      -> (shiftInput >> shift),
            IntegerOp.sra      -> (shiftInput.asSInt >> shift).asUInt,
            IntegerOp.slt      -> (io.left.asSInt < io.right.asSInt).asUInt,
            IntegerOp.sltu     -> (io.left < io.right).asUInt,
            IntegerOp.czeroEqz -> Mux(io.right === 0.U, 0.U, io.left),
            IntegerOp.czeroNez -> Mux(io.right =/= 0.U, 0.U, io.left)
        )
    )
    io.legal := (io.operation <= IntegerOp.czeroNez && (!io.word ||
        io.operation === IntegerOp.add || io.operation === IntegerOp.sub ||
        io.operation === IntegerOp.sll || io.operation === IntegerOp.srl || io.operation === IntegerOp.sra)) || bitManip.io.legal
    io.result := Mux(io.word, Cat(Fill(32, result(31)), result(31, 0)), result)
}
