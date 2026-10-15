package soc.core.ooo
import org.scalatest.funsuite.AnyFunSuite
import _root_.ooo.ProfileAbi77
import soc.core.ooo._
class LoadReadyBackendConfigSpec extends AnyFunSuite {
    test("single named opt-in field and full bounded prerequisite product") {
        val off = LoadReadyBackendFixture.params(false)
        val on = LoadReadyBackendFixture.params(true)
        assert(!OooParams().registeredLoadResultReady)
        assert(on.copy(registeredLoadResultReady = false) == off)
        assert(off.productElementNames.zip(off.productIterator).toMap.keySet ==
            on.productElementNames.zip(on.productIterator).toMap.keySet)
        ProfileAbi77.requireLive(off); ProfileAbi77.requireLive(on)
        assert(off.productArity == on.productArity && off.productArity == 178
        )
        assert(!off.frozenStoreCheckedFlow && !on.frozenStoreCheckedFlow)
        assert(off.heldAluIssueForwarding && on.heldAluIssueForwarding)
        assert(!off.machineSystem && off.virtualMemoryLevels == 0 && !off.taggedStoreReturns)
        assert(off.bankedIssuePayload && off.bankedRobPayload && off.tentativeRenameSources)
        assert(off.directRegisteredExecutionOperands && off.sharedLane1OwnerMatch)
        val invalid: Seq[() => OooParams] = Seq(
            () => on.copy(heldAluIssueForwarding=false), () => on.copy(ownerLocalOperandReady=false),
            () => on.copy(ownerLocalIssueReady=false), () => on.copy(registeredIssueExecute=false),
            () => on.copy(registeredLoadIssueForwarding=false), () => on.copy(parallelIssuePayload=false),
            () => on.copy(parallelIssueRanks=false), () => on.copy(parallelPrfReadyUpdates=false),
            () => on.copy(lvtPhysicalRegisterFile=false), () => on.copy(robEntries=32),
            () => on.copy(physicalRegs=64), () => on.copy(tagBits=32), () => on.copy(memoryEntries=2),
            () => on.copy(moveAlias=true), () => on.copy(loadCompletionBypass=true),
            () => on.copy(mulWordPreviewBypass=true), () => on.copy(fastHeadLoadRetire=true),
            () => on.copy(fastBufferedStoreRetire=true), () => on.copy(renameWidth=1),
            () => on.copy(commitWidth=1), () => on.copy(completionWidth=1))
        invalid.foreach(f => intercept[IllegalArgumentException] { f() })
    }
}
