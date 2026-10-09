package ooo

import chisel3._
import soc.core.ooo._
import _root_.circt.stage.ChiselStage

class StorePrefetchHistoryGsim extends Module {
    val io = IO(new Bundle {
        val acceptedStore = Input(Bool())
        val address = Input(UInt(64.W))
        val currentlyAllowed = Input(Bool())
        val candidateAvailable = Input(Bool())
        val clear = Input(Bool())
        val candidate = Output(Bool())
    })
    val history = Module(new StorePrefetchHistory())
    history.io.acceptedStore := io.acceptedStore
    history.io.address := io.address
    history.io.currentlyAllowed := io.currentlyAllowed
    history.io.candidateAvailable := io.candidateAvailable
    history.io.clear := io.clear
    io.candidate := history.io.candidate
}
object StorePrefetchHistoryGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new StorePrefetchHistoryGsim, Array("--target-dir", args.head))
}
