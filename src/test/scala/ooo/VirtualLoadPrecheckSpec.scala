package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class VirtualLoadPrecheckSpec extends AnyFunSuite {
    test("virtual load precheck is default-off and changes only its explicit option") {
        assert(!OooParams().virtualRamLoadPrecheck)
        assert(!BoardSocConfig.params.virtualRamLoadPrecheck)
        val base = VirtualLoadPrecheckFixture.params(false)
        assert(VirtualLoadPrecheckFixture.params(true) == base.copy(virtualRamLoadPrecheck = true))
        assert(base.issueWidth == 2 && base.memoryEntries == 2 && base.registeredMemoryAddress)
    }
    test("certified virtual loads require VM, PMP, address staging and parallel bounded RAM") {
        val valid = VirtualLoadPrecheckFixture.params(true)
        for (invalid <- Seq[() => OooParams](
            () => valid.copy(machineSystem = false),
            () => valid.copy(pmpEntries = 0),
            () => valid.copy(virtualMemoryLevels = 0),
            () => valid.copy(registeredMemoryAddress = false),
            () => valid.copy(memoryEntries = 1),
            () => valid.copy(speculativeRamBytes = 0))) {
            intercept[IllegalArgumentException] { invalid() }
        }
    }
}
