package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.memory.CacheStallEvents

class MachineCoreGsim(
    p: OooParams,
    wired: Boolean = false,
    mapped: Boolean = false,
    synchronous: Boolean = false,
    cached: Boolean = false,
    ramResponseDelay: Int = 0,
    tileLinkMemory: Boolean = false,
    splitTileLinkMemory: Boolean = false,
    tileLinkFetch: Boolean = false,
    coherentLineCache: Boolean = false,
    coherentLineCacheLines: Int = 0,
    instructionLineCacheLines: Int = 0,
    systemRecoveryFixture: Boolean = false
) extends Module {
    require(!p.registeredFetchPacket || (!synchronous && !mapped && !wired),
        "registered raw-fetch machine fixture supports only the direct instruction/MSI boundary")
    // GSIM applies registers at the start of step(). This is a test-device
    // cursor for the next raw instruction offer, never an architectural oracle.
    val nextFetchPc = IO(Output(UInt(64.W)))
    val headTrapAccepted = IO(Output(Bool()))
    val emptyTrapAccepted = IO(Output(Bool()))
    require(!systemRecoveryFixture || (!synchronous && !mapped && !wired && p.pmpEntries == 0),
        "authorization fixture observes the direct MachineCore boundary; VM/PMP remain separate tests")
    // Only this opt-in fixture has a delayed *external* FENCE.I flush reply.
    // Bores below are observational; no internal completion/grant is driven.
    val systemFenceHold = if (systemRecoveryFixture) IO(Input(Bool())) else WireDefault(false.B)
    def systemBool(name: String): Bool =
        if (systemRecoveryFixture) IO(Output(Bool())).suggestName(name) else WireDefault(false.B)
    def systemUInt(name: String, width: Int): UInt =
        if (systemRecoveryFixture) IO(Output(UInt(width.W))).suggestName(name) else WireDefault(0.U(width.W))
    val systemStartSeen = systemBool("systemStartSeen")
    val systemStartPc = systemUInt("systemStartPc", 64)
    val systemStartIndex = systemUInt("systemStartIndex", p.robBits)
    val systemStartTag = systemUInt("systemStartTag", p.tagBits)
    val systemOfferValid = systemBool("systemOfferValid")
    val systemOfferReady = systemBool("systemOfferReady")
    val systemOfferRedirect = systemBool("systemOfferRedirect")
    val systemOfferException = systemBool("systemOfferException")
    val systemOfferIndex = systemUInt("systemOfferIndex", p.robBits)
    val systemOfferTag = systemUInt("systemOfferTag", p.tagBits)
    val systemRecoveryAck = systemBool("systemRecoveryAck")
    val systemRedirectMatch = systemBool("systemRedirectMatch")
    val systemInvalidateRequested = systemBool("systemInvalidateRequested")
    val systemInvalidated = systemBool("systemInvalidated")
    val systemProtectedSeen = systemBool("systemProtectedSeen")
    val systemOwnerIndex = systemUInt("systemOwnerIndex", p.robBits)
    val systemOwnerTag = systemUInt("systemOwnerTag", p.tagBits)
    val systemLsuComplete = systemBool("systemLsuComplete")
    val systemMComplete = systemBool("systemMComplete")
    val io = IO(new Bundle {
        val timerInterrupt   = Input(Bool())
        val timeValue        = Input(UInt(64.W))
        val timerTick        = Input(Bool())
        val programHold      = Input(Bool())
        val programWrite     = Input(Bool())
        val programIndex     = Input(UInt(11.W))
        val programData      = Input(UInt(32.W))
        val fetchWait        = Output(Bool())
        val dmaActive        = Output(Bool())
        val cpuMemoryFire    = Output(Bool())
        val dmaMemoryFire    = Output(Bool())
        val coherentReleaseData = Output(Bool())
        val coherentProbeAckData = Output(Bool())
        val lineFillGetFire = Output(Bool())
        val lineFillGetAddress = Output(UInt(64.W))
        val cacheStalls      = Output(new CacheStallEvents)
        val ramRequestStall  = Output(Bool())
        val ramResponseStall = Output(Bool())
        val fetchGetFire     = Output(Bool())
        val fetchGetAddress  = Output(UInt(64.W))
        val fetchGetSize     = Output(UInt(3.W))
        val sources          = Input(UInt(31.W))
        val uartRx           = Input(Bool())
        val uartTx           = Output(Bool())
        val msiError         = Output(Bool())
        val instruction0     = Input(Valid(UInt(32.W)))
        val instruction1     = Input(Valid(UInt(32.W)))
        val accepted0        = Output(Bool())
        val accepted1        = Output(Bool())
        val fetchPc          = Output(UInt(64.W))
        val commitEnable     = Input(Bool())
        val commit0          = Output(Valid(new CommitRecord(p)))
        val commit1          = Output(Valid(new CommitRecord(p)))
        val commit2          = Output(Valid(new CommitRecord(p)))
        val commit3          = Output(Valid(new CommitRecord(p)))
        val trap             = Output(Valid(new HeadException(p)))
        val redirect         = Output(Valid(new FrontendRedirect(p)))
        val recovering       = Output(Bool())
        val memory           = new DataPort
        val msi              = Flipped(new RegisterPort)
        val externalPending  = Output(UInt(2.W))
        val inspectRegister  = Input(UInt(5.W))
        val committedValue   = Output(UInt(64.W))
    })
    io.dmaActive        := false.B
    io.cpuMemoryFire    := false.B
    io.dmaMemoryFire    := false.B
    io.coherentReleaseData := false.B
    io.coherentProbeAckData := false.B
    io.lineFillGetFire := false.B
    io.lineFillGetAddress := 0.U
    io.cacheStalls      := 0.U.asTypeOf(new CacheStallEvents)
    io.ramRequestStall  := false.B
    io.ramResponseStall := false.B
    io.fetchGetFire     := false.B
    io.fetchGetAddress  := 0.U
    io.fetchGetSize     := 0.U
    io.commit2 := 0.U.asTypeOf(io.commit2)
    io.commit3 := 0.U.asTypeOf(io.commit3)
    io.fetchWait        := false.B
    io.uartTx           := true.B
    nextFetchPc         := io.fetchPc
    headTrapAccepted    := false.B
    emptyTrapAccepted   := false.B
    if (synchronous) {
        val core = Module(new MachinePlatform(p, programmable = true, sharedReadCache = cached,
            ramResponseDelay = ramResponseDelay, tileLinkMemory = tileLinkMemory,
            splitTileLinkMemory = splitTileLinkMemory, tileLinkFetch = tileLinkFetch,
            coherentLineCache = coherentLineCache, coherentLineCacheLines = coherentLineCacheLines,
            instructionLineCacheLines = instructionLineCacheLines))
        io.dmaActive              := core.io.activity.get.dmaActive
        io.cpuMemoryFire          := core.io.activity.get.cpuMemoryFire
        io.dmaMemoryFire          := core.io.activity.get.dmaMemoryFire
        io.coherentReleaseData    := core.io.activity.get.coherentReleaseData
        io.coherentProbeAckData   := core.io.activity.get.coherentProbeAckData
        io.lineFillGetFire        := core.io.activity.get.lineFillGetFire
        io.lineFillGetAddress     := core.io.activity.get.lineFillGetAddress
        io.cacheStalls            := core.io.activity.get.cacheStalls
        io.ramRequestStall        := core.io.activity.get.ramRequestStall
        io.ramResponseStall       := core.io.activity.get.ramResponseStall
        io.fetchGetFire           := core.io.activity.get.fetchGetFire
        io.fetchGetAddress        := core.io.activity.get.fetchGetAddress
        io.fetchGetSize           := core.io.activity.get.fetchGetSize
        core.io.timerTick         := io.timerTick
        core.io.uartRx            := io.uartRx
        io.uartTx                 := core.io.uartTx
        core.io.sources           := io.sources
        io.msiError               := core.io.msiError
        core.io.program.get.hold  := io.programHold
        core.io.program.get.write := io.programWrite
        core.io.program.get.index := io.programIndex
        core.io.program.get.data  := io.programData
        io.fetchWait              := core.io.fetchWait
        core.io.commitEnable      := io.commitEnable
        core.io.inspectRegister   := io.inspectRegister
        io.memory.request.valid   := false.B
        io.memory.request.bits    := 0.U.asTypeOf(io.memory.request.bits)
        io.memory.response.ready  := false.B
        io.msi.request.ready      := false.B
        io.msi.response.valid     := false.B
        io.msi.response.bits      := 0.U.asTypeOf(io.msi.response.bits)
        io.accepted0              := false.B
        io.accepted1              := false.B
        io.fetchPc                := core.io.fetchPc
        io.commit0                := core.io.commit(0)
        io.commit1                := core.io.commit(1)
        if (p.commitWidth > 2) {
            io.commit2 := core.io.commit(2)
            io.commit3 := core.io.commit(3)
        }
        io.trap                   := core.io.trap
        io.redirect               := core.io.redirect
        io.recovering             := core.io.recovering
        io.externalPending        := core.io.externalPending
        io.committedValue         := core.io.committedValue
    } else if (mapped) {
        val core = Module(new MappedMachineCore(p))
        core.io.fenceIFlushReady := true.B
        core.io.timerInterrupt  := io.timerInterrupt
        core.io.timeValue       := io.timeValue
        core.io.sources         := io.sources
        io.msiError             := core.io.msiError
        core.io.instructions(0) := io.instruction0
        core.io.instructions(1) := io.instruction1
        core.io.instructionFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
        core.io.instructionPageFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
        core.io.commitEnable    := io.commitEnable
        core.io.inspectRegister := io.inspectRegister
        io.memory <> core.io.memory
        io.msi.request.ready  := false.B
        io.msi.response.valid := false.B
        io.msi.response.bits  := 0.U.asTypeOf(io.msi.response.bits)
        io.accepted0          := core.io.accepted(0)
        io.accepted1          := core.io.accepted(1)
        io.fetchPc            := core.io.fetchPc
        io.commit0            := core.io.commit(0)
        io.commit1            := core.io.commit(1)
        io.trap               := core.io.trap
        io.redirect           := core.io.redirect
        io.recovering         := core.io.recovering
        io.externalPending    := core.io.externalPending
        io.committedValue     := core.io.committedValue
    } else if (wired) {
        val core = Module(new WiredMachineCore(p))
        core.io.timerInterrupt  := io.timerInterrupt
        core.io.timeValue       := io.timeValue
        core.io.sources         := io.sources
        io.msiError             := core.io.msiError
        core.io.instructions(0) := io.instruction0
        core.io.instructions(1) := io.instruction1
        core.io.instructionFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
        core.io.instructionPageFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
        core.io.commitEnable    := io.commitEnable
        core.io.inspectRegister := io.inspectRegister
        io.memory <> core.io.memory
        io.msi <> core.io.interruptControl
        io.accepted0       := core.io.accepted(0)
        io.accepted1       := core.io.accepted(1)
        io.fetchPc         := core.io.fetchPc
        io.commit0         := core.io.commit(0)
        io.commit1         := core.io.commit(1)
        io.trap            := core.io.trap
        io.redirect        := core.io.redirect
        io.recovering      := core.io.recovering
        io.externalPending := core.io.externalPending
        io.committedValue  := core.io.committedValue
    } else {
        val core = Module(new MachineCore(p))
        if (p.registeredFetchPacket) {
            // MachineCore deliberately does not expose this production port;
            // bore only into this test wrapper, without changing its interface.
            nextFetchPc := BoringUtils.bore(core.core.io.nextFetchPc.get)
        }
        if (p.fastHeadTrapRecovery) {
            headTrapAccepted := BoringUtils.bore(core.core.backend.headTrapAccepted)
            emptyTrapAccepted := BoringUtils.bore(core.core.backend.emptyTrap)
        }
        if (systemRecoveryFixture) {
            val backend = core.core.backend
            val unit = backend.systemUnit.get
            systemStartSeen := BoringUtils.bore(backend.systemStart)
            systemStartPc := BoringUtils.bore(unit.io.start.bits.pc)
            systemStartIndex := BoringUtils.bore(unit.io.start.bits.token.index)
            systemStartTag := BoringUtils.bore(unit.io.start.bits.token.tag)
            systemOfferValid := BoringUtils.bore(unit.io.complete.valid)
            systemOfferReady := BoringUtils.bore(unit.io.complete.ready)
            systemOfferRedirect := BoringUtils.bore(unit.io.complete.bits.redirect)
            systemOfferException := BoringUtils.bore(unit.io.complete.bits.completion.exception)
            systemOfferIndex := BoringUtils.bore(unit.io.complete.bits.completion.token.index)
            systemOfferTag := BoringUtils.bore(unit.io.complete.bits.completion.token.tag)
            // Match is the actual downstream authorization, not an OR bypass
            // with headSystem.accepted. This also supports the old generic A/B.
            systemRecoveryAck := BoringUtils.bore(backend.localRedirectAccepted)
            systemRedirectMatch := BoringUtils.bore(backend.systemRedirectMatches)
            systemInvalidateRequested := BoringUtils.bore(backend.systemInvalidate)
            systemInvalidated := BoringUtils.bore(backend.io.invalidateFetch)
            systemProtectedSeen := BoringUtils.bore(backend.systemProtected)
            systemOwnerIndex := BoringUtils.bore(backend.systemOwner.index)
            systemOwnerTag := BoringUtils.bore(backend.systemOwner.tag)
            systemLsuComplete := BoringUtils.bore(backend.lsu.io.complete.valid)
            systemMComplete := BoringUtils.bore(backend.mCompleteValid)
        }
        core.io.fenceIFlushReady := !systemFenceHold
        core.io.timerInterrupt  := io.timerInterrupt
        core.io.timeValue       := io.timeValue
        io.msiError             := false.B
        core.io.instructions(0) := io.instruction0
        core.io.instructions(1) := io.instruction1
        core.io.instructionFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
        core.io.instructionPageFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
        core.io.commitEnable    := io.commitEnable
        core.io.inspectRegister := io.inspectRegister
        io.memory <> core.io.memory
        io.msi <> core.io.msi
        io.accepted0       := core.io.accepted(0)
        io.accepted1       := core.io.accepted(1)
        io.fetchPc         := core.io.fetchPc
        io.commit0         := core.io.commit(0)
        io.commit1         := core.io.commit(1)
        io.trap            := core.io.trap
        io.redirect        := core.io.redirect
        io.recovering      := core.io.recovering
        io.externalPending := core.io.externalPending
        io.committedValue  := core.io.committedValue
    }
}
/** Exact two-issue backend and both new pipeline cuts at the DIRECT-IRQ
  * instruction/data/MSI test boundary. The existing SystemModel IRQ oracle
  * assumes direct IMSIC levels. Production registered IMSIC integration must
  * be verified separately and is not claimed by this emitter.
  */
