package ooo

import soc.core.ooo._
import java.nio.file.{Files, Paths}

object LoadReadyP1Params {
    def apply(enabled: Boolean): OooParams = OooParams(
        robEntries = 16, physicalRegs = 48, tagBits = 64, memoryEntries = 4,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096,
        parallelPrfReadyUpdates = true, ownerLocalOperandReady = true,
        ownerLocalIssueReady = true, registeredIssueExecute = true,
        registeredLoadIssueForwarding = true, heldAluIssueForwarding = true,
        parallelIssuePayload = true, parallelIssueRanks = true, earlyRankedOperands = true,
        parallelRecoveryAdmission = true, lvtPhysicalRegisterFile = true,
        registeredBranchRedirect = true, precompleteMispredictedBranch = true,
        registeredRobRetirement = true, registeredLoadResultReady = enabled)
    def params(enabled: Boolean): OooParams = apply(enabled)
    def write(target: String, enabled: Boolean): Unit = {
        Files.createDirectories(Paths.get(target))
        val p = apply(enabled)
        val fields = p.productElementNames.zip(p.productIterator).map { case (k, v) =>
            s"\"$k\":\"${v.toString.replace("\\", "\\\\").replace("\"", "\\\"")}\""
        }.mkString(",\n")
        Files.writeString(Paths.get(target, "parameters.json"), s"{\n$fields\n}\n")
    }
}
