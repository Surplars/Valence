package soc.core.ooo
import chisel3._
import chisel3.util._
import hardfloat._

/** Candidate only: one pinned 64-bit converter supplies W/WU/L/LU.
  * No state or pipeline boundary changes. A narrow result must be range-checked
  * AFTER integer rounding; NV suppresses NX. Never truncate an overflowing result.
  */
class FloatingPointToIntegerShared(e: Int, s: Int) extends Module {
    val io = IO(new Bundle {
        val in = Input(UInt((e+s+1).W))
        val signedOut = Input(Bool())
        val roundingMode = Input(UInt(3.W))
        val out32 = Output(UInt(32.W))
        val flags32 = Output(UInt(3.W))
        val out64 = Output(UInt(64.W))
        val flags64 = Output(UInt(3.W))
    })
    override def desiredName = s"FloatingPointToIntegerShared_e${e}_s${s}"
    val wide = Module(new RecFNToIN(e,s,64))
    wide.io.in := io.in
    wide.io.signedOut := io.signedOut
    wide.io.roundingMode := io.roundingMode
    val raw = rawFloatFromRecFN(e,s,io.in)
    val inRange32 = Mux(io.signedOut,
        wide.io.out(63,31) === Fill(33,wide.io.out(31)),
        !wide.io.out(63,32).orR)
    val invalid = wide.io.intExceptionFlags(2)
    val overflow32 = !invalid && (wide.io.intExceptionFlags(1) || !inRange32)
    val invalid32 = invalid || overflow32
    // Match pinned RecFNToIN exceptional outputs, including NaN's positive clip.
    val exceptionSign = !raw.isNaN && raw.sign
    val clipped32 = Mux(io.signedOut === exceptionSign, "h80000000".U(32.W), 0.U(32.W)) |
        Mux(!exceptionSign,"h7fffffff".U(32.W),0.U(32.W))
    io.out32 := Mux(invalid32,clipped32,wide.io.out(31,0))
    io.flags32 := Cat(invalid,overflow32,!invalid32 && wide.io.intExceptionFlags(0))
    io.out64 := wide.io.out
    io.flags64 := wide.io.intExceptionFlags
}
