package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Production frontend/owners/window with a host-owned ordered memory boundary.
  * The host models old tags and accepted owners; no DUT scheduler tap feeds its oracle.
  * This fixture proves no CPU trap or downstream translation/cache behavior by itself.
  */
class IdentityFetchHorizonGsim(enabled: Boolean = true) extends Module {
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
}

object IdentityFetchHorizonGsimMain extends App {
    require(args.length == 2, "output-directory enabled")
    ChiselStage.emitCHIRRTLFile(new IdentityFetchHorizonGsim(args(1).toBoolean), Array("--target-dir", args.head))
}
