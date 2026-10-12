package ooo
import chisel3._
class TaggedBoardRequest extends Bundle {
    val valid = Bool(); val ready = Bool(); val handle = UInt(3.W)
    val address = UInt(64.W); val data = UInt(64.W); val write = Bool(); val size = UInt(2.W); val ordinary = Bool()
}
class TaggedBoardResponse extends Bundle {
    val valid = Bool(); val ready = Bool(); val handle = UInt(3.W); val data = UInt(64.W); val flags = UInt(2.W)
}
class TaggedBoardSlot extends Bundle {
    val live = Bool(); val index = UInt(4.W); val tag = UInt(64.W); val cancel = Bool(); val discard = Bool()
    val complete = Bool(); val fastLoad = Bool(); val completeIndex = UInt(4.W); val completeTag = UInt(64.W)
    val tval = UInt(64.W); val exception = Bool(); val cause = UInt(64.W)
}
/** Optional ON-only passive scalar outputs. No control/credit path or storage is added. */
class TaggedBoardTrace extends Bundle {
    val startValid = Bool(); val startSlot = UInt(2.W); val startVa = UInt(64.W); val startPa = UInt(64.W)
    val startData = UInt(64.W); val startSize = UInt(2.W); val startFlags = UInt(5.W)
    val queued = new TaggedBoardRequest; val physical = new TaggedBoardRequest; val physicalReply = new TaggedBoardResponse
    val integerReply = new TaggedBoardResponse; val sbRequest = new TaggedBoardRequest; val sbReply = new TaggedBoardResponse
    val sbEnqueue = Bool(); val sbFast = Bool(); val sbSlot = UInt(1.W); val sbOriginHandle = UInt(3.W)
    val sbAddress = UInt(64.W); val sbData = UInt(64.W); val sbSize = UInt(2.W)
    val sbLocal = Bool(); val sbLocalWrite = Bool(); val sbDrainReply = Bool(); val fpEpoch = Bool()
    val fpIndex = UInt(4.W); val fpTag = UInt(64.W)
    val backendRequest = new TaggedBoardRequest; val backendReply = new TaggedBoardResponse
    val fpComplete = Bool(); val fpCompleteIndex = UInt(4.W); val fpCompleteTag = UInt(64.W)
    val fpTval = UInt(64.W); val fpException = Bool(); val fpCause = UInt(64.W)
    val slot0 = new TaggedBoardSlot; val slot1 = new TaggedBoardSlot; val slot2 = new TaggedBoardSlot; val slot3 = new TaggedBoardSlot
    def slots: Seq[TaggedBoardSlot] = Seq(slot0, slot1, slot2, slot3)
    val cache = new TaggedBoardRequest; val cacheReply = new TaggedBoardResponse
    val cacheHandle0 = UInt(3.W); val cacheHandle1 = UInt(3.W); val cacheKind0 = UInt(2.W); val cacheKind1 = UInt(2.W)
    val cacheSelected = UInt(1.W); val cacheOldestHit = Bool(); val cacheStoreWrite = Bool(); val cachePostedIntent = Bool()
}