object ThroughputMachineCoreGsimMain extends App {
    val profile = args.lift(1).getOrElse("staged-throughput")
    val p = ThroughputPerfConfig.params(profile).copy(registeredImsicInterrupts = false)
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2 &&
        p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 &&
        p.memoryEntries == 2 && p.branchPredictorEntries == 32)
    require(profile != "staged-throughput" ||
        (p.registeredIssueExecute && p.registeredFetchPacket && p.fastHeadTrapRecovery &&
            p.fastHeadSystemRecovery && p.tentativeRenameSources && p.sharedPhysicalSourceDecode),
        "throughput head-trap fixture must retain both pipeline cuts and fast head-trap recovery")
    println(s"MACHINE_HEAD_TRAP_FIXTURE profile=$profile irqBoundary=DIRECT-IRQ " +
        s"registeredImsicInterrupts=${p.registeredImsicInterrupts} rob=${p.robEntries} " +
        s"prf=${p.physicalRegs} tagBits=${p.tagBits} memoryEntries=${p.memoryEntries} " +
        s"branchEntries=${p.branchPredictorEntries} registeredIssueExecute=${p.registeredIssueExecute} " +
        s"registeredFetchPacket=${p.registeredFetchPacket} fastHeadTrapRecovery=${p.fastHeadTrapRecovery}")
    ChiselStage.emitCHIRRTLFile(new MachineCoreGsim(p), Array("--target-dir", args.head))
}
/** Same hardware geometry/profile; the second argument can retain generic
  * system recovery for a same-stimulus cycle/handshake A/B. The other two new
  * candidate flags stay enabled in both models. No production port changes.
  */
