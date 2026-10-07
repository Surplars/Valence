package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.PopCount
import java.nio.file.{Files, Paths}
import soc.core.ooo.{MachinePlatform, OooParams, SvTranslationRequest}

class VmDataPlatformGsim(coherent: Boolean = false, compact: Boolean = false,
    bufferedCoherentResponses: Boolean = false,
    registeredLocalStoreResponses: Boolean = false,
    registeredMemoryRequests: Boolean = false,
    registeredRetirement: Boolean = false,
    registeredLoadReplay: Boolean = false,
    earlyRecoveryIssueBlock: Boolean = false,
    precompleteMispredictedBranch: Boolean = false,
    registeredPhysicalOwners: Boolean = false,
    stagedFabric: Boolean = false, controlStage: Boolean = false,
    bufferedTranslatedResponses: Boolean = false, executeStage: Boolean = false,
    renameStage: Boolean = false, retireStage: Boolean = false, redirectStage: Boolean = false,
    preparationStage: Boolean = false, payloadStage: Boolean = false, returnStage: Boolean = false,
    fetchAddressStage: Boolean = false, fetchControlStage: Boolean = false,
    recoveryControlStage: Boolean = false, executeSelectStage: Boolean = false,
    frontendSelectStage: Boolean = false, sensitivePathsStage: Boolean = false,
    decodeAlignStage: Boolean = false, rankLegalityStage: Boolean = false,
    wordDestinationStage: Boolean = false, requestCaptureStage: Boolean = false,
    romBoundaryStage: Boolean = false, controlHeadsStage: Boolean = false,
    throughputStage: Boolean = false) extends Module {
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
    val p = if (compact) OooParams(robEntries = 16, physicalRegs = 48, memoryEntries = 2,
        branchPredictorEntries = 32, instructionCacheSets = 16, returnStackEntries = 8,
        storeBufferEntries = 2, speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = 65536, bufferedRamStores = true,
        registeredLocalStoreResponses = registeredLocalStoreResponses,
        registeredMemoryRequests = registeredMemoryRequests,
        registeredBranchRedirect = true, registeredMemoryAddress = true,
        registeredStoreResponseOwners = true, registeredRobRetirement = registeredRetirement, recoveryWidth = 4,
        registeredLoadReplay = registeredLoadReplay,
        earlyRecoveryIssueBlock = earlyRecoveryIssueBlock,
        precompleteMispredictedBranch = precompleteMispredictedBranch,
        parallelRenameAdmission = controlStage, stableFetchFaultMetadata = controlStage,
        earlyRankedOperands = executeStage, pcDerivedReturnLinks = executeStage,
        earlyRenameDestinations = renameStage, parallelPrfReadyUpdates = renameStage,
        stablePredictionMetadata = renameStage,
        balancedBranchCompare = retireStage && !redirectStage, separateBranchRetireFault = retireStage,
        parallelReturnStackControl = retireStage,
        earlyRedirectCapture = redirectStage,
        parallelMemoryPreparation = preparationStage, alignedFetchPmp = preparationStage,
        parallelIssuePayload = payloadStage, rawFetchPresence = payloadStage,
        oneHotPhysicalOperands = returnStage && !fetchAddressStage, registeredTranslatedResponses = returnStage,
        directMemoryResponse = returnStage, parallelFetchAddresses = fetchAddressStage,
        prefixTileLinkDecode = fetchAddressStage,
        rawTileLinkResponseMetadata = fetchControlStage, bufferedRomReplies = fetchControlStage,
        parallelPredictionQualification = fetchControlStage,
        parallelRecoveryAdmission = recoveryControlStage, parallelRedirectTokens = recoveryControlStage,
        parallelIssueRanks = executeSelectStage, parallelAluResults = executeSelectStage,
        parallelCompletionPayload = executeSelectStage,
        parallelFetchTagLookup = frontendSelectStage, parallelFrontendControl = frontendSelectStage,
        parallelAuipcQualification = frontendSelectStage,
        parallelPredictionSources = sensitivePathsStage, parallelAddressSums = sensitivePathsStage,
        bufferedFetchRequests = sensitivePathsStage, parallelFetchAlignment = decodeAlignStage,
        parallelDecodeLegality = decodeAlignStage, flowThroughFetchRequests = decodeAlignStage,
        parallelMinMaxResults = decodeAlignStage, parallelBitLegality = rankLegalityStage,
        parallelRenameRanks = rankLegalityStage, parallelMinMaxWordResults = rankLegalityStage,
        parallelArchitecturalDestinations = wordDestinationStage, parallelAluWordResults = wordDestinationStage,
        independentFetchCapture = requestCaptureStage, parallelHomeQualification = requestCaptureStage,
        registeredFabricBoundary = romBoundaryStage,
        registeredTranslationHeads = controlHeadsStage, registeredPredictionTraining = controlHeadsStage,
        parallelMemoryPayload = controlHeadsStage, parallelPacketPmp = controlHeadsStage,
        registeredIssueExecute = throughputStage, registeredFetchPacket = throughputStage,
        fastHeadTrapRecovery = throughputStage, fastHeadSystemRecovery = throughputStage,
        tentativeRenameSources = throughputStage, sharedPhysicalSourceDecode = throughputStage,
        ownerLocalOperandReady = throughputStage,
        earlyStorePreparation = throughputStage, parallelMulDivDispatch = throughputStage,
        registeredMulDivOperands = throughputStage,
        compressedInstructions = true)
    else OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true)
    if (throughputStage) {
        require(compact && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2 &&
            p.registeredIssueExecute && p.registeredFetchPacket && p.fastHeadTrapRecovery &&
            p.fastHeadSystemRecovery && p.tentativeRenameSources && p.sharedPhysicalSourceDecode &&
            p.ownerLocalOperandReady && p.earlyStorePreparation && p.parallelMulDivDispatch,
            "throughput VM fixture must retain the complete candidate backend")
        println("VM_DATA_THROUGHPUT: rob=16 prf=48 mem=2 issueExecute=1 fetchPacket=1 " +
            "headTrap=1 headSystem=1 tentativeSources=1 sharedDecode=1 " +
            "ownerReady=1 storePreparation=1 mulDivDispatch=1")
    }
    val platform = Module(new MachinePlatform(p, programmable = true, tileLinkMemory = true,
        tileLinkFetch = true, ramBytes = 65536, translationService = true,
        translationLevels = if (compact) 3 else 4, coreDataTranslation = true,
        coherentLineCache = coherent, coherentLineCacheLines = if (compact) 32 else 0,
        instructionLineCacheLines = if (compact) 8 else 16,
        pteCacheEntries = if (compact) 4 else 8,
        bufferCoherentResponses = bufferedCoherentResponses,
        registerPhysicalResponseOwners = registeredPhysicalOwners, stagedMemoryFabric = stagedFabric,
        bufferTranslatedResponses = bufferedTranslatedResponses))
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
    ChiselStage.emitCHIRRTLFile(new VmDataPlatformGsim(args.drop(1).contains("coherent"),
        args.drop(1).contains("compact"), args.drop(1).contains("buffered-response"),
        args.drop(1).contains("registered-local-response"),
        args.drop(1).contains("registered-memory-requests"),
        args.drop(1).contains("registered-retirement"),
        args.drop(1).contains("registered-load-replay"),
        args.drop(1).contains("early-recovery-issue-block"),
        args.drop(1).contains("precomplete-mispredicted-branch"),
        args.drop(1).contains("registered-physical-owners"), args.drop(1).contains("staged-fabric"),
        args.drop(1).contains("staged-control"), args.drop(1).contains("buffered-translated-response"),
        args.drop(1).contains("staged-execute"), args.drop(1).contains("staged-rename"),
        args.drop(1).contains("staged-retire"), args.drop(1).contains("staged-redirect"),
        args.drop(1).contains("staged-preparation"), args.drop(1).contains("staged-payload"),
        args.drop(1).contains("staged-return"), args.drop(1).contains("staged-fetch-address"),
        args.drop(1).contains("staged-fetch-control"), args.drop(1).contains("staged-recovery-control"),
        args.drop(1).contains("staged-execute-select"), args.drop(1).contains("staged-frontend-select"),
        args.drop(1).contains("staged-sensitive-paths"), args.drop(1).contains("staged-decode-align"), args.drop(1).contains("staged-rank-legality"),
        args.drop(1).contains("staged-word-destination"), args.drop(1).contains("staged-request-capture"),
        args.drop(1).contains("staged-rom-boundary"), args.drop(1).contains("staged-control-heads"),
        args.drop(1).contains("staged-throughput")),
        Array("--target-dir", output.toString))
}
