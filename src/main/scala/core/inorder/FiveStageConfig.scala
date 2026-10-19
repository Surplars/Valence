package soc.core.inorder

/** Orbital-I1: a strictly in-order, single-issue FPGA core, not a legacy adapter.
  * Only implemented ISA switches appear here; unimplemented extensions must not be advertised.
  */
case class FiveStageConfig(
    xlen: Int = 64,
    withM: Boolean = true,
    multiplyMode: String = "dsp",
    memoryBypass: Boolean = true,
    resetVector: BigInt = BigInt("80000000", 16),
    trapVector: BigInt = BigInt("80000100", 16),
    hartId: Int = 0,
    registerFileStorage: String = "block",
    instructionCacheBytes: Int = 0,
    dataCacheBytes: Int = 0,
    cacheLineBytes: Int = 64,
    branchPredictorEntries: Int = 0,
    cacheableBase: BigInt = BigInt("80000000", 16),
    cacheableBytes: BigInt = BigInt("10000000", 16),
    earlyMemoryIssue: Boolean = false,
    overlapWriteLookup: Boolean = false,
    withUser: Boolean = false,
    withSupervisor: Boolean = false,
    withSv39: Boolean = false,
    pmpEntries: Int = 0,
    physicalAddressBits: Int = 0,
    tlbEntries: Int = 4,
    fastInstructionTranslation: Boolean = true,
    withC: Boolean = false,
    withA: Boolean = false,
    pipelineProfile: String = "compact5",
    withF: Boolean = false,
    withD: Boolean = false,
    fpgaTimingCuts: Boolean = false,
    fastDataTranslation: Boolean = false,
    overlapDataRetirement: Boolean = false,
    readOnlyDataRetirement: Boolean = false,
    coherentCaches: Boolean = false,
    coherentCacheWays: Int = 1,
    coherentControlCuts: Boolean = false,
    coherentBandwidth: Boolean = false,
    coherentWholeLine: Boolean = false,
    directFastDataIssue: Boolean = false,
    cacheFetchPredecode: Boolean = false,
    indexedDataProofs: Boolean = false,
    coherentLineGrants: Boolean = false,
    coherentMissTurnover: Boolean = false,
    coherentWritebackOverlap: Boolean = false,
    coherentReadOverlap: Boolean = false,
    dataReplyHandoff: Boolean = false,
    bankedTlbProofs: Boolean = false,
    withAia: Boolean = false,
    externalFenceICompletion: Boolean = false
) {
    require(Set(32, 64).contains(xlen), "XLEN must be 32 or 64")
    require(Set(1, 2).contains(coherentCacheWays))
    require(!coherentControlCuts || (coherentCaches && fpgaTimingCuts),
        "coherent control cuts require explicit coherent FPGA timing mode")
    require(!coherentBandwidth || coherentControlCuts,
        "coherent bandwidth handoff requires the explicit coherent control timing mode")
    require(!coherentWholeLine || coherentBandwidth,
        "whole-line coherent return requires the qualified bounded bandwidth/timing profile")
    require(!coherentLineGrants || coherentWholeLine,
        "private whole-line grants require the explicit whole-line backing return profile")
    require(!coherentMissTurnover || (coherentBandwidth && coherentCacheWays == 2),
        "miss-response turnover requires ordered two-way coherent bandwidth admission")
    require(!coherentWritebackOverlap || coherentLineGrants,
        "bounded writeback/refill overlap requires independent private whole-line grants")
    require(!coherentReadOverlap || coherentWritebackOverlap,
        "paired reads reuse the qualified release context and private whole-line transport")
    require(!dataReplyHandoff || (directFastDataIssue && overlapDataRetirement),
        "read handoff requires fast proven scalar issue and registered data retirement")
    require(!coherentCaches || (xlen == 64 && cacheLineBytes == 64 &&
        instructionCacheBytes >= 128 && instructionCacheBytes <= 32768 &&
        instructionCacheBytes == dataCacheBytes && instructionCacheBytes / (64 * coherentCacheWays) >= 2),
        "dual-client TL-C uses equal RV64 I/D caches, 64-byte lines, at least two sets")
    require(!cacheFetchPredecode || (withC && coherentCaches && coherentControlCuts && coherentCacheWays == 2),
        "cached parcel predecode requires C, two-way coherent caches and explicit FPGA cuts")
    require(!indexedDataProofs || (withSv39 && fpgaTimingCuts && fastDataTranslation && preparedTranslationProofs),
        "indexed data proofs require Sv39, bounded fast data authorization and FPGA timing mode")
    require(!bankedTlbProofs || (withSv39 && fpgaTimingCuts && Set(16, 32).contains(tlbEntries)),
        "banked TLB proofs require explicit 16/32-entry Sv39 FPGA timing mode")
    require(!bankedTlbProofs || !fastDataTranslation || indexedDataProofs,
        "banked fast data translation retains indexed source-owned read/write proofs")
    // Capacity is explicit. This flag extends the prepared <=8-row path with
    // two/four local banks; it does not add an owner, PTW or request slot.
    def preparedTranslationProofs: Boolean = tlbEntries <= 8 || bankedTlbProofs
    require(!withD || withF, "D requires F")
    require(!withF || xlen == 64, "initial independent F/D integration supports RV64 only")
    val flen: Int = if (withD) 64 else 32
    val floatingConfig: I1FloatingPointConfig = I1FloatingPointConfig(f = withF, d = withD,
        resources = I1FloatingPointResourceConfig.fpga)
    require(Set("compact5", "balanced7", "fpga8").contains(pipelineProfile), "unsupported pipeline profile")
    require(!fpgaTimingCuts || pipelineProfile == "fpga8", "timing cuts require the explicit FPGA eight-stage profile")
    require(!fastDataTranslation || (fpgaTimingCuts && (withSv39 || pmpEntries > 0)),
        "fast data authorization requires registered FPGA addresses and an actual translation/protection stage")
    require(!directFastDataIssue || (fpgaTimingCuts && fastDataTranslation),
        "direct scalar issue requires explicit FPGA fast authorization; no unproven permission bypass")
    require(!overlapDataRetirement || (fpgaTimingCuts && earlyMemoryIssue && (withSv39 || pmpEntries > 0)),
        "data retirement overlap requires early issue, FPGA cuts and a registered translation/protection reply")
    require(!readOnlyDataRetirement || overlapDataRetirement, "read-only retirement requires explicit overlap enable")
    require(!withSupervisor || withUser, "S requires U")
    require(!withAia || (withSupervisor && xlen == 64), "I1 IMSIC requires RV64 S/U")
    require(!withSv39 || (withSupervisor && xlen == 64), "Sv39 requires RV64 S/U")
    require(Set(0, 4, 8, 16).contains(pmpEntries), "PMP has 0/4/8/16 writable regions")
    val physicalBits: Int = if (physicalAddressBits == 0) math.min(xlen, 36) else physicalAddressBits
    require(physicalBits >= 32 && physicalBits <= math.min(xlen, 56))
    require(tlbEntries >= 2 && tlbEntries <= 32 && (tlbEntries & (tlbEntries - 1)) == 0)
    // A present PMP exposes the architectural 16-entry bank; unused entries are hardwired OFF/zero.
    val pmpCsrEntries: Int = if (pmpEntries == 0) 0 else 16
    require(Set("dsp", "dsp-tiled", "iterative").contains(multiplyMode), "unknown multiplier implementation")
    require(resetVector >= 0 && resetVector < (BigInt(1) << xlen) && resetVector % (if (withC) 2 else 4) == 0)
    require(trapVector >= 0 && trapVector < (BigInt(1) << xlen) && trapVector % 4 == 0)
    require(hartId >= 0)
    require(Set("block", "distributed", "auto").contains(registerFileStorage), "unknown RAM implementation")
    private def powerOfTwo(n: Int): Boolean = n > 0 && (n & (n - 1)) == 0
    require(powerOfTwo(cacheLineBytes) && cacheLineBytes >= xlen / 8 && cacheLineBytes <= 256)
    for (bytes <- Seq(instructionCacheBytes, dataCacheBytes)) {
        require(bytes == 0 || (powerOfTwo(bytes) && bytes >= 2 * cacheLineBytes && bytes <= 65536),
            "cache must be disabled or a power-of-two capacity with at least two lines")
    }
    require(branchPredictorEntries == 0 || (powerOfTwo(branchPredictorEntries) &&
        branchPredictorEntries >= 2 && branchPredictorEntries <= 1024))
    require(cacheableBase >= 0 && cacheableBytes > 0 && cacheableBase + cacheableBytes < (BigInt(1) << xlen))
    require(cacheableBase % cacheLineBytes == 0 && cacheableBytes % cacheLineBytes == 0)
    val isa: String = "rv" + xlen + "i" + (if (withM) "m" else "") + (if (withA) "a" else "") +
        (if (withF) "f" else "") + (if (withD) "d" else "") + (if (withC) "c" else "") +
        "_zicsr_zifencei" + (if (withSv39) "_svade" else "")
    val registerReadStage: Boolean = pipelineProfile == "fpga8"
    val addressStage: Boolean = pipelineProfile != "compact5"
    val completionStage: Boolean = pipelineProfile != "compact5"
    val pipeline: Seq[String] = Seq("IF", "ID") ++ (if (registerReadStage) Seq("RF") else Nil) ++
        Seq("EX") ++ (if (addressStage) Seq("ADDR") else Nil) ++ Seq("MEM") ++
        (if (completionStage) Seq("CMP") else Nil) ++ Seq("WB")
    val registerFileStorageBits: Int = 2 * 32 * xlen
    val cachePayloadBits: Int = 8 * (instructionCacheBytes + dataCacheBytes)
}
