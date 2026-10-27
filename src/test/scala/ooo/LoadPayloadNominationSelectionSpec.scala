package ooo

import org.scalatest.funsuite.AnyFunSuite

/** Independent Boolean contract, not a hardware simulation or an authorization oracle.
  * Distinct tokens stand for the complete unmodified raw/registered/legacy bundles.
  * Permission is an unconstrained input: nomination must never make it true.
  */
class LoadPayloadNominationSelectionSpec extends AnyFunSuite {
    test("nomination preserves every valid source selection without granting permission") {
        for (state <- 0 until (1 << 8); rawKind <- 0 until 3; olderKind <- 0 until 4) {
            def bit(n: Int): Boolean = (state & (1 << n)) != 0
            val rawValid = bit(0)
            val oldCredit = bit(1)
            val incoming = bit(2)
            val translated = bit(3)
            val waiting = bit(4)
            val sidecarsAbsent = bit(5)
            // These arbitrary permission bits represent all existing qualifiers,
            // including shape/range/PMP/epoch/context/flush; none feed nomination.
            val ordinaryAllowed = bit(6)
            val certifiedAllowed = bit(7)
            val emptyOpportunity = rawValid && oldCredit && !incoming && !translated && !waiting && sidecarsAbsent
            val ordinaryNominal = emptyOpportunity && rawKind == 0
            val certifiedNominal = emptyOpportunity && rawKind == 1
            val physicalOffer = ordinaryNominal && ordinaryAllowed
            val certifiedOffer = certifiedNominal && certifiedAllowed
            val olderOpportunity = incoming && !translated && !waiting
            val identityOffer = olderOpportunity && olderKind == 0
            val precheckedOffer = olderOpportunity && olderKind == 1
            val hitOffer = olderOpportunity && olderKind == 2
            val checkedValid = translated || identityOffer || precheckedOffer || hitOffer ||
                physicalOffer || certifiedOffer
            val raw = 0x13579
            val registered = 0x24680
            val legacy = 0x5a5a5
            val oldHead = if (certifiedNominal) raw else legacy
            val oldPayload = if (physicalOffer) raw else if (identityOffer) registered else oldHead
            val newPayload = if (ordinaryNominal || certifiedNominal) raw
                else if (identityOffer) registered else legacy
            if (checkedValid) assert(newPayload == oldPayload)
            if (ordinaryNominal && !ordinaryAllowed) assert(!checkedValid)
            if (ordinaryNominal || certifiedNominal) {
                assert(!incoming && !translated && !waiting)
                assert(!identityOffer && !precheckedOffer && !hitOffer)
                assert(!(ordinaryNominal && certifiedNominal))
            }
            // Both downstream credit values retain exactly the same fire/spill
            // partition; current downstream credit is not upstream old credit.
            for (checkedReady <- Seq(false, true)) {
                val directFire = (physicalOffer || certifiedOffer) && checkedReady
                val upstreamFire = rawValid && oldCredit
                val spill = upstreamFire && !directFire
                assert(!directFire || upstreamFire)
                assert(!upstreamFire || (directFire ^ spill))
            }
        }
    }
}
