package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo.{MachinePlatform, OooParams}

class VmInstructionPlatformGsim(coherent: Boolean = false, wide: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(11.W))
        val romData = Input(UInt(32.W))
        val ramWrite = Input(Bool())
        val ramIndex = Input(UInt(13.W))
        val ramData = Input(UInt(64.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val trap = Output(Bool())
        val trapCause = Output(UInt(64.W))
        val trapTval = Output(UInt(64.W))
        val iWalk = Output(Bool())
        val iPteRead = Output(Bool())
        val iTlbHit = Output(Bool())
        val dWalk = Output(Bool())
    })
    private val issueWidth = if (wide) 4 else 2
    val p = OooParams(renameWidth = issueWidth, commitWidth = issueWidth,
        completionWidth = issueWidth,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true, compressedInstructions = true)
    val platform = Module(new MachinePlatform(p, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = 65536, translationService = true,
        translationLevels = 4, coreDataTranslation = true, coreInstructionTranslation = true,
        coherentLineCache = coherent))
    platform.io.timerTick := false.B
    platform.io.sources := 0.U
    platform.io.uartRx := true.B
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
    io.trap := platform.io.trap.valid
    io.trapCause := platform.io.trap.bits.cause
    io.trapTval := platform.io.trap.bits.tval
    io.iWalk := platform.io.translationEvents.get.walk(0)
    io.iPteRead := platform.io.translationEvents.get.pteRead(0)
    io.iTlbHit := platform.io.translationEvents.get.hit(0)
    io.dWalk := platform.io.translationEvents.get.walk(1)
}

object VmInstructionPlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new VmInstructionPlatformGsim(
        args.lift(1).contains("coherent"), args.lift(1).contains("wide")),
        Array("--target-dir", output.toString))
}
