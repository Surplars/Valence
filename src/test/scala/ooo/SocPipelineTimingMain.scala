package ooo

import _root_.circt.stage.ChiselStage
import chisel3.RawModule
import java.nio.file.{Files, Path}
import soc.core.ooo._

/** Selective STA of changed production boundaries, using the exact native board parameters.
  * No timing-only registers, tie-offs, or altered I/O contracts. Leaf OOC checks
  * are a triage step; only the connected, constrained whole board can qualify a bit.
  */
object SocPipelineTimingMain extends App {
    require(args.length == 1, "usage: SocPipelineTimingMain fresh-output-directory")
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "Preserve prior evidence: use a fresh output directory")
    val p = BoardSocConfig.boardParams("staged-fetch-feedback", 2, externalDdr = true, isa = "rv64gc")
    val options = Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info",
        "-default-layer-specialization=disable")
    def emit(name: String)(unit: => RawModule): Unit = {
        ChiselStage.emitSystemVerilogFile(unit,
            Array("--target-dir", output.resolve(name).toString), options)
    }
    emit("FloatingPointMemoryPipeline") { new FloatingPointMemoryPipeline(p) }
    emit("DataTranslationAdapter") {
        // Native BoardSocTop enables stagedMemoryFabric in MappedMachineCore.
        new DataTranslationAdapter(p, registerCheckedRequests = true)
    }
    emit("RegisteredFetchPacket") {
        new RegisteredFetchPacket(p.renameWidth, p.compressedInstructions, BoardSocConfig.romBase,
            p.parallelFetchValidation, p.fetchHintEntries, p.splitFetchCursor)
    }
}

/** Same native BoardSocTop configuration as the acceptance receipt, split for Vivado.
  * This exporter deliberately fixes the two-issue baseline; wider experiments
  * must use a separate entry and cannot silently replace the board candidate.
  */
object SocPipelineBoardMain extends App {
    require(args.length == 1, "usage: SocPipelineBoardMain fresh-output-directory")
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "Preserve previous board RTL evidence")
    ChiselStage.emitSystemVerilogFile(new BoardSocTop(
        socClockHz = 100000000, externalDdr = true, timingProfile = "staged-fetch-feedback",
        uartBaud = 460800, isaProfile = "rv64gc", issueWidth = 2,
        peripheralClockHz = 50000000, clockManagementHz = 50000000, ddrUiClockHz = 250000000,
        ethernetControl = true, ethernetDma = true, managedPeripherals = true),
        Array("--target-dir", output.toString),
        Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info",
            "-default-layer-specialization=disable"))
}
