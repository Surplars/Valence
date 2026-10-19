package inorder

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1JtagRamLoader
import soc.ip.debug.JtagRamLoader

/** Original endpoint is test-only. Every public handshake and owned payload
  * is compared every cycle while an independent host supplies memory bytes.
  */
class I1JtagTimingFixture(timingCuts: Boolean) extends Module {
    val dut = Module(new I1JtagRamLoader(BigInt("80200000", 16), BigInt("80201000", 16),
        timeoutCycles = 64, timingCuts = timingCuts))
    val io = IO(chiselTypeOf(dut.io))
    io <> dut.io
    val reference = Module(new JtagRamLoader(BigInt("80200000", 16), BigInt("80201000", 16),
        timeoutCycles = 64))
    reference.io.linkUp := io.linkUp
    reference.io.dmi.request.valid := io.dmi.request.valid
    reference.io.dmi.request.bits := io.dmi.request.bits
    reference.io.dmi.response.ready := io.dmi.response.ready
    reference.io.control.request.valid := io.control.request.valid
    reference.io.control.request.bits := io.control.request.bits
    reference.io.control.response.ready := io.control.response.ready
    reference.io.memory.request.ready := io.memory.request.ready
    reference.io.memory.response.valid := io.memory.response.valid
    reference.io.memory.response.bits := io.memory.response.bits
    when(!reset.asBool) {
        assert(dut.io.dmi.request.ready === reference.io.dmi.request.ready &&
            dut.io.dmi.response.valid === reference.io.dmi.response.valid,
            "prepared loader changed DMI ownership/latency")
        when(dut.io.dmi.response.valid) {
            assert(dut.io.dmi.response.bits.asUInt === reference.io.dmi.response.bits.asUInt,
                "prepared loader changed an owned DMI result")
        }
        assert(dut.io.control.request.ready === reference.io.control.request.ready &&
            dut.io.control.response.valid === reference.io.control.response.valid,
            "prepared loader changed CPU command ownership/latency")
        when(dut.io.control.response.valid) {
            assert(dut.io.control.response.bits.asUInt === reference.io.control.response.bits.asUInt,
                "prepared loader changed CPU metadata/command result")
        }
        assert(dut.io.memory.request.valid === reference.io.memory.request.valid &&
            dut.io.memory.response.ready === reference.io.memory.response.ready,
            "prepared loader changed outstanding memory obligation")
        when(dut.io.memory.request.valid) {
            assert(dut.io.memory.request.bits.asUInt === reference.io.memory.request.bits.asUInt,
                "prepared loader changed a presented memory request")
        }
    }
}
object I1JtagTimingMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1JtagTimingFixture(args.contains("--timing-cuts")),
        Array("--target-dir", args.head))
}
