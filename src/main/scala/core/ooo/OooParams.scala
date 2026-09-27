package soc.core.ooo

import chisel3.util.log2Ceil

/** Initial integer backend parameters. Wider product profiles are not implemented presets. */
case class OooParams(
    renameWidth: Int = 2,
    commitWidth: Int = 2,
    completionWidth: Int = 2,
    robEntries: Int = 32,
    physicalRegs: Int = 64,
    tagBits: Int = 64,
    speculativeRamBase: BigInt = 0,
    speculativeRamBytes: BigInt = 0,
    memoryEntries: Int = 4,
    branchPredictorEntries: Int = 64,
    bufferedRamStores: Boolean = false,
    fastBufferedStoreRetire: Boolean = false,
    fastHeadLoadRetire: Boolean = false,
    loadCompletionBypass: Boolean = false,
    mulWordPreviewBypass: Boolean = false,
    moveAlias: Boolean = false,
    flowTileLinkResponse: Boolean = false,
    storeBufferEntries: Int = 4,
    machineSystem: Boolean = false,
    atomicMemory: Boolean = false,
    pmpEntries: Int = 0,
    virtualMemoryLevels: Int = 0,
    compressedInstructions: Boolean = false,
    instructionCacheSets: Int = 0,
    returnStackEntries: Int = 16,
    indirectTargetEntries: Int = 0,
    recoveryWidth: Int = 1
) {
    require(
        Seq(renameWidth, commitWidth, completionWidth).forall(w => w >= 1 && w <= 6),
        "each backend port width must be between one and six"
    )
    require(
        robEntries >= Seq(2, renameWidth, commitWidth).max && isPow2(robEntries),
        "ROB capacity must be a power of two, at least two, and cover allocation/commit widths"
    )
    require(physicalRegs > 32 && physicalRegs <= 256, "integer PRF needs more than 32 and at most 256 entries")
    require(tagBits >= 8 && tagBits <= 64, "allocation tag width must be between 8 and 64")

    require(
        speculativeRamBase >= 0 && speculativeRamBytes >= 0 &&
            speculativeRamBase + speculativeRamBytes <= (BigInt(1) << 64),
        "invalid speculative RAM range"
    )

    require(
        !atomicMemory || (speculativeRamBytes >= 64 && speculativeRamBase % 64 == 0 && speculativeRamBytes % 64 == 0),
        "atomics require an explicit RAM window with whole reservation granules"
    )
    require(Set(1, 2, 4, 8).contains(memoryEntries), "memory slots must be 1, 2, 4 or 8")
    require(Set(0, 16, 32, 64).contains(indirectTargetEntries), "indirect target entries must be 0, 16, 32 or 64")
    require(Set(1, 2, 4, 8).contains(storeBufferEntries), "store buffer must have 1, 2, 4 or 8 entries")
    require(Set(0, 8, 16).contains(pmpEntries) && (pmpEntries == 0 || machineSystem),
        "PMP requires machine-system mode and supports 0, 8 or 16 entries")
    require(Set(0, 3, 4, 5).contains(virtualMemoryLevels) &&
        (virtualMemoryLevels == 0 || (machineSystem && pmpEntries > 0)),
        "virtual memory control requires machine-system mode, PMP and Sv39/Sv48/Sv57")
    require(!bufferedRamStores || speculativeRamBytes > 0, "buffered writes require an explicit no-write-error RAM")
    require(!fastBufferedStoreRetire || bufferedRamStores,
        "same-cycle buffered store retirement requires guaranteed-success RAM buffering")

    require(
        branchPredictorEntries >= 2 && branchPredictorEntries <= 256 && isPow2(branchPredictorEntries),
        "branch predictor entries must be a power of two between 2 and 256"
    )
    val frontendCacheSets: Int = if (instructionCacheSets == 0) {
        if (renameWidth >= 4) 128 else 64
    } else instructionCacheSets
    require(frontendCacheSets >= 2 && frontendCacheSets <= 256 && isPow2(frontendCacheSets),
        "instruction cache sets must be automatic or a power of two between 2 and 256")
    require(returnStackEntries >= 2 && returnStackEntries <= 32 && isPow2(returnStackEntries),
        "return stack entries must be a power of two between 2 and 32")
    require(Set(1, 2, 4, 8, 16).contains(recoveryWidth) && recoveryWidth <= robEntries,
        "recovery width must be 1, 2, 4, 8 or 16 and fit the ROB")

    // A memory start shares the ALU issue budget. Completion ports are separately arbitrated.
    val issueWidth: Int = completionWidth
    val robBits: Int    = log2Ceil(robEntries)
    val physBits: Int   = log2Ceil(physicalRegs)
    val countBits: Int  = log2Ceil(robEntries + 1)

    private def isPow2(value: Int): Boolean = value > 0 && (value & (value - 1)) == 0
}
