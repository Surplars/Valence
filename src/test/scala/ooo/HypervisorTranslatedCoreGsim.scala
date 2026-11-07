package ooo
import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class HypervisorTranslatedCoreGsim extends Module {
    val core = Module(new HypervisorMachineCore)
    val io = IO(chiselTypeOf(core.io))
    io <> core.io
    def ram(address: UInt): Bool = address >= "h80000000".U && address < "h81000000".U
    core.io.dataPmaDenied := !ram(core.io.dataPhysicalCheck.bits.address)
    core.io.fetchPmaDenied := !ram(core.io.fetchPhysicalCheck.bits.address)
    core.io.dataPmaUncached := false.B
    core.io.timerInterrupt := false.B; core.io.timeValue := 0.U
    core.io.msi.request.valid := false.B
    core.io.msi.request.bits := 0.U.asTypeOf(core.io.msi.request.bits)
    core.io.msi.response.ready := true.B
}
object HypervisorTranslatedCoreGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HypervisorTranslatedCoreGsim, Array("--target-dir", args(0)))
}
