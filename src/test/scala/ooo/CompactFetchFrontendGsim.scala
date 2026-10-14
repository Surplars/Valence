package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Full frontend cycle pairing, including offers while stalled and all valid architectural payloads.
  * The C++ fixture independently predicts every handshake and valid instruction from full64 addresses.
  */
class CompactFetchFrontendGsim(sets: Int = 16, window: Boolean = true, staged: Boolean = true) extends Module {
    val io = IO(new Bundle {
        val pc = Input(UInt(64.W))
        val requestFrontier = Input(UInt(64.W))
        val suppressRequest = Input(Bool())
        val enable = Input(Bool())
        val invalidate = Input(Bool())
        val pause = Input(Bool())
        val privilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
        val pmpCfg0 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val requestReady = Input(Bool())
        val requestValid = Output(Bool())
        val requestAddress = Output(UInt(64.W))
        val requestMask = Output(UInt(2.W))
        val responseValid = Input(Bool())
        val responseData = Input(UInt(64.W))
        val responseErrors = Input(UInt(2.W))
        val responsePages = Input(UInt(2.W))
        val responseReady = Output(Bool())
        val quiescent = Output(Bool())
        val lane0 = Output(Valid(UInt(32.W)))
        val lane1 = Output(Valid(UInt(32.W)))
        val errors = Output(UInt(2.W))
        val pages = Output(UInt(2.W))
        val fault0 = Output(UInt(64.W))
        val fault1 = Output(UInt(64.W))
        val faultOffset0 = Output(UInt(5.W))
        val faultOffset1 = Output(UInt(5.W))
    })
    val candidate = Module(new SynchronousFetch(pmpEntries = 16, compressed = true,
        cacheSets = sets, fetchWidth = 2, stableFaultMetadata = true, alignedFetchPmp = true,
        rawFetchPresence = true, parallelFetchTagLookup = true, parallelAlignment = true,
        registeredWindow = window, independentPayloadCapture = true, fetchPreviousPacket = window,
        boundedRequestFrontier = staged, fetchAddressBeforePmp = staged, compactCacheKeys = true))
    val reference = Module(new FrozenSynchronousFetchBeforeCompactKeys(pmpEntries = 16, compressed = true,
        cacheSets = sets, fetchWidth = 2, stableFaultMetadata = true, alignedFetchPmp = true,
        rawFetchPresence = true, parallelFetchTagLookup = true, parallelAlignment = true,
        registeredWindow = window, independentPayloadCapture = true, fetchPreviousPacket = window,
        boundedRequestFrontier = staged, fetchAddressBeforePmp = staged))
    if (staged) {
        candidate.io.requestFrontier.get := io.requestFrontier
        candidate.io.suppressRequest.get := io.suppressRequest
        reference.io.requestFrontier.get := io.requestFrontier
        reference.io.suppressRequest.get := io.suppressRequest
    }
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    PmpState.decodeRegions(pmp)
    candidate.io.pc := io.pc
    candidate.io.enable := io.enable
    candidate.io.invalidate := io.invalidate
    candidate.io.pause := io.pause
    candidate.io.privilege := io.privilege
    candidate.io.virtualized := io.virtualized
    candidate.io.pmpState := pmp
    candidate.io.memory.request.ready := io.requestReady
    candidate.io.memory.response.valid := io.responseValid
    candidate.io.memory.response.bits := io.responseData
    candidate.io.memory.responseError := io.responseErrors
    candidate.io.memory.responsePageFault := io.responsePages
    reference.io.pc := io.pc
    reference.io.enable := io.enable
    reference.io.invalidate := io.invalidate
    reference.io.pause := io.pause
    reference.io.privilege := io.privilege
    reference.io.virtualized := io.virtualized
    reference.io.pmpState := pmp
    reference.io.memory.request.ready := io.requestReady
    reference.io.memory.response.valid := io.responseValid
    reference.io.memory.response.bits := io.responseData
    reference.io.memory.responseError := io.responseErrors
    reference.io.memory.responsePageFault := io.responsePages
    io.requestValid := candidate.io.memory.request.valid
    io.requestAddress := candidate.io.memory.request.bits
    io.requestMask := candidate.io.memory.requestMask
    io.responseReady := candidate.io.memory.response.ready
    io.quiescent := candidate.io.quiescent
    io.lane0 := candidate.io.instructions(0)
    io.lane1 := candidate.io.instructions(1)
    io.errors := candidate.io.instructionFaults.asUInt
    io.pages := candidate.io.instructionPageFaults.asUInt
    io.fault0 := candidate.io.instructionFaultAddresses(0)
    io.fault1 := candidate.io.instructionFaultAddresses(1)
    io.faultOffset0 := candidate.io.instructionFaultOffsets(0)
    io.faultOffset1 := candidate.io.instructionFaultOffsets(1)
    when(!reset.asBool) {
        assert(candidate.io.memory.request.valid === reference.io.memory.request.valid &&
            candidate.io.memory.response.ready === reference.io.memory.response.ready &&
            candidate.io.quiescent === reference.io.quiescent,
            "compact fetch keys paired handshake mismatch")
        when(candidate.io.memory.request.valid) {
            assert(candidate.io.memory.request.bits === reference.io.memory.request.bits &&
                candidate.io.memory.requestMask === reference.io.memory.requestMask,
                "compact fetch keys paired offered request mismatch")
        }
        for (lane <- 0 until 2) {
            assert(candidate.io.instructions(lane).valid === reference.io.instructions(lane).valid,
                "compact fetch keys paired instruction validity mismatch")
            when(candidate.io.instructions(lane).valid) {
                assert(candidate.io.instructions(lane).bits === reference.io.instructions(lane).bits &&
                    candidate.io.instructionFaults(lane) === reference.io.instructionFaults(lane) &&
                    candidate.io.instructionPageFaults(lane) === reference.io.instructionPageFaults(lane) &&
                    candidate.io.instructionFaultAddresses(lane) === reference.io.instructionFaultAddresses(lane) &&
                    candidate.io.instructionFaultOffsets(lane) === reference.io.instructionFaultOffsets(lane),
                    "compact fetch keys paired valid instruction payload mismatch")
            }
        }
    }
}

object CompactFetchFrontendGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CompactFetchFrontendGsim(args.lift(1).map(_.toInt).getOrElse(16),
        !args.contains("no-window"), !args.contains("no-window") && !args.contains("unstaged")), Array("--target-dir", args.head))
}
