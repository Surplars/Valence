package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Small real frontend/adapter fixture. The optional reservoir is only for the independent ISA regression. */
class FetchAddressStageGsim(staged: Boolean, architectural: Boolean = false) extends Module {
    private val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(p => Files.isRegularFile(p.resolve("build.mill"))).get
    private val profile = Files.readString(root.resolve("fpga/next/timing-batch-owner-row-profile.json"))
    private val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(profile).get.group(1)
    private val options = "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSet
    require(options.size == 52)
    val p = FpgaNextConfig.fromOptions(options, defaultSelected = false).coreParams
        .copy(fetchAddressBeforePmp = staged)
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
        boundedRequestFrontier = p.alignedFetchPermissionStage, fetchAddressBeforePmp = staged))
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
    io.arch0 := 0.U.asTypeOf(io.arch0)
    if (architectural) {
        // These are the real default52 permission and reservoir modules, with the
        // same connections as IntegerCore's aligned-permission path. No backend.
        val packet = Module(new RegisteredFetchPacket(2, true, BigInt("80000000", 16),
            p.parallelFetchValidation, p.fetchHintEntries, p.splitFetchCursor, p.bankedFetchHints,
            p.alignedFetchPermissionStage, p.eagerFetchPrefixSelect))
        val permission = Module(new FetchPacketPermission(p.pmpEntries, 2,
            p.wordSpanPacketPmp, p.balancedPacketPmp, p.sharedFetchPmpRelations))
        frontend.io.pc := packet.io.fetchPc
        frontend.io.requestFrontier.get := packet.io.requestFrontier.get
        frontend.io.suppressRequest.get := packet.io.suppressRequest.get || io.suppress
        permission.io.base := packet.io.fetchPc
        permission.io.state := state
        permission.io.privilege := io.privilege
        permission.io.virtualized := io.virtualized
        packet.io.phaseInput.get.denied := permission.io.candidateDenied
        packet.io.phaseInput.get.faultOffsets := frontend.io.instructionFaultOffsets
        packet.io.pause := io.pause
        packet.io.consume := VecInit(Seq.fill(2)(false.B))
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
            packet.io.supply(lane).bits.accessFault := frontend.io.instructionFaults(lane)
            packet.io.supply(lane).bits.pageFault := frontend.io.instructionPageFaults(lane)
        }
        io.arch0 := packet.io.instructions(0)
    }
}

object FetchAddressStageGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchAddressStageGsim(args.contains("--staged"),
        args.contains("--architectural")), Array("--target-dir", args.head))
}
