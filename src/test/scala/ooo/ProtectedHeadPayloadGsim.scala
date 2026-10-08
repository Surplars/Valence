package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Exact integrated CPU profile with external fixture memory instead of the SoC fabric. */
class ProtectedHeadPayloadGsim(shared: Boolean) extends FloatingPointCpuGsim(
    withMemory = true, bufferedMemory = true, compressed = true, publishGc = true,
    paramsOverride = Some(FpgaNextConfig.Candidate.coreParams.copy(
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096,
        shareProtectedHeadPayload = shared))) {
    override def desiredName: String = "FloatingPointCpuGsim"
    // The external fixture offers no fetch fault and owns no cache prefetch.
    core.io.instructionFaultAddresses.foreach(addresses => addresses.foreach(_ := 0.U))
    core.io.externalPrefetchBusy.foreach(_ := false.B)
    val protectedReset = IO(Output(Bool()))
    val protectedActive = IO(Output(Bool()))
    val protectedHeadValid = IO(Output(Bool()))
    val protectedOwnerTag = IO(Output(UInt(64.W)))
    val protectedOwnerIndex = IO(Output(UInt(4.W)))
    val protectedHeadTag = IO(Output(UInt(64.W)))
    val protectedHeadIndex = IO(Output(UInt(4.W)))
    val protectedCompleteValid = IO(Output(Bool()))
    val protectedCompleteReady = IO(Output(Bool()))
    val protectedCompleteException = IO(Output(Bool()))
    val protectedCompleteTag = IO(Output(UInt(64.W)))
    val protectedCompleteIndex = IO(Output(UInt(4.W)))
    val b = core.core.backend
    protectedReset := reset.asBool
    protectedActive := BoringUtils.bore(b.systemProtected)
    protectedHeadValid := BoringUtils.bore(b.ledger.io.headValid)
    protectedOwnerTag := BoringUtils.bore(b.systemOwner.tag)
    protectedOwnerIndex := BoringUtils.bore(b.systemOwner.index)
    protectedHeadTag := BoringUtils.bore(b.ledger.io.headSystem.get.headToken.tag)
    protectedHeadIndex := BoringUtils.bore(b.ledger.io.headSystem.get.headToken.index)
    protectedCompleteValid := BoringUtils.bore(b.systemComplete.valid)
    protectedCompleteReady := BoringUtils.bore(b.systemComplete.ready)
    protectedCompleteException := BoringUtils.bore(b.systemComplete.bits.exception)
    protectedCompleteTag := BoringUtils.bore(b.systemComplete.bits.token.tag)
    protectedCompleteIndex := BoringUtils.bore(b.systemComplete.bits.token.index)
}
object ProtectedHeadPayloadGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ProtectedHeadPayloadGsim(args.lift(1).contains("shared")),
        Array("--target-dir", args.head))
}
