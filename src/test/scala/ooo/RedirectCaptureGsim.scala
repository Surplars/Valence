package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class RedirectCaptureGsim extends Module {
    val io = IO(new Bundle {
        val flags = Input(UInt(2.W))
        val index0 = Input(UInt(4.W))
        val index1 = Input(UInt(4.W))
        val killed = Input(UInt(16.W))
        val blocked = Input(Bool())
        val selectedLow = Output(UInt(2.W))
        val selectedHigh = Output(UInt(2.W))
        val acceptLow = Output(Bool())
        val acceptHigh = Output(Bool())
        val clearLow = Output(UInt(16.W))
        val clearHigh = Output(UInt(16.W))
    })
    val p = OooParams(robEntries = 16, physicalRegs = 48, registeredBranchRedirect = true)
    val planners = Seq(false, true).map { descending =>
        val c = Module(new EarlyRedirectCapture(p, descending))
        c.io.flags := io.flags
        c.io.indices(0) := io.index0; c.io.indices(1) := io.index1
        c.io.killed := io.killed; c.io.blocked := io.blocked
        c
    }
    io.selectedLow := planners(0).io.selected; io.selectedHigh := planners(1).io.selected
    io.acceptLow := planners(0).io.accept; io.acceptHigh := planners(1).io.accept
    io.clearLow := planners(0).io.clear; io.clearHigh := planners(1).io.clear
}

object RedirectCaptureGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RedirectCaptureGsim, Array("--target-dir", args.head))
}
