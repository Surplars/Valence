package ooo
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
class LoadReadyP1ConfigSpec extends AnyFunSuite {
    test("single named opt-in field and full bounded prerequisite product") {
        val off = LoadReadyP1Params(false)
        val on = LoadReadyP1Params(true)
        assert(!OooParams().registeredLoadResultReady)
        assert(on.copy(registeredLoadResultReady = false) == off)
        assert(off.productElementNames.zip(off.productIterator).toMap.keySet ==
            on.productElementNames.zip(on.productIterator).toMap.keySet)
        assert(off.productArity == on.productArity)
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
