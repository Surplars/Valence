package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo.{MachinePlatform, OooParams}

/** Programmable 8 KiB machine platform for end-to-end upper-RAM atomic checks. */
class Atomic8PlatformGsim extends Module {
    val p = OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 8192,
        bufferedRamStores = true, compressedInstructions = true)
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(8.W))
        val romData = Input(UInt(32.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Bool())
        val commit1 = Output(Bool())
        val trap = Output(Bool())
        val trapCause = Output(UInt(64.W))
        val trapPc = Output(UInt(64.W))
        val trapTval = Output(UInt(64.W))
        val cpuMemoryFire = Output(Bool())
    })
    val platform = Module(new MachinePlatform(p, romWords = 256, programmable = true,
        tileLinkMemory = true, tileLinkFetch = true, ramBytes = 8192))
    platform.io.timerTick := true.B
    platform.io.sources := 0.U
    platform.io.uartRx := true.B
    platform.io.commitEnable := true.B
    platform.io.inspectRegister := io.inspectRegister
    platform.io.program.get.hold := io.hold
    platform.io.program.get.write := io.romWrite
    platform.io.program.get.index := io.romIndex
    platform.io.program.get.data := io.romData
    io.committedValue := platform.io.committedValue
    io.commit0 := platform.io.commit(0).valid
    io.commit1 := platform.io.commit(1).valid
    io.trap := platform.io.trap.valid
    io.trapCause := platform.io.trap.bits.cause
    io.trapPc := platform.io.trap.bits.pc
    io.trapTval := platform.io.trap.bits.tval
    io.cpuMemoryFire := platform.io.activity.get.cpuMemoryFire
}

object Atomic8PlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new Atomic8PlatformGsim, Array("--target-dir", output.toString))
}
