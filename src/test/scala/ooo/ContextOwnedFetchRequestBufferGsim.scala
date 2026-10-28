package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Same two-credit transport as the legacy fixture, with ON-only provenance.
  * Independent host supplies full64 sequences and toggles backpressure; no DUT
  * sequence arithmetic or response oracle is duplicated in this wrapper.
  */
class ContextOwnedFetchRequestBufferGsim(flowThrough: Boolean = false,
    independentCapture: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new InstructionPort(2, withRequestContext = true, withSpeculationContext = true))
        val downstream = new InstructionPort(2, withRequestContext = true, withSpeculationContext = true)
    })
    val requests = Module(new InstructionRequestBuffer(2, flowThrough, independentCapture,
        withRequestContext = true, contextOwnedInstructionPrefetch = true))
    requests.io.upstream <> io.upstream
    io.downstream <> requests.io.downstream
}

object ContextOwnedFetchRequestBufferGsimMain extends App {
    require(args.length >= 1 && args.length <= 2, "usage: output-dir [registered|flow|independent]")
    val mode = args.lift(1).getOrElse("registered")
    require(Set("registered", "flow", "independent").contains(mode), "unknown request-buffer mode")
    ChiselStage.emitCHIRRTLFile(new ContextOwnedFetchRequestBufferGsim(
        flowThrough = mode != "registered", independentCapture = mode == "independent"),
        Array("--target-dir", args.head))
}
