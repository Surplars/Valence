package soc.core.ooo

import chisel3._
import chisel3.util._

/** New reconstruction contract. No existing profile enables or instantiates it. */
case class PostedStoreMergeConfig(
    enabled: Boolean = false,
    tokenTagBits: Int = 64,
    tokenIndexBits: Int = 4,
    generationBits: Int = 64,
    epochBits: Int = 32,
    lineEntries: Int = 2,
    storeEntries: Int = 16,
    cacheSets: Int = 256,
    cacheWays: Int = 2,
    readMshrs: Int = 2,
    responseEntries: Int = 2,
    writebackEntries: Int = 2,
    guaranteedBase: BigInt = 0,
    guaranteedBytes: BigInt = 0
) {
    require(tokenTagBits >= 8 && tokenTagBits <= 64 && tokenIndexBits >= 1 && tokenIndexBits <= 8)
    require(generationBits >= 2 && generationBits <= 64 && epochBits >= 1 && epochBits <= 64)
    require(lineEntries == 2 && storeEntries == 16, "first owner checkpoint is two lines and sixteen tokens")
    require(isPow2(cacheSets) && cacheSets >= 2 && cacheSets <= 512 && Set(1, 2).contains(cacheWays))
    require(Set(1, 2, 4).contains(readMshrs) && Set(1, 2, 4).contains(writebackEntries))
    require(isPow2(responseEntries) && responseEntries >= 2 && responseEntries <= 16)
    require(guaranteedBase >= 0 && guaranteedBytes >= 0 && guaranteedBase + guaranteedBytes <= (BigInt(1) << 64))
    require(!enabled || (readMshrs == 2 && cacheSets >= readMshrs && responseEntries >= readMshrs),
        "initial posted merge uses exactly the original two cache MSHRs")
    require(!enabled || (guaranteedBytes > 0 && guaranteedBase % 64 == 0 && guaranteedBytes % 64 == 0),
        "posted merge requires an explicit full-line successful physical RAM aperture")
    val lineBits: Int = log2Ceil(lineEntries)
    val storeBits: Int = log2Ceil(storeEntries)
    val countBits: Int = log2Ceil(storeEntries + 1)
    val setBits: Int = log2Ceil(cacheSets)
    val mshrBits: Int = math.max(1, log2Ceil(readMshrs))
    val responseBits: Int = log2Ceil(responseEntries)
    val writebackBits: Int = math.max(1, log2Ceil(writebackEntries))

    /** The real cache assembly must call this with its own aperture, not a CPU PA hint. */
    def requireCacheAperture(cacheBase: BigInt, cacheBytes: BigInt): Unit = {
        require(cacheBase >= 0 && cacheBytes > 0 && cacheBase + cacheBytes <= (BigInt(1) << 64))
        require(!enabled || (guaranteedBase >= cacheBase &&
            guaranteedBase + guaranteedBytes <= cacheBase + cacheBytes),
            "successful posted RAM aperture must be wholly inside the actual private cache aperture")
    }
}

class PostedStoreToken(c: PostedStoreMergeConfig) extends Bundle {
    val index = UInt(c.tokenIndexBits.W)
    val tag = UInt(c.tokenTagBits.W)
}

class PostedLineOwner(c: PostedStoreMergeConfig) extends Bundle {
    val slot = UInt(c.lineBits.W)
    val generation = UInt(c.generationBits.W)
}

/** Cohort root is retained after that first owner retires. Epoch alone is not a cohort. */
class PostedLineContext(c: PostedStoreMergeConfig) extends Bundle {
    val owner = new PostedLineOwner(c)
    val cohortRoot = new PostedLineOwner(c)
    val epoch = UInt(c.epochBits.W)
    val lineAddress = UInt(64.W)
}

class PostedCacheReservation(c: PostedStoreMergeConfig) extends Bundle {
    val mshr = UInt(c.mshrBits.W)
    val set = UInt(c.setBits.W)
    val way = UInt(1.W)
    val victimValid = Bool()
    val victimDirty = Bool()
    val victimAddress = UInt(64.W)
}

/** CPU-only proof of an already irrevocable legacy StoreBuffer transfer.
  * Both ordinary physical head stores and fast head transfers may produce it.
  * Identity translation, a PA, or a test fixture cannot create this authority.
  */
class PostedStoreProof(c: PostedStoreMergeConfig) extends Bundle {
    val token = new PostedStoreToken(c)
    val epoch = UInt(c.epochBits.W)
    val address = UInt(64.W)
    val data = UInt(64.W)
    val mask = UInt(8.W)
    val size = UInt(2.W)
    val headAuthorized = Bool()
    val physicalPmpAllowed = Bool()
    val originalPhysical = Bool()
    val integerOrigin = Bool()
    val legacyPostedAccepted = Bool()
    val finalChecked = Bool()
}

class PostedStoreOffer(c: PostedStoreMergeConfig) extends Bundle {
    val request = new DataRequest
    val proof = new PostedStoreProof(c)
}

/** Acceptance-time resource decision; never part of a held upstream offer. */
class PostedStoreAdmission(c: PostedStoreMergeConfig) extends Bundle {
    val responseAvailable = Bool()
    val targetAbsent = Bool() // Actual N/absent-line miss; resident hits/upgrades retain the legacy path.
    val reservationValid = Bool()
    val reservation = new PostedCacheReservation(c)
    val responseTicket = UInt(c.responseBits.W)
}

class PostedStoreMember(c: PostedStoreMergeConfig) extends Bundle {
    val token = new PostedStoreToken(c)
    val context = new PostedLineContext(c)
    val responseTicket = UInt(c.responseBits.W)
}

class PostedFallbackAcknowledgement(c: PostedStoreMergeConfig) extends Bundle {
    val token = new PostedStoreToken(c)
    val responseTicket = UInt(c.responseBits.W)
}

class PostedStoreAcceptance(c: PostedStoreMergeConfig) extends Bundle {
    val member = new PostedStoreMember(c)
    val reservation = new PostedCacheReservation(c)
    val newLine = Bool()
}

class PostedLineEvent(c: PostedStoreMergeConfig) extends Bundle {
    val context = new PostedLineContext(c)
    val reservation = new PostedCacheReservation(c)
}

class PostedLineRefill(c: PostedStoreMergeConfig) extends PostedLineEvent(c) {
    val data = UInt(512.W)
    val error = Bool()
    val toT = Bool()
    val hasData = Bool()
    val grantAcked = Bool()
}

class PostedLineInstall(c: PostedStoreMergeConfig) extends PostedLineEvent(c) {
    val data = UInt(512.W)
}

/** At most one voluntary victim release per full posted owner. No slot-only completion. */
class PostedWritebackTicket(c: PostedStoreMergeConfig) extends Bundle {
    val slot = UInt(c.writebackBits.W)
    val owner = new PostedLineOwner(c)
}

class PostedWritebackEvent(c: PostedStoreMergeConfig) extends PostedLineEvent(c) {
    val ticket = new PostedWritebackTicket(c)
}
