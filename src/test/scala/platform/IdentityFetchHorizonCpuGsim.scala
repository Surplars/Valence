package soc.core.ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** One new combined CPU. Existing generated OLD members supply passive host
  * observations; there are no new test ports or production observation wires.
  * OFF remains the exact CertifiedIngressCpuGsim wrapper from sealed 6b223f0.
  */
object IdentityFetchHorizonCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    val control = CommonA1RebuildProfile.FullR1M3CertifiedIngress
    val candidate = CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon
    require(Set(control.name, candidate.name).contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    require(config.fetchThirdPacketLookahead == (args(1) == candidate.name))
    require(config.certifiedLoadIngress && config.fetchTransactionSlots == 2)
    require(config.coreParams.renameWidth == 2 && config.coreParams.robEntries == 16 &&
        config.coreParams.physicalRegs == 48 && config.coreParams.memoryEntries == 4)
    // registered_raw_certified_cpu.cpp::Program::mapped supplies these exact RAM
    // bytes. ROM has a separate window and is intentionally not an eligible range.
    val safeRam = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Identity-only third horizon: one candidate CPU; immutable 6b223f0 runtime control. " +
        "Safe RAM [0x80200000,0x80220000); ROM/VM excluded; two owners/results unchanged. " +
        "Passive OLD generated-member capture; no new production/test IO. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(if (config.fetchThirdPacketLookahead)
        new CertifiedIngressCpuGsim(args(1), safeRam) else new CertifiedIngressCpuGsim(args(1)),
        Array("--target-dir", args(0)))
}
