package spinor_integration

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.integration.spinor._
import soc.ip.axi.Axi4MemoryPort

/** Full-board optimization target: three independent managed 300 MHz domains. */
object I1BoardProfile {
    val cpuHz = 300000000L
    val vpuHz = 300000000L
    val systemHz = 300000000
    // Optional second emitter argument selects the actual board CPU clock in Hz.
    def selectedCpuHz(arguments: Array[String]): Long =
        if (arguments.length > 1) arguments(1).toLong else cpuHz
}
object I1BoardRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new I1SpinorPsFpga(I1HypervisorProfile.core,
        I1BoardProfile.systemHz, I1BoardProfile.selectedCpuHz(args), I1BoardProfile.vpuHz),
        Array("--target-dir", args.head), Array("--split-verilog", "--lower-memories",
            "--disable-all-randomization", "--disable-layers=Verification",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}

/** The physical BUFGCE gates are driven as explicit managed edges in GSIM.
  * All boot-release, address relocation and system RTL are the production units.
  */
class I1PsBoardGsim(cpuHz: Long = I1BoardProfile.cpuHz) extends RawModule {
    val cpuClock = IO(Input(Clock())); val vpuClock = IO(Input(Clock()))
    val systemClock = IO(Input(Clock())); val boardColdReset = IO(Input(AsyncReset()))
    val boot = Module(new I1PsBootRelease)
    boot.systemClock := systemClock; boot.boardColdReset := boardColdReset
    val unit = Module(new I1SpinorManagedSystem(I1HypervisorProfile.core,
        I1BoardProfile.systemHz, cpuHz, I1BoardProfile.vpuHz))
    val io = IO(new Bundle {
        val memory = new Axi4MemoryPort(49, 6)
        val start = Input(Bool()); val ddrReady = Input(Bool()); val started = Output(Bool())
        val cpuClockEnable = Output(Bool()); val vpuClockEnable = Output(Bool())
        val protocolError = Output(Bool()); val retire = chiselTypeOf(unit.io.retire)
    })
    boot.io.start := io.start; boot.io.ddrReady := io.ddrReady; io.started := boot.io.started
    unit.cpuClock := cpuClock; unit.vpuClock := vpuClock; unit.systemClock := systemClock
    unit.commonColdReset := boot.io.subsystemColdReset; unit.io.memoryReady := boot.io.memoryReady
    unit.io.uartRx := true.B; unit.io.externalIrq := false.B
    unit.io.wakeCpu := false.B; unit.io.wakeVpu := false.B
    io.cpuClockEnable := unit.io.cpuClockEnable; io.vpuClockEnable := unit.io.vpuClockEnable
    io.protocolError := unit.io.protocolError; io.retire := unit.io.retire
    val window = withClockAndReset(systemClock, boot.io.subsystemColdReset) { Module(new I1PsDdrWindow) }
    window.io.offset <> unit.io.memory; io.memory <> window.io.hp
}
object I1BoardGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PsBoardGsim(I1BoardProfile.selectedCpuHz(args)), Array("--target-dir", args.head))
}
