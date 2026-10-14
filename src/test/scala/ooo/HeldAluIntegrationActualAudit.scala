package ooo

import soc.core.ooo._

/** Object reads only: no new RTL ports, state, controls or hardware observations. */
object HeldAluIntegrationActualAudit {
    def requireArgument(expected: FpgaNextConfig, argument: Boolean): Unit =
        require(argument == expected.coreParams.heldAluIssueForwarding,
            "held ALU argument differs from actual matching-board configuration")

    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        val core = platform.core.core.core
        val backend = core.backend
        val p = expected.coreParams
        require(core.p == p && backend.p == p && backend.ledger.p == p,
            "complete core/backend/ledger constructor parameters must be identical")
        require(backend.p.heldAluIssueForwarding == expected.heldAluIssueForwarding)
        require(core.p.productArity == 174 && expected.productArity == 91)
        require(backend.executionStages.size == (if (p.registeredIssueExecute) p.completionWidth else 0))
        if (p.heldAluIssueForwarding) {
            require(backend.executionStages.size == 2 && p.renameWidth == 2 && p.commitWidth == 2 &&
                p.completionWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 &&
                p.registeredIssueExecute && p.registeredLoadIssueForwarding && p.parallelIssuePayload &&
                p.parallelIssueRanks && p.parallelRecoveryAdmission && !p.moveAlias &&
                !p.loadCompletionBypass && !p.mulWordPreviewBypass)
        }
        Map("schema" -> "actual-held-alu-integration-v1", "scope" -> "actual-constructor-only",
            "core" -> core.p, "backend" -> backend.p, "ledger" -> backend.ledger.p,
            "coreNames" -> p.productElementNames.toSeq, "profileNames" -> expected.productElementNames.toSeq,
            "heldAluIssueForwarding" -> backend.p.heldAluIssueForwarding,
            "executionStages" -> backend.executionStages.size,
            "nearTermA" -> NearTermAActualAudit.capture(platform, expected),
            "profileFields" -> expected.productArity, "coreFields" -> p.productArity,
            "dynamicQualification" -> false, "physicalQualification" -> false)
    }
}
