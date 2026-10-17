package soc.core.ooo

import chisel3._
import chisel3.util._

/** Exact fallback pool factorization. Original presence precedes issued-owner exclusion. */
object PreparedStorePool {
    /** Ordinary saved operands only. Numeric VA range carries no physical authority. */
    def virtualOperands(pending: Bool, live: Bool, atHead: Bool, indexMatches: Bool,
        request: IntegerRequest, prepared: Bool, addressKnown: Bool, virtualized: Bool): Bool =
        pending && live && !atHead && indexMatches &&
            request.memory && request.store && !request.atomic &&
            !request.system && !request.mulDiv && request.controlFlow === ControlFlow.none &&
            request.operation === IntegerOp.add && !request.fetchFault && !request.fetchPageFault &&
            prepared && addressKnown && virtualized

    def fallback(original: UInt, prepared: UInt, preparationEnabled: Bool, lateEnable: Boolean): (UInt, Bool) = {
        require(original.getWidth == prepared.getWidth)
        if (lateEnable) {
            (Mux(original.orR, original, prepared), original.orR || preparationEnabled)
        } else {
            (Mux(original.orR, original, prepared & Fill(original.getWidth, preparationEnabled)), true.B)
        }
    }
}

/** Bounded default-OFF constructor contract; raw operands do not cache VM/PMP authorization. */
object VirtualStoreOperandLookaheadContract {
    def requireSupported(p: OooParams, enabled: Boolean, factored: Boolean, descriptor: Boolean): Unit = {
        require(!enabled || (p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 &&
            p.issueWidth == 2 && p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 &&
            p.memoryEntries == 4 && p.virtualMemoryLevels == 3 && p.machineSystem &&
            p.parallelMemoryPreparation && p.registeredMemoryAddress && p.residentMemoryPayloadReuse &&
            p.preparedStoreLookahead && !p.postedPreparationPriority && factored && descriptor &&
            p.registeredIssueHeadMask && p.bankedIssuePayload && p.unconditionalMemoryPayloadCapture &&
            !p.fastBufferedStoreRetire && !p.fastHeadLoadRetire && !p.memoryProofFrontier &&
            !p.translatedResponseEmptyFlow && !p.frozenStoreCheckedFlow),
            "virtual operand lookahead requires the qualified two-wide four-slot factored descriptor profile")
    }
}
