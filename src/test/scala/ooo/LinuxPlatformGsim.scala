package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo.{CoherentCacheProfile, MachinePlatform, OooParams}

/** Large GSIM RAM profile for executing Linux behind the unmodified OpenSBI fw_jump. */
class LinuxPlatformGsim(issueWidth: Int = 2, cacheMode: String = "direct", cacheLines: Int = 128) extends Module {
    require(Set(2, 4).contains(issueWidth))
    require(Set("direct", "coherent").contains(cacheMode))
    require(Set(128, 256).contains(cacheLines))
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(11.W))
        val romData = Input(UInt(32.W))
        val ramWrite = Input(Bool())
        val ramIndex = Input(UInt(23.W))
        val ramData = Input(UInt(64.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Bool())
        val commit0Pc = Output(UInt(64.W))
        val commit1 = Output(Bool())
        val commit1Pc = Output(UInt(64.W))
        val commit2 = Output(Bool())
        val commit2Pc = Output(UInt(64.W))
        val commit3 = Output(Bool())
        val commit3Pc = Output(UInt(64.W))
        val trap = Output(Bool())
        val trapPc = Output(UInt(64.W))
        val trapCause = Output(UInt(64.W))
        val trapTval = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val cacheHit = Output(Bool())
        val cacheMiss = Output(Bool())
        val coherentCacheProfile = Output(new CoherentCacheProfile)
    })
    private val ramBytes = 1 << 26
    private val p = OooParams(renameWidth = issueWidth, commitWidth = issueWidth,
        completionWidth = issueWidth, speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = ramBytes, bufferedRamStores = true, compressedInstructions = true)
    private val platform = Module(new MachinePlatform(p, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = ramBytes, translationService = true,
        translationLevels = 3, coreDataTranslation = true, coreInstructionTranslation = true,
        coherentLineCache = cacheMode == "coherent",
        coherentLineCacheLines = if (cacheMode == "coherent") cacheLines else 0))
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
    io.commit1 := platform.io.commit(1).valid
    io.commit1Pc := platform.io.commit(1).bits.pc
    io.commit2 := (if (issueWidth == 4) platform.io.commit(2).valid else false.B)
    io.commit2Pc := (if (issueWidth == 4) platform.io.commit(2).bits.pc else 0.U)
    io.commit3 := (if (issueWidth == 4) platform.io.commit(3).valid else false.B)
    io.commit3Pc := (if (issueWidth == 4) platform.io.commit(3).bits.pc else 0.U)
    io.trap := platform.io.trap.valid
    io.trapPc := platform.io.trap.bits.pc
    io.trapCause := platform.io.trap.bits.cause
    io.trapTval := platform.io.trap.bits.tval
    io.fetchPc := platform.io.fetchPc
    io.uartTx := platform.io.uartTx
    io.cacheHit := platform.io.activity.get.cacheHit
    io.cacheMiss := platform.io.activity.get.cacheMiss
    io.coherentCacheProfile := platform.io.activity.get.coherentCacheProfile
}

object LinuxPlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new LinuxPlatformGsim(args.lift(1).map(_.toInt).getOrElse(2),
        args.lift(2).getOrElse("direct"), args.lift(3).map(_.toInt).getOrElse(128)),
        Array("--target-dir", output.toString))
}
