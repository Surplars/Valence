package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.log2Ceil
import java.nio.file.{Files, Paths}
import soc.core.ooo.{CoherentCacheProfile, HeadProfile, MachinePlatform, OooParams}

class CoremarkPlatformGsim(
    cacheMode: String = "direct",
    ramDelay: Int = 0,
    renameWidth: Int = 2,
    commitWidth: Int = 2,
    robEntries: Int = 32,
    physicalRegs: Int = 64,
    memoryEntries: Int = 4,
    storeBufferEntries: Int = 4,
    completionWidth: Int = 2,
    flowTileLinkResponse: Boolean = false,
    fastBufferedStoreRetire: Boolean = false,
    fastHeadLoadRetire: Boolean = false,
    branchPredictorEntries: Int = 256,
    recoveryWidth: Int = 4,
    loadCompletionBypass: Boolean = false,
    moveAlias: Boolean = false,
    mulWordPreviewBypass: Boolean = false,
    indirectTargetEntries: Int = 0,
    instructionCacheSets: Int = 0
) extends Module {
    require(Set("direct", "cache", "coherent").contains(cacheMode))
    val p = OooParams(renameWidth = renameWidth, commitWidth = commitWidth,
        robEntries = robEntries, physicalRegs = physicalRegs, memoryEntries = memoryEntries,
        storeBufferEntries = storeBufferEntries, completionWidth = completionWidth,
        flowTileLinkResponse = flowTileLinkResponse,
        fastBufferedStoreRetire = fastBufferedStoreRetire,
        fastHeadLoadRetire = fastHeadLoadRetire,
        loadCompletionBypass = loadCompletionBypass,
        moveAlias = moveAlias,
        mulWordPreviewBypass = mulWordPreviewBypass,
        indirectTargetEntries = indirectTargetEntries,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 8192,
        bufferedRamStores = true, compressedInstructions = true,
        instructionCacheSets = instructionCacheSets,
        branchPredictorEntries = branchPredictorEntries, recoveryWidth = recoveryWidth)
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(12.W))
        val romData = Input(UInt(32.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Bool())
        val commit1 = Output(Bool())
        val commit2 = Output(Bool())
        val commit3 = Output(Bool())
        val commitPc0 = Output(UInt(64.W))
        val commitPc1 = Output(UInt(64.W))
        val commitPc2 = Output(UInt(64.W))
        val commitPc3 = Output(UInt(64.W))
        val trap = Output(Bool())
        val trapCause = Output(UInt(64.W))
        val trapPc = Output(UInt(64.W))
        val fetchWait = Output(Bool())
        val fetchGetFire = Output(Bool())
        val fetchGetAddress = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val redirect = Output(Bool())
        val redirectPc = Output(UInt(64.W))
        val recovering = Output(Bool())
        val cpuMemoryFire = Output(Bool())
        val ramRequestStall = Output(Bool())
        val ramResponseStall = Output(Bool())
        val robOccupancy = Output(UInt(p.countBits.W))
        val headProfile = Output(new HeadProfile)
        val issueCount = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryBusy = Output(Bool())
        val cacheHit = Output(Bool())
        val cacheMiss = Output(Bool())
        val coherentCacheProfile = Output(new CoherentCacheProfile)
    })
    val platform = Module(new MachinePlatform(p, romWords = 4096, programmable = true,
        tileLinkMemory = true, tileLinkFetch = true, ramBytes = 8192,
        sharedReadCache = cacheMode == "cache", sharedReadCacheLines = if (cacheMode == "cache") 128 else 16,
        coherentLineCache = cacheMode == "coherent",
        ramResponseDelay = ramDelay))
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
    io.commitPc0 := platform.io.commit(0).bits.pc
    io.commitPc1 := platform.io.commit(1).bits.pc
    io.commit2 := (if (p.commitWidth > 2) platform.io.commit(2).valid else false.B)
    io.commit3 := (if (p.commitWidth > 3) platform.io.commit(3).valid else false.B)
    io.commitPc2 := (if (p.commitWidth > 2) platform.io.commit(2).bits.pc else 0.U)
    io.commitPc3 := (if (p.commitWidth > 3) platform.io.commit(3).bits.pc else 0.U)
    io.trap := platform.io.trap.valid
    io.trapCause := platform.io.trap.bits.cause
    io.trapPc := platform.io.trap.bits.pc
    io.fetchWait := platform.io.fetchWait
    io.fetchGetFire := platform.io.activity.get.fetchGetFire
    io.fetchGetAddress := platform.io.activity.get.fetchGetAddress
    io.fetchPc := platform.io.fetchPc
    io.redirect := platform.io.redirect.valid
    io.redirectPc := platform.io.redirect.bits.pc
    io.recovering := platform.io.recovering
    io.cpuMemoryFire := platform.io.activity.get.cpuMemoryFire
    io.ramRequestStall := platform.io.activity.get.ramRequestStall
    io.ramResponseStall := platform.io.activity.get.ramResponseStall
    io.robOccupancy := platform.io.activity.get.robOccupancy
    io.headProfile := platform.io.activity.get.headProfile
    io.issueCount := platform.io.activity.get.issueCount
    io.memoryBusy := platform.io.activity.get.memoryBusy
    io.cacheHit := platform.io.activity.get.cacheHit
    io.cacheMiss := platform.io.activity.get.cacheMiss
    io.coherentCacheProfile := platform.io.activity.get.coherentCacheProfile
}

object CoremarkPlatformGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new CoremarkPlatformGsim(args.lift(1).getOrElse("direct"),
        args.lift(2).map(_.toInt).getOrElse(0), args.lift(3).map(_.toInt).getOrElse(2),
        args.lift(4).map(_.toInt).getOrElse(2), args.lift(5).map(_.toInt).getOrElse(32),
        args.lift(6).map(_.toInt).getOrElse(64), args.lift(7).map(_.toInt).getOrElse(4),
        args.lift(8).map(_.toInt).getOrElse(4), args.lift(9).map(_.toInt).getOrElse(2),
        args.lift(10).contains("flow-response"), args.lift(11).contains("fast-store"),
        args.lift(12).contains("fast-load"), args.lift(13).map(_.toInt).getOrElse(256),
        args.lift(14).map(_.toInt).getOrElse(4), args.lift(15).contains("load-bypass"),
        args.lift(16).contains("move-alias"), args.lift(17).contains("word-bypass"),
        args.lift(18).map(_.toInt).getOrElse(0), args.lift(19).map(_.toInt).getOrElse(64)),
        Array("--target-dir", output.toString))
}
