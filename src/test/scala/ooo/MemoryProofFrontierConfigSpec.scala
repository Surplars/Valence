package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Constructor-only gate. The exact archived model-r64p64 profile is the control, not a new preset. */
class MemoryProofFrontierConfigSpec extends AnyFunSuite {
    private val options = PostedPrefetchBoardProfiles.options("head-offer", "on") ++
        Set("--canonical-virtual-store-overlap", "--rob-entries=64", "--physical-regs=64")
    private val off = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    test("frontier is default off and changes no frozen capacity or baseline switch") {
        assert(!FpgaNextConfig.Selected.memoryProofFrontier && !off.memoryProofFrontier)
        val on = FpgaNextConfig.fromOptions(options + "--memory-proof-frontier", defaultSelected = false)
        assert(on.copy(memoryProofFrontier = false) == off)
        assert(on.coreParams.copy(memoryProofFrontier = false) == off.coreParams)
        assert(on.coreParams.robEntries == 64 && on.coreParams.physicalRegs == 64 && on.coreParams.memoryEntries == 4)
        assert(on.coreParams.memoryProofRows == 16 && on.coreParams.memoryProofCacheSets == 256)
        assert(on.coreParams.registeredLoadReplay && on.coreParams.loadOrderOlderRetire)
        assert(on.coreParams.registeredIssueExecute)
        assert(!on.coreParams.precheckedDataRequestFlow && !on.coreParams.fastBufferedStoreRetire)
        assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage)
    }
    test("unsupported constructor combinations fail closed") {
        val on = off.copy(memoryProofFrontier = true)
        for (missing <- Seq("--virtual-ram-load-precheck", "--canonical-virtual-store-overlap",
            "--load-order-older-retire", "--rob-entries=64", "--physical-regs=64")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(options - missing + "--memory-proof-frontier", defaultSelected = false).coreParams
            }
        }
        intercept[IllegalArgumentException] { on.coreParams.copy(memoryProofRows = 24) }
        intercept[IllegalArgumentException] { on.coreParams.copy(memoryProofCacheSets = 128) }
        intercept[IllegalArgumentException] { on.coreParams.copy(registeredMemoryAddress = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(parallelMemoryPayload = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(registeredTranslatedResponses = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(registeredFabricBoundary = false) }
    }
    test("frontier rejects an otherwise legal combinational issue configuration") {
        val unstaged = off.coreParams.copy(registeredIssueExecute = false,
            registeredLoadIssueForwarding = false, earlyStorePreparation = false,
            sharedStoreOperandReads = false, ownerLocalIssueReady = false)
        assert(!unstaged.memoryProofFrontier && !unstaged.registeredIssueExecute)
        val rejected = intercept[IllegalArgumentException] { unstaged.copy(memoryProofFrontier = true) }
        assert(rejected.getMessage.contains("memory proof frontier supports only"))
    }
}
