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
class IntegerAlu(parallelResult: Boolean = false, parallelAddressSums: Boolean = false,
    parallelMinMax: Boolean = false, parallelMinMaxWord: Boolean = false,
    earlyWordResults: Boolean = false) extends Module {
    require(!parallelMinMaxWord || (parallelResult && parallelMinMax))
    require(!earlyWordResults || (parallelMinMaxWord && parallelAddressSums))
    // Stateless, II 1; independent base/B/address W payloads join only once.
    def wordResult(data: UInt): UInt = {
        val xlen = Wire(UInt(64.W))
        xlen := data
        Mux(io.word, Cat(Fill(32, xlen(31)), xlen(31, 0)), xlen)
    }
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
    val bitManip = Module(new IntegerBitManip(parallelResult, parallelAddressSums, parallelMinMax,
        parallelMinMaxWord, earlyWordResults))
    bitManip.io.operation := io.operation
    bitManip.io.word      := io.word
    bitManip.io.left      := io.left
    bitManip.io.right     := io.right
    val baseResults = Seq(
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
    val result = if (parallelResult) {
        // Base and B codes are disjoint; do not put the selected B result through
        // a second base-op priority chain. Unknown controls still produce zero.
        val sumSelected = io.operation === IntegerOp.add || io.operation === IntegerOp.sub
        val base = Seq(sumSelected -> sum) ++ baseResults.drop(2).map { case (code, data) =>
            val xlenResult = Wire(UInt(64.W))
            xlenResult := data
            (io.operation === code) -> xlenResult
        }
        val qualifiedBase = if (earlyWordResults)
            base.map { case (grant, data) => grant -> wordResult(data) } else base
        Mux1H(qualifiedBase) | bitManip.io.result | bitManip.io.addressResult.getOrElse(0.U(64.W))
    } else MuxLookup(io.operation, bitManip.io.result)(baseResults)
    io.legal := (io.operation <= IntegerOp.czeroNez && (!io.word ||
        io.operation === IntegerOp.add || io.operation === IntegerOp.sub ||
        io.operation === IntegerOp.sll || io.operation === IntegerOp.srl || io.operation === IntegerOp.sra)) ||
        bitManip.io.legal
    val normal = if (earlyWordResults) result else wordResult(result)
    if (parallelMinMaxWord) {
        val minMax = Module(new ParallelMinMaxResult)
        minMax.io.operation := io.operation
        minMax.io.word := io.word
        minMax.io.left := io.left
        minMax.io.right := io.right
        // The normal bit datapath structurally omits MIN/MAX, not a late mask
        // or timing exception; disjoint operation classes combine by OR.
        io.result := normal | minMax.io.result
    } else io.result := normal
}
