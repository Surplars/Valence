package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Real frontend, translation adapter, packet permission and reservoir; no backend or synthetic fetch state. */
class FetchFaultPrecisionGsim(aligned: Boolean = true) extends Module {
    private val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(p => Files.isRegularFile(p.resolve("build.mill"))).get
    private val profile = Files.readString(root.resolve("fpga/next/timing-batch-owner-row-profile.json"))
    private val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(profile).get.group(1)
    private val options = "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSet
    require(options.size == 52)
    val p = FpgaNextConfig.fromOptions(options, defaultSelected = false).coreParams

    require(p.renameWidth == 2 && p.alignedFetchPmp && p.registeredTranslationHeads && p.fetchReplyTurnover &&
        p.fetchIdentityTranslation && p.alignedFetchPermissionStage && p.registeredFetchWindow)
    val io = IO(new Bundle {
        val pc = Input(UInt(64.W))
        val enable = Input(Bool())
        val pause = Input(Bool())
        val invalidate = Input(Bool())
        val suppress = Input(Bool())
        val linkReady = Input(Bool()) // Test-only admission gate; normal tests keep the direct link open.
        val virtualized = Input(Bool())
        val privilege = Input(UInt(2.W))
        val satp = Input(UInt(64.W))
        val sum = Input(Bool())
        val mxr = Input(Bool())
        val pmpCfg0 = Input(UInt(8.W))
        val pmpCfg1 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val pmpAddr1 = Input(UInt(54.W))
        val translation = new SvTranslationPort
        val physical = new InstructionPort(2)
        val fetchValid = Output(Bool())
        val fetchReady = Output(Bool())
        val fetchAddress = Output(UInt(64.W))
        val fetchMask = Output(UInt(2.W))
        val replyValid = Output(Bool())
        val replyReady = Output(Bool())
        val replyData = Output(UInt(64.W))
        val replyErrors = Output(UInt(2.W))
        val replyPages = Output(UInt(2.W))
        val quiescent = Output(Bool())
        val adapterIdle = Output(Bool())
        val lane0 = Output(Valid(UInt(32.W)))
        val lane1 = Output(Valid(UInt(32.W)))
        val errors = Output(UInt(2.W))
        val pages = Output(UInt(2.W))
        val fault0 = Output(UInt(64.W))
        val fault1 = Output(UInt(64.W))
        val flush = Input(Bool())
        val arch0 = Output(Valid(new RawFetchInstruction))
        val arch1 = Output(Valid(new RawFetchInstruction))
        val drain = Input(Bool())
        val occupancy = Output(UInt(3.W))
        val tokenValid = Output(Bool())
        val probePc = Input(UInt(64.W))
        val probeInstruction0 = Input(UInt(32.W))
        val probeInstruction1 = Input(UInt(32.W))
        val probeDenied = Output(UInt(2.W))
        val probeFault0 = Output(UInt(64.W))
        val probeFault1 = Output(UInt(64.W))
        val probeGenericDenied = Output(UInt(2.W))
        val probeGenericFault0 = Output(UInt(64.W))
        val probeGenericFault1 = Output(UInt(64.W))
    })
    val state = WireDefault(0.U.asTypeOf(new PmpState))
    state.cfg(0) := io.pmpCfg0
    state.cfg(1) := io.pmpCfg1
    state.addr(0) := io.pmpAddr0
    state.addr(1) := io.pmpAddr1
    PmpState.decodeRegions(state)
    val frontend = Module(new SynchronousFetch(p.pmpEntries, p.compressedInstructions, p.frontendCacheSets,
        p.renameWidth, stableFaultMetadata = p.stableFetchFaultMetadata, alignedFetchPmp = p.alignedFetchPmp,
        rawFetchPresence = p.rawFetchPresence, parallelFetchTagLookup = p.parallelFetchTagLookup,
        parallelAlignment = p.parallelFetchAlignment, registeredWindow = p.registeredFetchWindow,
        independentPayloadCapture = p.independentFetchPayloadCapture, fetchPreviousPacket = p.fetchPreviousPacket,
        boundedRequestFrontier = p.alignedFetchPermissionStage))
    val adapter = Module(new InstructionTranslationAdapter(p))
    frontend.io.pc := io.pc
    frontend.io.requestFrontier.get := io.pc
    frontend.io.suppressRequest.get := io.suppress
    frontend.io.enable := io.enable
    frontend.io.pause := io.pause
    frontend.io.invalidate := io.invalidate
    frontend.io.virtualized := io.virtualized
    frontend.io.privilege := io.privilege
    frontend.io.pmpState := state
    adapter.io.vmState.satp := io.satp
    adapter.io.vmState.sum := io.sum
    adapter.io.vmState.mxr := io.mxr
    adapter.io.vmState.dataPrivilege := io.privilege
    adapter.io.privilege := io.privilege
    adapter.io.pmpState := state
    adapter.io.virtual.request.valid := frontend.io.memory.request.valid && io.linkReady
    adapter.io.virtual.request.bits := frontend.io.memory.request.bits
    adapter.io.virtual.requestMask := frontend.io.memory.requestMask
    frontend.io.memory.request.ready := adapter.io.virtual.request.ready && io.linkReady
    frontend.io.memory.response <> adapter.io.virtual.response
    frontend.io.memory.responseError := adapter.io.virtual.responseError
    frontend.io.memory.responsePageFault := adapter.io.virtual.responsePageFault
    io.translation <> adapter.io.translation
    io.physical <> adapter.io.physical
    io.fetchValid := frontend.io.memory.request.valid
    io.fetchReady := frontend.io.memory.request.ready
    io.fetchAddress := frontend.io.memory.request.bits
    io.fetchMask := frontend.io.memory.requestMask
    io.replyValid := adapter.io.virtual.response.valid
    io.replyReady := adapter.io.virtual.response.ready
    io.replyData := adapter.io.virtual.response.bits
    io.replyErrors := adapter.io.virtual.responseError
    io.replyPages := adapter.io.virtual.responsePageFault
    io.quiescent := frontend.io.quiescent
    io.adapterIdle := adapter.io.idle
    io.lane0 := frontend.io.instructions(0)
    io.lane1 := frontend.io.instructions(1)
    io.errors := frontend.io.instructionFaults.asUInt
    io.pages := frontend.io.instructionPageFaults.asUInt
    io.fault0 := frontend.io.instructionFaultAddresses(0)
    io.fault1 := frontend.io.instructionFaultAddresses(1)
    // Both optimized/shared and generic parcel implementations see the same
    // independent host oracle. These extra checkers belong only to the fixture.
    for (generic <- Seq(false, true)) {
        val probe = Module(new FetchPacketPermission(p.pmpEntries, 2,
            wordSpan = !generic, balanced = !generic, sharedRelations = !generic))
        probe.io.base := io.probePc
        probe.io.state := state
        probe.io.privilege := io.privilege
        probe.io.virtualized := io.virtualized
        probe.io.instructionLow(0) := io.probeInstruction0(1, 0)
        probe.io.instructionLow(1) := io.probeInstruction1(1, 0)
        if (generic) {
            io.probeGenericDenied := probe.io.denied.asUInt
            io.probeGenericFault0 := probe.io.faultAddresses(0)
            io.probeGenericFault1 := probe.io.faultAddresses(1)
        } else {
            io.probeDenied := probe.io.denied.asUInt
            io.probeFault0 := probe.io.faultAddresses(0)
            io.probeFault1 := probe.io.faultAddresses(1)
        }
    }
    locally {
        // These are the real default52 permission and reservoir modules, with the
        // same connections as IntegerCore's aligned-permission path. No backend.
        val packet = Module(new RegisteredFetchPacket(2, true, BigInt("80000000", 16),
            p.parallelFetchValidation, p.fetchHintEntries, p.splitFetchCursor, p.bankedFetchHints,
            aligned, aligned && p.eagerFetchPrefixSelect))
        val permission = Module(new FetchPacketPermission(p.pmpEntries, 2,
            p.wordSpanPacketPmp, p.balancedPacketPmp, p.sharedFetchPmpRelations))
        frontend.io.pc := packet.io.fetchPc
        frontend.io.requestFrontier.get := packet.io.requestFrontier.map(identity).getOrElse(packet.io.fetchPc)
        frontend.io.suppressRequest.get := packet.io.suppressRequest.map(identity).getOrElse(io.flush) || io.suppress
        permission.io.base := packet.io.fetchPc
        permission.io.state := state
        permission.io.privilege := io.privilege
        permission.io.virtualized := io.virtualized
        packet.io.phaseInput.foreach { phase =>
            phase.denied := permission.io.candidateDenied
            phase.faultOffsets := frontend.io.instructionFaultOffsets
        }
        packet.io.pause := io.pause
        packet.io.consume := VecInit((0 until 2).map(lane => io.drain && packet.io.instructions(lane).valid))
        packet.io.flush.valid := io.flush
        packet.io.flush.bits := io.pc
        packet.io.expectedNext := 0.U.asTypeOf(packet.io.expectedNext)
        packet.io.validation.foreach(_ := 0.U.asTypeOf(packet.io.validation.get))
        packet.io.train := 0.U.asTypeOf(packet.io.train)
        packet.io.invalidate := io.invalidate
        for (lane <- 0 until 2) {
            permission.io.instructionLow(lane) := frontend.io.instructions(lane).bits(1, 0)
            packet.io.supply(lane).valid := frontend.io.instructions(lane).valid
            packet.io.supply(lane).bits := 0.U.asTypeOf(new RawFetchInstruction)
            packet.io.supply(lane).bits.instruction := frontend.io.instructions(lane).bits
            val transportFault = frontend.io.instructionFaults(lane) || frontend.io.instructionPageFaults(lane)
            packet.io.supply(lane).bits.accessFault := frontend.io.instructionFaults(lane) ||
                (if (aligned) false.B else permission.io.denied(lane))
            packet.io.supply(lane).bits.pageFault := frontend.io.instructionPageFaults(lane)
            packet.io.supply(lane).bits.faultAddress := Mux(permission.io.denied(lane) && !transportFault,
                permission.io.faultAddresses(lane), frontend.io.instructionFaultAddresses(lane))
        }
        io.arch0 := packet.io.instructions(0)
        io.arch1 := packet.io.instructions(1)
        io.occupancy := packet.io.occupancy
        io.tokenValid := packet.io.phaseStatus.map(_.tokenValid).getOrElse(false.B)
    }
}

object FetchFaultPrecisionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchFaultPrecisionGsim(!args.contains("--unaligned")),
        Array("--target-dir", args.head))
}