object AuthorizationMachineCoreGsimMain extends App {
    val p = ThroughputPerfConfig.params("staged-throughput").copy(
        registeredImsicInterrupts = false, fastHeadSystemRecovery = !args.drop(1).contains("generic-system"))
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2 &&
        p.registeredIssueExecute && p.registeredFetchPacket && p.fastHeadTrapRecovery &&
        p.tentativeRenameSources && p.sharedPhysicalSourceDecode)
    println(s"AUTHORIZATION_MACHINE_FIXTURE headSystem=${p.fastHeadSystemRecovery} " +
        s"tentativeSources=${p.tentativeRenameSources} sharedDecode=${p.sharedPhysicalSourceDecode} " +
        "irqBoundary=DIRECT-IRQ oracle=SystemModel fixture=legal-fence-flush-backpressure")
    ChiselStage.emitCHIRRTLFile(new MachineCoreGsim(p, systemRecoveryFixture = true),
        Array("--target-dir", args.head))
}

object MachineCoreGsimMain extends App {
    val p = OooParams(
        renameWidth = args.lift(8).map(_.toInt).getOrElse(2),
        commitWidth = args.lift(8).map(_.toInt).getOrElse(2),
        completionWidth = args.lift(8).map(_.toInt).getOrElse(2),
        robEntries = args(1).toInt,
        physicalRegs = args(2).toInt,
        speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = 4096,
        bufferedRamStores = true,
        compressedInstructions = args.lift(9).contains("compressed"),
        instructionCacheSets = args.lift(10).map(_.toInt).getOrElse(0),
        flowTileLinkResponse = args.lift(4).contains("tilelink-flow"),
        memoryEntries = args.lift(5).map(_.toInt).getOrElse(4)
    )
    ChiselStage.emitCHIRRTLFile(
        new MachineCoreGsim(
            p,
            args.length > 4 && args(4) == "wired",
            args.length > 4 && args(4) == "mapped",
            args.length > 4 && (args(4) == "synchronous" || args(4) == "cached" ||
                args(4) == "tilelink" || args(4) == "tilelink-flow" || args(4) == "tilelink-split" ||
                args(4) == "tilelink-dual" || args(4) == "tilelink-dual-split" ||
                args(4) == "tilelink-coherent" || args(4) == "tilelink-coherent-evict" ||
                args(4) == "tilelink-dual-split-coherent"),
            args.length > 4 && args(4) == "cached",
            args.lift(6).map(_.toInt).getOrElse(0),
            args.length > 4 && (args(4) == "tilelink" || args(4) == "tilelink-flow" ||
                args(4) == "tilelink-split" ||
                args(4) == "tilelink-dual" || args(4) == "tilelink-dual-split" ||
                args(4) == "tilelink-coherent" || args(4) == "tilelink-coherent-evict" ||
                args(4) == "tilelink-dual-split-coherent"),
            args.length > 4 && (args(4) == "tilelink-split" || args(4) == "tilelink-dual-split" ||
                args(4) == "tilelink-dual-split-coherent"),
            args.length > 4 && (args(4) == "tilelink-dual" || args(4) == "tilelink-dual-split" ||
                args(4) == "tilelink-coherent" || args(4) == "tilelink-coherent-evict" ||
                args(4) == "tilelink-dual-split-coherent"),
            args.length > 4 && (args(4) == "tilelink-coherent" || args(4) == "tilelink-coherent-evict" ||
                args(4) == "tilelink-dual-split-coherent"),
            if (args.length > 4 && args(4) == "tilelink-coherent-evict") 16 else 0,
            args.lift(7).map(_.toInt).getOrElse(0)
        ),
        Array("--target-dir", args.head)
    )
}
object MachineCoreRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new MachineCore(),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object CoherentPlatformRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new MachinePlatform(romFiles = args.drop(1).toSeq, tileLinkMemory = true,
            tileLinkFetch = true, coherentLineCache = true),
        Array("--target-dir", args.head)
    )
}

object WiredMachineCoreRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new WiredMachineCore(),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object MappedMachineCoreRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new MappedMachineCore(),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
object CoreRegisterRouterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CoreRegisterRouter(BigInt("0c000000", 16)), Array("--target-dir", args.head))
}

object MachinePlatformRtlMain extends App {
    val files = if (args.length == 3) args.drop(1).toSeq else Seq.empty
    ChiselStage.emitSystemVerilogFile(
        new MachinePlatform(romFiles = files),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object TileLinkMachinePlatformRtlMain extends App {
    val files = if (args.length == 3) args.drop(1).toSeq else Seq.empty
    ChiselStage.emitSystemVerilogFile(
        new MachinePlatform(romFiles = files, tileLinkMemory = true),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object SplitTileLinkMachinePlatformRtlMain extends App {
    val files = if (args.length == 3) args.drop(1).toSeq else Seq.empty
    ChiselStage.emitSystemVerilogFile(
        new MachinePlatform(romFiles = files, tileLinkMemory = true, splitTileLinkMemory = true),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object Memory8MachinePlatformRtlMain extends App {
    val files = if (args.length == 3) args.drop(1).toSeq else Seq.empty
    val p = OooParams(
        speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = 4096,
        bufferedRamStores = true,
        memoryEntries = 8
    )
    ChiselStage.emitSystemVerilogFile(
        new MachinePlatform(p, romFiles = files),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

object CachedMachinePlatformRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new MachinePlatform(romFiles = args.drop(1).toSeq, sharedReadCache = true),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
