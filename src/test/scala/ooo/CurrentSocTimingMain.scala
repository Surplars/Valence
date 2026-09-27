package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import java.nio.file.{Files, Path}

/** Current four-issue machine datapath with a small on-chip RAM for out-of-context FPGA timing.
  * The Linux simulation's 64 MiB RAM is a functional model, not an FPGA storage implementation.
  */
class CurrentSocTimingTop extends Module {
    private val ramBytes = 16384
    private val romWords = 2048
    private val p = OooParams(renameWidth = 4, commitWidth = 4, completionWidth = 4,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = ramBytes,
        bufferedRamStores = true, compressedInstructions = true)
    val io = IO(new Bundle {
        val timerTick = Input(Bool())
        val sources = Input(UInt(31.W))
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val commitEnable = Input(Bool())
        val commit = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap = Output(Valid(new HeadException(p)))
        val fetchPc = Output(UInt(64.W))
        val fetchWait = Output(Bool())
        val msiError = Output(Bool())
        val translationFlush = Input(Bool())
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(11.W))
        val romData = Input(UInt(32.W))
        val ramWrite = Input(Bool())
        val ramIndex = Input(UInt(11.W))
        val ramData = Input(UInt(64.W))
    })
    val platform = Module(new MachinePlatform(p, romWords = romWords, programmable = true,
        tileLinkMemory = true, tileLinkFetch = true, ramBytes = ramBytes,
        instructionLineCacheLines = 16, translationService = true, translationLevels = 3,
        coreDataTranslation = true, coreInstructionTranslation = true,
        coherentLineCache = true, coherentLineCacheLines = 128))
    platform.io.timerTick := io.timerTick
    platform.io.sources := io.sources
    platform.io.uartRx := io.uartRx
    platform.io.commitEnable := io.commitEnable
    platform.io.inspectRegister := io.inspectRegister
    platform.io.translationFlush.get := io.translationFlush
    platform.io.program.get.hold := io.hold
    platform.io.program.get.write := io.romWrite
    platform.io.program.get.index := io.romIndex
    platform.io.program.get.data := io.romData
    platform.io.ramProgram.get.write := io.ramWrite
    platform.io.ramProgram.get.index := io.ramIndex
    platform.io.ramProgram.get.data := io.ramData
    io.uartTx := platform.io.uartTx
    io.commit := platform.io.commit
    io.trap := platform.io.trap
    io.fetchPc := platform.io.fetchPc
    io.fetchWait := platform.io.fetchWait
    io.msiError := platform.io.msiError
    io.committedValue := platform.io.committedValue
}

object CurrentSocTimingMain extends App {
    require(args.length == 1, "usage: CurrentSocTimingMain output-directory")
    val output = Path.of(args(0)).toAbsolutePath
    Files.createDirectories(output)
    ChiselStage.emitSystemVerilogFile(new CurrentSocTimingTop,
        Array("--target-dir", output.toString),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
