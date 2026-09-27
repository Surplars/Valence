package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import soc.core.ooo.{MachinePlatform, OooParams, SvTranslationRequest, SvTranslationResponse}

class TranslationPlatformGsim(romFiles: Seq[String], ramFile: String) extends Module {
    val io = IO(new Bundle {
        val requestValid0 = Input(Bool())
        val request0 = Input(new SvTranslationRequest)
        val requestReady0 = Output(Bool())
        val responseValid0 = Output(Bool())
        val response0 = Output(new SvTranslationResponse)
        val responseReady0 = Input(Bool())
        val hit0 = Output(Bool())
        val walk0 = Output(Bool())
        val pteRead0 = Output(Bool())
        val pteCacheHit0 = Output(Bool())
        val requestValid1 = Input(Bool())
        val request1 = Input(new SvTranslationRequest)
        val requestReady1 = Output(Bool())
        val responseValid1 = Output(Bool())
        val response1 = Output(new SvTranslationResponse)
        val responseReady1 = Input(Bool())
        val hit1 = Output(Bool())
        val walk1 = Output(Bool())
        val pteRead1 = Output(Bool())
        val pteCacheHit1 = Output(Bool())
        val flush = Input(Bool())
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(11.W))
        val romData = Input(UInt(32.W))
        val ramWrite = Input(Bool())
        val ramIndex = Input(UInt(13.W))
        val ramData = Input(UInt(64.W))
        val committed = Output(Bool())
        val trap = Output(Bool())
        val trapPc = Output(UInt(64.W))
        val trapCause = Output(UInt(64.W))
        val trapTval = Output(UInt(64.W))
        val satp = Output(UInt(64.W))
        val sum = Output(Bool())
        val mxr = Output(Bool())
        val sfenceFlush = Output(Bool())
        val vmFlushPending = Output(Bool())
    })
    val p = OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true)
    val platform = Module(new MachinePlatform(p, romFiles = romFiles, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = 65536, translationService = true,
        translationLevels = 5, ramInitFile = ramFile))
    platform.io.timerTick := false.B
    platform.io.sources := 0.U
    platform.io.uartRx := true.B
    platform.io.commitEnable := true.B
    platform.io.inspectRegister := 0.U
    platform.io.translationFlush.get := io.flush
    platform.io.program.get.hold := io.hold
    platform.io.program.get.write := io.romWrite
    platform.io.program.get.index := io.romIndex
    platform.io.program.get.data := io.romData
    platform.io.ramProgram.get.write := io.ramWrite
    platform.io.ramProgram.get.index := io.ramIndex
    platform.io.ramProgram.get.data := io.ramData
    platform.io.translation.get(0).request.valid := io.requestValid0
    platform.io.translation.get(0).request.bits := io.request0
    io.requestReady0 := platform.io.translation.get(0).request.ready
    io.responseValid0 := platform.io.translation.get(0).response.valid
    io.response0 := platform.io.translation.get(0).response.bits
    platform.io.translation.get(0).response.ready := io.responseReady0
    io.hit0 := platform.io.translationEvents.get.hit(0)
    io.walk0 := platform.io.translationEvents.get.walk(0)
    io.pteRead0 := platform.io.translationEvents.get.pteRead(0)
    io.pteCacheHit0 := platform.io.translationEvents.get.pteCacheHit(0)
    platform.io.translation.get(1).request.valid := io.requestValid1
    platform.io.translation.get(1).request.bits := io.request1
    io.requestReady1 := platform.io.translation.get(1).request.ready
    io.responseValid1 := platform.io.translation.get(1).response.valid
    io.response1 := platform.io.translation.get(1).response.bits
    platform.io.translation.get(1).response.ready := io.responseReady1
    io.hit1 := platform.io.translationEvents.get.hit(1)
    io.walk1 := platform.io.translationEvents.get.walk(1)
    io.pteRead1 := platform.io.translationEvents.get.pteRead(1)
    io.pteCacheHit1 := platform.io.translationEvents.get.pteCacheHit(1)
    io.committed := platform.io.commit.map(_.valid).reduce(_ || _)
    io.trap := platform.io.trap.valid
    io.trapPc := platform.io.trap.bits.pc
    io.trapCause := platform.io.trap.bits.cause
    io.trapTval := platform.io.trap.bits.tval
    io.satp := platform.io.translationEvents.get.vmState.satp
    io.sum := platform.io.translationEvents.get.vmState.sum
    io.mxr := platform.io.translationEvents.get.vmState.mxr
    io.sfenceFlush := platform.io.translationEvents.get.flush
    io.vmFlushPending := platform.io.translationEvents.get.flushPending
}

object TranslationPlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    val firmware = Seq("fff00293", "3b029073", "01f00293", "3a029073",
        "000c02b7", "3002a073", "800002b7", "02029293", "01028293", "18029073",
        "fff00313", "18031073", "12000073", "0000006f").map(BigInt(_, 16))
    for (bank <- 0 until 2) {
        val contents = (0 until 1024).map { i =>
            val word = firmware.lift(i * 2 + bank).getOrElse(BigInt("00000013", 16)).toLong
            f"$word%08x"
        }
        Files.write(output.resolve(s"rom-$bank.hex"), (contents.mkString("\n") + "\n").getBytes(StandardCharsets.US_ASCII))
    }
    val virtualAddress = BigInt("40002000", 16)
    val ramBasePpn = BigInt("80010", 16)
    val words = Array.fill[BigInt](8192)(BigInt(0))
    for ((levels, rootPage) <- Seq(3 -> 0, 4 -> 3, 5 -> 7)) {
        for (level <- (levels - 1) to 0 by -1) {
            val page = rootPage + levels - 1 - level
            val vpn = ((virtualAddress >> (12 + 9 * level)) & 511).toInt
            val flags = if (level == 0) 0xcf else 1
            val ppn = if (level == 0) BigInt("80000", 16) else ramBasePpn + page + 1
            words(page * 512 + vpn) = (ppn << 10) | flags
        }
    }
    val ram = output.resolve("ram.hex")
    Files.write(ram, (words.map(w => f"${w.toLong}%016x").mkString("\n") + "\n")
        .getBytes(StandardCharsets.US_ASCII))
    ChiselStage.emitCHIRRTLFile(new TranslationPlatformGsim(Seq(
        output.resolve("rom-0.hex").toString, output.resolve("rom-1.hex").toString),
        ram.toString),
        Array("--target-dir", output.toString))
}
