package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.Cat
import soc.core.ooo.RenameAllocationCapacity

class RenameCapacityGsim extends Module {
    val io = IO(new Bundle {
        val freeLow = Input(UInt(64.W))
        val freeHigh = Input(UInt(32.W))
        val fresh = Input(UInt(6.W))
        val enough2 = Output(UInt(2.W))
        val enough4 = Output(UInt(4.W))
        val enough6 = Output(UInt(6.W))
    })
    val two = Module(new RenameAllocationCapacity(2, 48))
    val four = Module(new RenameAllocationCapacity(4, 64))
    val six = Module(new RenameAllocationCapacity(6, 96))
    two.io.free := io.freeLow(47, 0)
    four.io.free := io.freeLow
    six.io.free := Cat(io.freeHigh, io.freeLow)
    two.io.fresh := io.fresh(1, 0)
    four.io.fresh := io.fresh(3, 0)
    six.io.fresh := io.fresh
    io.enough2 := two.io.enough
    io.enough4 := four.io.enough
    io.enough6 := six.io.enough
}

object RenameCapacityGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RenameCapacityGsim, Array("--target-dir", args.head))
}
