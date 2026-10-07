package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo.{BoardSocConfig, MachinePlatform, OooParams}

class VmInstructionPlatformGsim(coherent: Boolean = false, wide: Boolean = false,
    fetchAddresses: Boolean = false, fetchControl: Boolean = false, frontendSelect: Boolean = false,
    sensitivePaths: Boolean = false, decodeAlign: Boolean = false, rankLegality: Boolean = false,
    requestCapture: Boolean = false, romBoundary: Boolean = false, controlHeads: Boolean = false,
    throughput: Boolean = false) extends Module {
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
    private val directParams = OooParams(renameWidth = issueWidth, commitWidth = issueWidth,
        completionWidth = issueWidth,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true, compressedInstructions = true,
        parallelFetchAddresses = fetchAddresses, prefixTileLinkDecode = fetchAddresses,
        rawTileLinkResponseMetadata = fetchControl, bufferedRomReplies = fetchControl,
        parallelPredictionQualification = fetchControl || frontendSelect,
        parallelFetchTagLookup = frontendSelect, parallelFrontendControl = frontendSelect,
        parallelAuipcQualification = frontendSelect,
        parallelPredictionSources = sensitivePaths, bufferedFetchRequests = sensitivePaths,
        parallelFetchAlignment = decodeAlign, parallelDecodeLegality = decodeAlign,
        flowThroughFetchRequests = decodeAlign, parallelBitLegality = rankLegality,
        independentFetchCapture = requestCapture, parallelHomeQualification = requestCapture,
        registeredFabricBoundary = romBoundary, registeredTranslatedResponses = controlHeads,
        registeredTranslationHeads = controlHeads, registeredPredictionTraining = controlHeads,
        parallelPacketPmp = controlHeads)
    val p = if (throughput) BoardSocConfig.timingParams("staged-throughput").copy(
        speculativeRamBase = directParams.speculativeRamBase,
        speculativeRamBytes = directParams.speculativeRamBytes,
        instructionCacheSets = directParams.instructionCacheSets) else directParams
    val platform = Module(new MachinePlatform(p, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = 65536, translationService = true,
        translationLevels = 4, coreDataTranslation = true, coreInstructionTranslation = true,
        coherentLineCache = coherent || controlHeads, bufferCoherentResponses = controlHeads,
        registerPhysicalResponseOwners = romBoundary,
        stagedMemoryFabric = romBoundary, bufferTranslatedResponses = controlHeads))
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
        args.lift(1).contains("coherent"), args.lift(1).contains("wide"),
        args.drop(1).contains("fetch-addresses"), args.drop(1).contains("fetch-control"),
        args.drop(1).contains("frontend-select"), args.drop(1).contains("sensitive-paths"),
        args.drop(1).contains("decode-align"), args.drop(1).contains("rank-legality"), args.drop(1).contains("request-capture"),
        args.drop(1).contains("rom-boundary"), args.drop(1).contains("control-heads"),
        args.drop(1).contains("throughput")),
        Array("--target-dir", output.toString))
}
