package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo.AlignedMemoryDisjoint

class AlignedMemoryDisjointGsim extends Module {
    val io = IO(new Bundle {
        val loadAddress = Input(UInt(64.W))
        val storeAddress = Input(UInt(64.W))
        val loadSize = Input(UInt(2.W))
        val storeSize = Input(UInt(2.W))
        val disjoint = Output(Bool())
    })
    io.disjoint := AlignedMemoryDisjoint(io.loadAddress, io.loadSize, io.storeAddress, io.storeSize)
}

object AlignedMemoryDisjointGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AlignedMemoryDisjointGsim, Array("--target-dir", args.head))
}
