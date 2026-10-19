package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo.ResettableHomeClientArbiter

/** Four-state startup/held-offer fixture for the actual Home arbitration helper.
  * Legacy mode retains Chisel RRArbiter as the pre-fix cold-start negative control.
  */
class CommonHomeArbiterGsim(legacy: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val a = Vec(2, Flipped(Decoupled(UInt(64.W))))
        val e = Vec(2, Flipped(Decoupled(UInt(1.W))))
        val aOut = Decoupled(UInt(64.W))
        val eOut = Decoupled(UInt(1.W))
        val aChosen = Output(UInt(1.W))
        val eChosen = Output(UInt(1.W))
    })
    if (legacy) {
        val a = Module(new RRArbiter(UInt(64.W), 2))
        val e = Module(new RRArbiter(UInt(1.W), 2))
        a.io.in <> io.a; io.aOut <> a.io.out; io.aChosen := a.io.chosen
        e.io.in <> io.e; io.eOut <> e.io.out; io.eChosen := e.io.chosen
    } else {
        val a = Module(new ResettableHomeClientArbiter(UInt(64.W)))
        val e = Module(new ResettableHomeClientArbiter(UInt(1.W)))
        a.io.in <> io.a; io.aOut <> a.io.out; io.aChosen := a.io.chosen
        e.io.in <> io.e; io.eOut <> e.io.out; io.eChosen := e.io.chosen
    }
}

object CommonHomeArbiterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CommonHomeArbiterGsim(args.lift(1).contains("legacy")),
        Array("--target-dir", args.head))
}
