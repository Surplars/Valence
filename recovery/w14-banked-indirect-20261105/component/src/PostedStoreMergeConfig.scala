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

