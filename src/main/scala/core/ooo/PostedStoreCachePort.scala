package soc.core.ooo

import chisel3._
import chisel3.util._

/** Optional production cache boundary. The enclosing cache constructor validates
  * the enabled config against its actual aperture and physical capacities.
  * requestProof is a sidecar to the unchanged upstream DataRequest: its valid
  * says authority is present, not that a second transaction is being offered.
  * All request/proof transport uses upstream.request.fire exclusively.
  */
class PostedStoreCachePort(c: PostedStoreMergeConfig) extends Bundle {
    val requestProof = Input(Valid(new PostedStoreProof(c)))
    val contextEpoch = Input(UInt(c.epochBits.W))
    // Stop extending runs while allowing every accepted obligation to drain.
    val seal = Input(Bool())
    // An external aggregate-drain event, never inferred from local line count.
    val endEpisode = Input(Bool())
    // Accepted cache-owner/fallback/WB responsibility; episodeActive is separate.
    val busy = Output(Bool())
    val episodeActive = Output(Bool())
}

/** Passive wrapper-only lineage observation, with no production IO or storage. */
class PostedStoreCacheObservation(c: PostedStoreMergeConfig) extends Bundle {
    val accepted = Valid(new PostedStoreAcceptance(c))
    val acknowledged = Valid(new PostedStoreMember(c))
    val acquired = Valid(new PostedLineEvent(c))
    val refillValid = Bool()
    val refillEvent = new PostedLineEvent(c)
    val refillData = UInt(512.W)
    val refillError = Bool()
    val installed = Valid(new PostedLineInstall(c))
    val drained = Valid(new PostedStoreMember(c))
    val released = Valid(new PostedLineEvent(c))
    val attached = Valid(new PostedWritebackEvent(c))
    val sent = Valid(new PostedWritebackEvent(c))
    val completed = Valid(new PostedWritebackEvent(c))
    val cancelled = Valid(new PostedLineEvent(c))
    val fallback = Valid(new PostedFallbackAcknowledgement(c))
    val fallbackAck = Valid(new PostedFallbackAcknowledgement(c))
    val failed = Bool()
    val mshrMask = UInt(c.readMshrs.W)
    val postedMask = UInt(c.readMshrs.W)
    val responseMask = UInt(c.responseEntries.W)
    val responseCompleteMask = UInt(c.responseEntries.W)
    val wbMask = UInt(c.writebackEntries.W)
}

class CacheLineWriteObservation extends Bundle {
    val valid = Bool()
    val posted = Bool()
    val address = UInt(64.W)
    val data = UInt(512.W)
}
