package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RetirementSlotSpec extends AnyFunSuite {
    test("the unified flag is the only complete-product difference from exact actual59") {
        val off = RetirementSlotTestProfile.off
        val on = RetirementSlotTestProfile.on
        RetirementSlotProfile.requirePair(off, on)
        assert(off.productArity == 175 && off.retirementIntent && off.predecodedHeadDrain)
        assert(RetirementSlotProfile.original164(off).size == 164)
        assert(PlacedTimingProfile.candidateOptions.size == 59)
        val defaults = OooParams()
        val values = defaults.productElementNames.zip(defaults.productIterator).toMap
        assert(RetirementSlotProfile.addedCoreNames.forall(name => values(name) == false))
    }
    test("historical projection rejects every named enabled addition") {
        val p = RetirementSlotTestProfile.off
        for (changed <- Seq(p.copy(memoryPreparationHeadMask = true), p.copy(directRank0MemorySourceIds = true),
            p.copy(fetchReadyDataClear = true), p.copy(retirementSlotIdentity = true),
            p.copy(fetchAcceptedPrefixValidation = true), p.copy(alignedFetchSinglePage = true),
            p.copy(factorCheckedNextAllowed = true), p.copy(localTaggedResponseReady = true))) {
            intercept[IllegalArgumentException] { RetirementSlotProfile.original164(changed) }
        }
    }
    test("actual ROB and backend constructors reject flag divergence") {
        val off = RetirementSlotTestProfile.off
        val on = RetirementSlotTestProfile.on
        for ((p, wrong) <- Seq(off -> true, on -> false)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new RenameRob(p, retirementSlotIdentity = wrong))
            }
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new IntegerBackend(p,
                    registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent, retirementSlotIdentity = wrong))
            }
        }
    }
    test("the unified flag rejects unsupported retirement topology") {
        intercept[IllegalArgumentException] {
            RetirementSlotTestProfile.off.copy(retirementIntent = false, retirementSlotIdentity = true)
        }
        intercept[IllegalArgumentException] { OooParams(retirementSlotIdentity = true) }
    }
}
