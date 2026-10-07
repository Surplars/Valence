package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import java.nio.file.{Files, Path}

/** Machine datapath with a small on-chip RAM for out-of-context FPGA timing.
  * The compact profile preserves the peripherals, PMP and Sv39, but reduces microarchitectural capacity.
  * The Linux simulation's 64 MiB RAM is a functional model, not an FPGA storage implementation.
  */
class CurrentSocTimingTop(compact: Boolean = false,
    registeredLocalResponse: Boolean = false,
    registeredMemoryRequests: Boolean = false,
    registeredRetirement: Boolean = false,
    registeredLoadReplay: Boolean = false,
    earlyRecoveryIssueBlock: Boolean = false,
    precompleteMispredictedBranch: Boolean = false) extends Module {
    private val ramBytes = 16384
    private val romWords = 2048
    private val p = if (compact) OooParams(renameWidth = 2, commitWidth = 2, completionWidth = 2,
        robEntries = 16, physicalRegs = 48, memoryEntries = 2, branchPredictorEntries = 32,
        instructionCacheSets = 16, returnStackEntries = 8, storeBufferEntries = 2,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = ramBytes,
        bufferedRamStores = true,
        registeredLocalStoreResponses = registeredLocalResponse,
        registeredMemoryRequests = registeredMemoryRequests,
        registeredBranchRedirect = true, registeredMemoryAddress = true,
        registeredStoreResponseOwners = true, registeredRobRetirement = registeredRetirement, recoveryWidth = 4,
        registeredLoadReplay = registeredLoadReplay,
        earlyRecoveryIssueBlock = earlyRecoveryIssueBlock,
        precompleteMispredictedBranch = precompleteMispredictedBranch,
        compressedInstructions = true)
    else OooParams(renameWidth = 4, commitWidth = 4, completionWidth = 4,
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
        instructionLineCacheLines = if (compact) 8 else 16,
        translationService = true, translationLevels = 3,
        coreDataTranslation = true, coreInstructionTranslation = true,
        coherentLineCache = true, coherentLineCacheLines = if (compact) 32 else 128,
        pteCacheEntries = if (compact) 4 else 8,
        bufferCoherentResponses = compact))
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

class CompactSocTimingTop(registeredLocalResponse: Boolean = false,
    registeredMemoryRequests: Boolean = false,
    registeredRetirement: Boolean = false,
    registeredLoadReplay: Boolean = false,
    earlyRecoveryIssueBlock: Boolean = false,
    precompleteMispredictedBranch: Boolean = false)
    extends CurrentSocTimingTop(compact = true, registeredLocalResponse = registeredLocalResponse,
        registeredMemoryRequests = registeredMemoryRequests,
        registeredRetirement = registeredRetirement, registeredLoadReplay = registeredLoadReplay,
        earlyRecoveryIssueBlock = earlyRecoveryIssueBlock,
        precompleteMispredictedBranch = precompleteMispredictedBranch)

object CurrentSocTimingMain extends App {
    val compactOptions = Set("registered-local-response", "registered-memory-requests", "registered-retirement",
        "registered-load-replay", "early-recovery-issue-block", "precomplete-mispredicted-branch")
    require(args.length == 1 || (args.length >= 2 && args(1) == "compact" &&
        args.drop(2).forall(compactOptions.contains) && args.drop(2).distinct.length == args.length - 2),
        "usage: CurrentSocTimingMain output-directory [compact [registered-local-response] [registered-memory-requests] [registered-retirement] [registered-load-replay] [early-recovery-issue-block] [precomplete-mispredicted-branch]]")
    val output = Path.of(args(0)).toAbsolutePath
    Files.createDirectories(output)
    ChiselStage.emitSystemVerilogFile(
        if (args.length >= 2) new CompactSocTimingTop(
            registeredLocalResponse = args.drop(2).contains("registered-local-response"),
            registeredMemoryRequests = args.drop(2).contains("registered-memory-requests"),
            registeredRetirement = args.drop(2).contains("registered-retirement"),
            registeredLoadReplay = args.drop(2).contains("registered-load-replay"),
            earlyRecoveryIssueBlock = args.drop(2).contains("early-recovery-issue-block"),
            precompleteMispredictedBranch = args.drop(2).contains("precomplete-mispredicted-branch"))
        else new CurrentSocTimingTop,
        Array("--target-dir", output.toString),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
