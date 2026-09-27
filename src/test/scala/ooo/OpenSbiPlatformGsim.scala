package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo.{MachinePlatform, OooParams}

/** GSIM image-loader boundary for the real OpenSBI firmware. RAM is a 1 MiB model;
  * the boot ROM contains only a reset trampoline.
  */
class OpenSbiPlatformGsim extends Module {
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(11.W))
        val romData = Input(UInt(32.W))
        val ramWrite = Input(Bool())
        val ramIndex = Input(UInt(17.W))
        val ramData = Input(UInt(64.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Bool())
        val commit0Pc = Output(UInt(64.W))
        val commit0Instruction = Output(UInt(32.W))
        val commit1 = Output(Bool())
        val commit1Pc = Output(UInt(64.W))
        val trap = Output(Bool())
        val trapPc = Output(UInt(64.W))
        val trapCause = Output(UInt(64.W))
        val trapTval = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
    })
    private val ramBytes = 1 << 20
    private val p = OooParams(speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = ramBytes, bufferedRamStores = true, compressedInstructions = true)
    private val platform = Module(new MachinePlatform(p, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = ramBytes, translationService = true,
        translationLevels = 3, coreDataTranslation = true, coreInstructionTranslation = true))
    platform.io.timerTick := !io.hold
    platform.io.sources := 0.U
    platform.io.uartRx := io.uartRx
    platform.io.commitEnable := true.B
    platform.io.inspectRegister := io.inspectRegister
    platform.io.translationFlush.get := false.B
    platform.io.program.get.hold := io.hold
    platform.io.program.get.write := io.romWrite
    platform.io.program.get.index := io.romIndex
    platform.io.program.get.data := io.romData
    platform.io.ramProgram.get.write := io.ramWrite
    platform.io.ramProgram.get.index := io.ramIndex
    platform.io.ramProgram.get.data := io.ramData
    io.committedValue := platform.io.committedValue
    io.commit0 := platform.io.commit(0).valid
    io.commit0Pc := platform.io.commit(0).bits.pc
    io.commit0Instruction := platform.io.commit(0).bits.instruction
    io.commit1 := platform.io.commit(1).valid
    io.commit1Pc := platform.io.commit(1).bits.pc
    io.trap := platform.io.trap.valid
    io.trapPc := platform.io.trap.bits.pc
    io.trapCause := platform.io.trap.bits.cause
    io.trapTval := platform.io.trap.bits.tval
    io.fetchPc := platform.io.fetchPc
    io.uartTx := platform.io.uartTx
}

object OpenSbiPlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new OpenSbiPlatformGsim,
        Array("--target-dir", output.toString))
}
