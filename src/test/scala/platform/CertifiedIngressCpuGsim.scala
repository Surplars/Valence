package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** Passive final-port observations; no production interface or new authority. */
class CertifiedIngressCpuGsim(profile: String, sideEffectFreeFetchRanges: Seq[SideEffectFreeFetchRange] = Seq.empty) extends RegisteredRawCertifiedCpuGsim(profile, sideEffectFreeFetchRanges) {
    override def desiredName: String = "CommonA1VmPipelineGsim"
    require(CommonA1RebuildProfile.named(profile).config.certifiedLoadIngress)
    val certified = IO(new Bundle {
        val upstreamFire = Output(Bool())
        val upstream = Output(new DataRequest)
        val nominal = Output(Bool())
        val pass = Output(Bool())
        val ingressCount = Output(UInt(2.W))
        val checkedPush = Output(Bool())
        val checkedRequest = Output(new DataRequest)
        val checkedFault = Output(Bool())
        val checkedCount = Output(UInt(2.W))
        val fpEpoch = Output(Bool())
    })
    private def tap[T <: Data](value: T): T = BoringUtils.bore(value)
    certified.upstreamFire := tap(adapter.io.virtual.request.valid) && tap(adapter.io.virtual.request.ready)
    certified.upstream := tap(adapter.io.virtual.request.bits)
    certified.nominal := tap(adapter.certifiedIngressNominal)
    certified.pass := tap(adapter.certifiedIngressPass)
    certified.ingressCount := tap(adapter.virtualRequests.get.io.count)
    certified.checkedPush := tap(adapter.checked.get.enq.valid) && tap(adapter.checked.get.enq.ready)
    certified.checkedRequest := tap(adapter.checked.get.enq.bits.request)
    certified.checkedFault := tap(adapter.checked.get.enq.bits.fault)
    certified.checkedCount := tap(adapter.checked.get.count)
    certified.fpEpoch := tap(tile.core.core.core.backend.fpMemoryEpoch)
}

/** Exactly one fresh candidate CPU; OFF is exported only for saved-control graph equivalence. */
object CertifiedIngressCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val control = CommonA1RebuildProfile.FullR1M3AdvisoryOwner
    val candidate = CommonA1RebuildProfile.FullR1M3CertifiedIngress
    require(Set(control.name, candidate.name).contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    require(config.certifiedLoadIngress == (args(1) == candidate.name))
    require(config.registeredAdvisoryExclusion && config.orderedLsuResponseReady && config.bufferedReturnFlow)
    require(!config.physicalLoadIngressFlow && !config.registeredDataTranslation)
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Certified ingress: one candidate CPU; immutable d5805c6 runtime control. " +
        "No capacity change or new production port. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(if (config.certifiedLoadIngress) new CertifiedIngressCpuGsim(args(1))
        else new RegisteredRawCertifiedCpuGsim(args(1)), Array("--target-dir", args(0)))
}
