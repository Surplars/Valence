package ooo
import soc.core.ooo._
/** Constructor-only current-source audit, without DUT ports/state/taps. */
object RetirementIntentActualAudit {
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        HeadDrainActualAudit.requireShape(expected)
        val core = platform.core.core.core
        val b = core.backend
        require(core.p == expected.coreParams && b.p == core.p)
        require(b.p.retirementIntent == expected.retirementIntent)
        val offers = b.executionRetirementOffer
        val port = b.ledger.io.retirementIntentValid
        require(offers.nonEmpty == expected.retirementIntent && port.nonEmpty == expected.retirementIntent)
        require(offers.forall(v => v.size == 2 && v.getWidth == 2) &&
            port.forall(v => v.size == 2 && v.getWidth == 2))
        require(!expected.retirementIntent || (b.p.registeredIssueExecute && b.p.parallelCompletionPayload &&
            b.p.tagBits == 64 && b.executionStages.size == 2))
        Map("schema" -> "actual-retirement-intent-v1", "retirementIntent" -> b.p.retirementIntent,
            "rawOfferPresent" -> offers.nonEmpty, "rawOfferBits" -> offers.map(_.getWidth).getOrElse(0),
            "ledgerIntentPresent" -> port.nonEmpty, "ledgerIntentBits" -> port.map(_.getWidth).getOrElse(0),
            "registeredExecutionLanes" -> b.executionStages.size, "tagBits" -> b.p.tagBits,
            "predecodedHeadDrain" -> b.p.predecodedHeadDrain,
            "headDrainClassesPresent" -> b.headDrainClasses.nonEmpty,
            "coreFields" -> b.p.productArity, "profileFields" -> expected.productArity)
    }
}
