package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Actual dual-owner ledgers, differing only in completion payload storage.
  * The reference side is supplemental; an independent software ledger/byte
  * oracle remains the authority. Raw invalid output bits are exposed unchanged.
  * No hierarchical writes, synthetic done state or shortened owner tags.
  */
class BankedRobCompletionDataGsim extends Module {
    val baseline = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2.config.coreParams
    val candidate = CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3.config.coreParams
    require(candidate == baseline.copy(bankedRobCompletionData = true))
    require(baseline.completionTopology == "dual-owner" && !baseline.retirementIntent &&
        !baseline.retirementSlotIdentity && baseline.tagBits == 64)
    val io = IO(new Bundle {
        // Reuse only public port shapes, not any old RTL or software oracle.
        val rob = new RobCompletionPayloadPort(baseline)
        val fastHeadRetire = Input(Valid(new BackendCompletion(baseline)))
        val inspectRegister = Input(UInt(5.W))
        val referencePendingException = Output(Valid(new HeadException(baseline)))
        val candidatePendingException = Output(Valid(new HeadException(baseline)))
        val referenceSpeculativeMapping = Output(UInt(baseline.physBits.W))
        val candidateSpeculativeMapping = Output(UInt(baseline.physBits.W))
        val referenceCommittedMapping = Output(UInt(baseline.physBits.W))
        val candidateCommittedMapping = Output(UInt(baseline.physBits.W))
    })

    for ((p, out, enabled) <- Seq((baseline, io.rob.reference, false), (candidate, io.rob.candidate, true))) {
        val ledger = Module(new RenameRob(p))
        require(!ledger.bankedCompletionPayload && ledger.p.bankedRobCompletionData == enabled)
        ledger.io.allocate(0) := io.rob.in.allocate0
        ledger.io.allocate(1) := io.rob.in.allocate1
        ledger.io.rawRequests.foreach { raw =>
            raw(0) := io.rob.in.allocate0.bits
            raw(1) := io.rob.in.allocate1.bits
        }
        ledger.io.rawDestinations.foreach { rd =>
            rd(0) := io.rob.in.allocate0.bits.rd
            rd(1) := io.rob.in.allocate1.bits.rd
        }
        ledger.io.fetchFaultMask.foreach(_ := 0.U)
        ledger.io.complete(0) := io.rob.in.complete0
        ledger.io.complete(1) := io.rob.in.complete1
        ledger.io.retirementIntentValid.foreach { intents =>
            intents(0) := io.rob.in.intent(0)
            intents(1) := io.rob.in.intent(1)
        }
        ledger.io.sameCycleRetire := VecInit((0 until 2).map(io.rob.in.sameCycleRetire(_)))
        ledger.io.sameCycleFault.foreach { faults =>
            faults(0) := io.rob.in.complete0.bits.exception
            faults(1) := io.rob.in.complete1.bits.exception
        }
        // Normally tied invalid by the current CPU; separately exposes the
        // unchanged public ledger bypass for focused component qualification.
        ledger.io.fastHeadRetire := io.fastHeadRetire
        ledger.io.loadOrderRetireLimit.foreach(_ := io.rob.in.loadOrderLimit)
        ledger.io.dispatchReady := io.rob.in.dispatchReady
        ledger.io.commitEnable := io.rob.in.commitEnable
        ledger.io.recover := io.rob.in.external
        ledger.io.recoveryProbe := io.rob.in.external
        ledger.io.parallelRecovery.get.local := io.rob.in.local
        ledger.io.headTrap.get.valid := io.rob.in.headTrap
        ledger.io.headSystem.get.valid := io.rob.in.headSystem
        ledger.io.inspectRegister := io.inspectRegister

        out.renamed0 := ledger.io.renamed(0)
        out.renamed1 := ledger.io.renamed(1)
        out.commit0 := ledger.io.commit(0)
        out.commit1 := ledger.io.commit(1)
        out.completionAccepted0 := ledger.io.completionAccepted(0)
        out.completionAccepted1 := ledger.io.completionAccepted(1)
        out.externalAccepted := ledger.io.recoveryProbeAccepted
        out.externalWins := ledger.io.parallelRecovery.get.externalWins
        out.selected := ledger.io.parallelRecovery.get.selected
        out.killed := ledger.io.parallelRecovery.get.killed
        out.recoveryAccepted := ledger.io.recoveryAccepted
        out.headTrapAccepted := ledger.io.headTrap.get.accepted
        out.headSystemAccepted := ledger.io.headSystem.get.accepted
        out.headSystemToken := ledger.io.headSystem.get.headToken
        out.recovering := ledger.io.recovering
        out.occupancy := ledger.io.occupancy
        out.headValid := ledger.io.headValid
        out.headDone := ledger.io.headDone
        out.headPc := ledger.io.headPc
        out.headException := ledger.io.headException
        out.freeCount := ledger.io.freeCount
        out.tagExhausted := ledger.io.tagExhausted
        if (enabled) {
            io.candidatePendingException := ledger.io.pendingException
            io.candidateSpeculativeMapping := ledger.io.speculativeMapping
            io.candidateCommittedMapping := ledger.io.committedMapping
        } else {
            io.referencePendingException := ledger.io.pendingException
            io.referenceSpeculativeMapping := ledger.io.speculativeMapping
            io.referenceCommittedMapping := ledger.io.committedMapping
        }
    }
}

object BankedRobCompletionDataGsimMain extends App {
    require(args.length == 1, "output-directory")
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    for ((name, profile) <- Seq("reference" -> CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
        "candidate" -> CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3)) {
        _root_.platform.CommonA1CpuRetirementFixture.writeFields(
            out.resolve(s"actual-core-$name.json"), profile.config.coreParams)
    }
    ChiselStage.emitCHIRRTLFile(new BankedRobCompletionDataGsim, Array("--target-dir", args(0)))
}
