package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Structural/elaboration checks only; cycle-level ownership qualification uses GSIM. */
class RegisteredRequestQueueConfigSpec extends AnyFunSuite {
    private def params(posted: Boolean, canonical: Boolean, frozen: Boolean, tagged: Boolean): OooParams =
        PendingStoreProofFixture.params(enabled = false).copy(
            postedStoreMerge = posted, canonicalVirtualStoreOverlap = canonical,
            frozenStoreProofTransport = frozen, taggedStoreReturns = tagged,
            registeredStoreResponseOwners = tagged)

    test("one typed FIFO owns every legal optional sidecar combination, including posted off canonical on") {
        for {
            posted <- Seq(false, true)
            canonical <- Seq(false, true)
            frozen <- Seq(false, true) if !frozen || canonical
            tagged <- Seq(false, true)
        } {
            val p = params(posted, canonical, frozen, tagged)
            assert(p.memoryEntries == 4)
            val rtl = ChiselStage.emitCHIRRTL {
                val dut = new RegisteredRequestQueue(p)
                val entry = dut.entries.io.enq.bits
                assert(entry.postedProof.nonEmpty == posted)
                assert(entry.canonicalStoreOrigin.nonEmpty == canonical)
                assert(entry.frozenStoreProof.nonEmpty == frozen)
                assert(entry.request.returnHandle.nonEmpty == tagged)
                if (tagged) assert(entry.request.returnHandle.get.getWidth == p.dataReturnHandleBits)
                if (posted) {
                    assert(entry.postedProof.get.bits.getWidth == dut.proofIn.get.bits.getWidth)
                }
                if (canonical) {
                    assert(entry.canonicalStoreOrigin.get.bits.token.tag.getWidth == p.tagBits)
                    assert(entry.canonicalStoreOrigin.get.bits.epoch.getWidth == 32)
                }
                if (frozen) {
                    assert(entry.frozenStoreProof.get.bits.address.getWidth == 64)
                    assert(entry.frozenStoreProof.get.bits.physicalAddress.getWidth == 64)
                }
                dut
            }
            assert(rtl.linesIterator.count(_.trim.startsWith("inst entries of ")) == 1)
            assert(rtl.contains("canonicalOriginIn :") == canonical)
            assert(rtl.contains("frozenProofIn :") == frozen)
            assert(rtl.contains("proofIn :") == posted)
            assert(!rtl.contains("input flush :"), "accepted request ownership must not be cancelled by a flush")
        }
    }
}
