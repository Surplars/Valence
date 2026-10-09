package soc.core.ooo

import chisel3._

/** Prediction only: every candidate requires the current checked permission.
  * One accepted ordinary store per cycle; 60 bits of history, no queue/owner.
  * Same-line retry is legal only after entering that line sequentially.
  */
class StorePrefetchHistory extends Module {
    val io = IO(new Bundle {
        val acceptedStore = Input(Bool())
        val address = Input(UInt(64.W))
        val currentlyAllowed = Input(Bool())
        val candidateAvailable = Input(Bool())
        val clear = Input(Bool())
        val candidate = Output(Bool())
    })
    private val valid = RegInit(false.B)
    private val lastLine = Reg(UInt(58.W))
    private val sequentialLine = RegInit(false.B)
    private val line = io.address(63, 6)
    private val same = valid && line === lastLine
    private val sequential = valid && line =/= 0.U && line === lastLine + 1.U
    io.candidate := io.acceptedStore && !io.clear && io.currentlyAllowed && io.candidateAvailable &&
        (sequential || (same && sequentialLine))
    when(io.clear) {
        valid := false.B
        sequentialLine := false.B
    }.elsewhen(io.acceptedStore) {
        valid := true.B
        lastLine := line
        when(!same) { sequentialLine := sequential }
    }
}
