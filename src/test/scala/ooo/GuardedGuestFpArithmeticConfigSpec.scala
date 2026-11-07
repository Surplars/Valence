package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Admission and direct MSU wiring only. The positive full-core fixture is elaborated
  * once by its separately supervised GSIM build, not repeatedly by these Scala checks.
  */
class GuardedGuestFpArithmeticConfigSpec extends AnyFunSuite {
    private val p = GuardedGuestFpArithmeticProfile.params

    test("arithmetic qualification is separate, explicit, fixed and does not change public defaults or ISA advertisement") {
        val default = OooParams()
        assert(!default.guardedGuestFpArithmeticQualification && !default.guardedGuestFpQualification)
        assert(!default.guardedGuestFpEnabled && !default.hypervisorExperiment && !default.fpEnabled)
        assert(!p.guardedGuestFpQualification && p.guardedGuestFpEnabled)
        assert(!default.atomicMemory && !default.basicCounters)
        assert(p.guardedGuestFpArithmeticQualification && p.machineSystem && p.hypervisorExperiment)
        assert(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2 && p.issueWidth == 2)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 && p.memoryEntries == 2)
        assert(p.pmpEntries == 16 && p.virtualMemoryLevels == 3 && p.compressedInstructions)
        assert(p.recoveryWidth == 1 && p.branchPredictorEntries == 64 && p.returnStackEntries == 16)
        assert(p.fpConfig == GuardedGuestFpArithmeticProfile.floatingPoint)
        assert(p.fpConfig.f && p.fpConfig.d && p.fpConfig.signClassMove && p.fpConfig.memory)
        assert(!p.fpConfig.complete && p.fpConfig.addSubtract && !p.fpConfig.multiply && !p.fpConfig.divide)
        assert(!p.fpConfig.squareRoot && !p.fpConfig.fusedMultiplyAdd && !p.fpConfig.compareMinMax)
        assert(!p.fpConfig.conversions && p.fpConfig.resources == FloatingPointResourceConfig.fpga)
        assert(!p.experimentalFloatingPoint && !p.advertiseFloatingPoint && !p.atomicMemory && !p.basicCounters)
        assert(!p.bufferedRamStores && !p.taggedStoreReturns && !p.postedStoreMerge)
        assert(!p.registeredMemoryRequests && p.cpuReturnConfig.isEmpty)
        assert(!p.misaValue.testBit(7) && !p.misaValue.testBit(5) && !p.misaValue.testBit(3))
        assert(p.advertisedIsa == "rv64imc_zicsr_zifencei")
        for (public <- Seq(BoardSocConfig.timingParams(BoardSocConfig.timingProfile),
            BoardSocConfig.boardParams(BoardSocConfig.timingProfile))) {
            assert(!public.guardedGuestFpArithmeticQualification && !public.hypervisorExperiment && !public.fpEnabled)
        }
    }

    test("both genuine constructors reject arbitrary H FP and the exact unselected recipe") {
        val unselected = p.copy(guardedGuestFpArithmeticQualification = false)
        for (forbidden <- Seq(unselected,
            unselected.copy(floatingPoint = FloatingPointConfig.fullF),
            unselected.copy(floatingPoint = FloatingPointConfig.fullFD),
            unselected.copy(floatingPoint = FloatingPointConfig.disabled, experimentalFloatingPoint = true))) {
            val systemError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new MachineSystemUnit(forbidden, experimentalHypervisor = true, guestFiles = 3))
            }
            assert(systemError.getMessage.contains("guest FP state is not yet integrated"))
            val backendError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new IntegerBackend(forbidden, experimentalHypervisor = true, guestFiles = 3))
            }
            assert(backendError.getMessage.contains(
                "experimental H uses owner-carried translated memory without host-only proofs"))
        }
    }

    test("qualification rejects changed privilege, resource, arithmetic and memory contracts") {
        val changes: Seq[() => OooParams] = Seq(
            () => p.copy(guardedGuestFpQualification = true),
            () => GuardedGuestFpCoreProfile.params.copy(guardedGuestFpArithmeticQualification = true),
            () => p.copy(hypervisorExperiment = false),
            () => p.copy(machineSystem = false),
            () => p.copy(virtualMemoryLevels = 4),
            () => p.copy(pmpEntries = 8),
            () => p.copy(compressedInstructions = false),
            () => p.copy(atomicMemory = true, speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 64),
            () => p.copy(basicCounters = true),
            () => p.copy(experimentalFloatingPoint = true),
            () => p.copy(floatingPoint = FloatingPointConfig.disabled, experimentalFloatingPoint = true),
            () => p.copy(floatingPoint = FloatingPointConfig.fullFD),
            () => p.copy(floatingPoint = FloatingPointConfig.fullFD, advertiseFloatingPoint = true),
            () => p.copy(floatingPoint = p.fpConfig.copy(f = false, d = false)),
            () => p.copy(floatingPoint = p.fpConfig.copy(d = false)),
            () => p.copy(floatingPoint = p.fpConfig.copy(signClassMove = false)),
            () => p.copy(floatingPoint = p.fpConfig.copy(memory = false)),
            () => p.copy(floatingPoint = p.fpConfig.copy(addSubtract = false)),
            () => p.copy(floatingPoint = p.fpConfig.copy(multiply = true)),
            () => p.copy(floatingPoint = p.fpConfig.copy(divide = true)),
            () => p.copy(floatingPoint = p.fpConfig.copy(squareRoot = true)),
            () => p.copy(floatingPoint = p.fpConfig.copy(fusedMultiplyAdd = true)),
            () => p.copy(floatingPoint = p.fpConfig.copy(compareMinMax = true)),
            () => p.copy(floatingPoint = p.fpConfig.copy(conversions = true)),
            () => p.copy(floatingPoint = p.fpConfig.copy(resources = FloatingPointResourceConfig.baseline)),
            () => p.copy(floatingPoint = p.fpConfig.copy(resources = FloatingPointResourceConfig.roundOnly)),
            () => p.copy(speculativeRamBytes = 64),
            () => p.copy(speculativeRamBytes = 64, bufferedRamStores = true),
            () => p.copy(speculativeRamBytes = 64, bufferedRamStores = true, registeredMemoryRequests = true,
                taggedStoreReturns = true, registeredStoreResponseOwners = true),
            () => p.copy(speculativeRamBytes = 64, bufferedRamStores = true, postedStoreMerge = true),
            () => p.copy(identityDataRequestFlow = true),
            () => p.copy(precheckedDataRequestFlow = true),
            () => p.copy(physicalLoadIngressFlow = true))
        changes.foreach(change => intercept[IllegalArgumentException](change()))
    }

    test("qualification rejects every changed frozen width and unrelated pipeline experiment") {
        val changes: Seq[() => OooParams] = Seq(
            () => p.copy(renameWidth = 1), () => p.copy(commitWidth = 1), () => p.copy(completionWidth = 1),
            () => p.copy(robEntries = 32), () => p.copy(physicalRegs = 64), () => p.copy(tagBits = 32),
            () => p.copy(memoryEntries = 4), () => p.copy(storeBufferEntries = 2),
            () => p.copy(branchPredictorEntries = 32), () => p.copy(returnStackEntries = 8),
            () => p.copy(instructionCacheSets = 32), () => p.copy(fetchHintEntries = 16),
            () => p.copy(indirectTargetEntries = 16), () => p.copy(recoveryWidth = 2),
            () => p.copy(registeredImsicInterrupts = true), () => p.copy(registeredMemoryAddress = true),
            () => p.copy(registeredRobRetirement = true), () => p.copy(parallelRenameAdmission = true),
            () => p.copy(fastHeadTrapRecovery = true), () => p.copy(fastHeadSystemRecovery = true))
        changes.foreach(change => intercept[IllegalArgumentException](change()))
    }

    test("production top rejects a broadened qualification before any core elaboration") {
        for (make <- Seq[() => HypervisorMachineCore](
            () => new HypervisorMachineCore(guardedGuestFpQualification = true,
                guardedGuestFpArithmeticQualification = true),
            () => new HypervisorMachineCore(platformIntegration = true, guardedGuestFpArithmeticQualification = true),
            () => new HypervisorMachineCore(basicCounters = true, guardedGuestFpArithmeticQualification = true),
            () => new HypervisorMachineCore(ramBytes = 64, guardedGuestFpArithmeticQualification = true),
            () => new HypervisorMachineCore(atomicMemory = true, ramBytes = 64,
                guardedGuestFpArithmeticQualification = true))) {
            intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(make()) }
        }
    }

    test("admitted MSU directly binds dual FS ownership without changing effective memory context") {
        val fir = ChiselStage.emitCHIRRTL {
            val system = new MachineSystemUnit(p, experimentalHypervisor = true, guestFiles = 3)
            assert(system.floatingPoint.get.io.guestContext.isDefined)
            assert(system.hypervisor.get.io.floatingPoint.isDefined)
            system
        }
        val start = fir.indexOf("module MachineSystemUnit :")
        assert(start >= 0)
        val msu = fir.substring(start)
        val lines = msu.linesIterator.map(_.trim).toSeq
        def bound(sink: String, source: String): Boolean =
            lines.exists(line => line == s"connect $sink, $source" || line.startsWith(s"connect $sink, $source "))
        assert(bound("floatingPoint.io.guestContext.virtualized", "hypervisor.io.virtualized"))
        assert(bound("floatingPoint.io.guestContext.fs", "hypervisor.io.floatingPoint.fs"))
        assert(bound("hypervisor.io.floatingPoint.mutation", "floatingPoint.io.mutation") ||
            (bound("hypervisor.io.floatingPoint.mutation.valid", "floatingPoint.io.mutation.valid") &&
                bound("hypervisor.io.floatingPoint.mutation.bits.guest", "floatingPoint.io.mutation.bits.guest")))
        assert(msu.contains("floatingPoint.io.virtualized") && msu.contains("guestDataContext.virtualized"))
        assert(fir.contains("inst fp of FloatingPointState") && fir.contains("pendingGuest"))
        assert(fir.contains(" of FloatingPointMemoryPipeline") && fir.contains(" of FloatingPointMiscS") &&
            fir.contains(" of FloatingPointMiscD"))
        assert(fir.contains(" of FloatingPointSharedArithmetic"))
        assert(!fir.contains(" of FloatingPointDivSqrt"))
    }
}
