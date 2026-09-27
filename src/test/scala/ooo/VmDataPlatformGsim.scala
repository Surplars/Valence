package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.PopCount
import java.nio.file.{Files, Paths}
import soc.core.ooo.{MachinePlatform, OooParams, SvTranslationRequest}

class VmDataPlatformGsim(coherent: Boolean = false) extends Module {
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
        val committed = Output(Bool())
        val commitCount = Output(UInt(2.W))
        val trap = Output(Bool())
        val trapCause = Output(UInt(64.W))
        val trapTval = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val cpuPhysicalRequest = Output(Bool())
        val dWalk = Output(Bool())
        val dPteRead = Output(Bool())
        val dTlbHit = Output(Bool())
        val probeAckData = Output(Bool())
        val releaseData = Output(Bool())
    })
    val p = OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true)
    val platform = Module(new MachinePlatform(p, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = 65536, translationService = true,
        translationLevels = 4, coreDataTranslation = true, coherentLineCache = coherent))
    platform.io.timerTick := false.B
    platform.io.sources := 0.U
    platform.io.uartRx := true.B
    platform.io.commitEnable := true.B
    platform.io.inspectRegister := io.inspectRegister
    platform.io.translationFlush.get := false.B
    platform.io.translation.get(0).request.valid := false.B
    platform.io.translation.get(0).request.bits := 0.U.asTypeOf(new SvTranslationRequest)
    platform.io.translation.get(0).response.ready := true.B
    platform.io.program.get.hold := io.hold
    platform.io.program.get.write := io.romWrite
    platform.io.program.get.index := io.romIndex
    platform.io.program.get.data := io.romData
    platform.io.ramProgram.get.write := io.ramWrite
    platform.io.ramProgram.get.index := io.ramIndex
    platform.io.ramProgram.get.data := io.ramData
    io.committedValue := platform.io.committedValue
    io.committed := platform.io.commit.map(_.valid).reduce(_ || _)
    io.commitCount := PopCount(platform.io.commit.map(_.valid))
    io.trap := platform.io.trap.valid
    io.trapCause := platform.io.trap.bits.cause
    io.trapTval := platform.io.trap.bits.tval
    io.fetchPc := platform.io.fetchPc
    io.cpuPhysicalRequest := platform.io.activity.get.cpuMemoryFire
    io.dWalk := platform.io.translationEvents.get.walk(1)
    io.dPteRead := platform.io.translationEvents.get.pteRead(1)
    io.dTlbHit := platform.io.translationEvents.get.hit(1)
    io.probeAckData := platform.io.activity.get.coherentProbeAckData
    io.releaseData := platform.io.activity.get.coherentReleaseData
}

object VmDataPlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new VmDataPlatformGsim(args.lift(1).contains("coherent")),
        Array("--target-dir", output.toString))
}
