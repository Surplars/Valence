package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Production frontend/owners/window with a host-owned ordered memory boundary.
  * The host models old tags and accepted owners; no DUT scheduler tap feeds its oracle.
  * This fixture proves no CPU trap or downstream translation/cache behavior by itself.
  */
class CanonicalFetchFrontendGsim(enabled: Boolean = true) extends Module {
    val io = IO(new Bundle {
        val pc = Input(UInt(64.W))
        val enable = Input(Bool())
        val pause = Input(Bool())
        val invalidate = Input(Bool())
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
    })
    // Low aperture also detects accidental XLEN-wrap authorization. The high
    // aperture distinguishes full addresses with identical low 32 bits.
    val frontend = Module(new SynchronousFetch(pmpEntries = 16, compressed = true,
        cacheSets = 16, fetchWidth = 2, stableFaultMetadata = true, alignedFetchPmp = true,
        rawFetchPresence = true, parallelFetchTagLookup = true, parallelAlignment = true,
        registeredWindow = true, independentPayloadCapture = true, transactionSlots = 2,
        fetchThirdPacketLookahead = enabled, sideEffectFreeFetchRanges = Seq(
            SideEffectFreeFetchRange(0, 4096),
            SideEffectFreeFetchRange(BigInt("80200000", 16), 8192),
            SideEffectFreeFetchRange(BigInt("180200000", 16), 8192)), canonicalFetchCacheKeys = true))
    val reference = Module(new SynchronousFetch(pmpEntries = 16, compressed = true,
        cacheSets = 16, fetchWidth = 2, stableFaultMetadata = true, alignedFetchPmp = true,
        rawFetchPresence = true, parallelFetchTagLookup = true, parallelAlignment = true,
        registeredWindow = true, independentPayloadCapture = true, transactionSlots = 2,
        fetchThirdPacketLookahead = enabled, sideEffectFreeFetchRanges = Seq(
            SideEffectFreeFetchRange(0, 4096),
            SideEffectFreeFetchRange(BigInt("80200000", 16), 8192),
            SideEffectFreeFetchRange(BigInt("180200000", 16), 8192))))
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    PmpState.decodeRegions(pmp)
    frontend.io.pc := io.pc
    frontend.io.enable := io.enable
    frontend.io.pause := io.pause
    frontend.io.invalidate := io.invalidate
    frontend.io.privilege := io.privilege
    frontend.io.virtualized := io.virtualized
    frontend.io.pmpState := pmp
    frontend.io.memory.request.ready := io.requestReady
    frontend.io.memory.response.valid := io.responseValid
    frontend.io.memory.response.bits := io.responseData
    frontend.io.memory.responseError := io.responseErrors
    frontend.io.memory.responsePageFault := io.responsePages
    reference.io.pc := io.pc
    reference.io.enable := io.enable
    reference.io.pause := io.pause
    reference.io.invalidate := io.invalidate
    reference.io.privilege := io.privilege
    reference.io.virtualized := io.virtualized
    reference.io.pmpState := pmp
    reference.io.memory.request.ready := io.requestReady
    reference.io.memory.response.valid := io.responseValid
    reference.io.memory.response.bits := io.responseData
    reference.io.memory.responseError := io.responseErrors
    reference.io.memory.responsePageFault := io.responsePages
    io.requestValid := frontend.io.memory.request.valid
    io.requestAddress := frontend.io.memory.request.bits
    io.requestMask := frontend.io.memory.requestMask
    io.responseReady := frontend.io.memory.response.ready
    io.quiescent := frontend.io.quiescent
    io.lane0 := frontend.io.instructions(0)
    io.lane1 := frontend.io.instructions(1)
    io.errors := frontend.io.instructionFaults.asUInt
    io.pages := frontend.io.instructionPageFaults.asUInt
    io.fault0 := frontend.io.instructionFaultAddresses(0)
    io.fault1 := frontend.io.instructionFaultAddresses(1)
    // Representation-only change: every observable event must remain cycle-identical.
    // The C++ host also maintains an independent full-address/owner oracle.
    when(!reset.asBool) {
        assert(frontend.io.memory.request.valid === reference.io.memory.request.valid)
        when(frontend.io.memory.request.valid) {
            assert(frontend.io.memory.request.bits === reference.io.memory.request.bits)
            assert(frontend.io.memory.requestMask === reference.io.memory.requestMask)
        }
        assert(frontend.io.memory.response.ready === reference.io.memory.response.ready)
        assert(frontend.io.quiescent === reference.io.quiescent)
        for (lane <- 0 until 2) {
            assert(frontend.io.instructions(lane).valid === reference.io.instructions(lane).valid)
            when(frontend.io.instructions(lane).valid) {
                assert(frontend.io.instructions(lane).bits === reference.io.instructions(lane).bits)
                assert(frontend.io.instructionFaults(lane) === reference.io.instructionFaults(lane))
                assert(frontend.io.instructionPageFaults(lane) === reference.io.instructionPageFaults(lane))
                assert(frontend.io.instructionFaultAddresses(lane) === reference.io.instructionFaultAddresses(lane))
                assert(frontend.io.instructionFaultOffsets(lane) === reference.io.instructionFaultOffsets(lane))
            }
        }
    }

}

object CanonicalFetchFrontendGsimMain extends App {
    require(args.length == 2, "output-directory enabled")
    ChiselStage.emitCHIRRTLFile(new CanonicalFetchFrontendGsim(args(1).toBoolean), Array("--target-dir", args.head))
}
