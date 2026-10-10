package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Source-prepared qualification; these checks do not replace directed GSIM ownership/fault tests. */
class CanonicalVirtualStoreConfigSpec extends AnyFunSuite {
    private def legal: OooParams = BoardSocConfig.timingParams("staged-fetch-turnover").copy(
        machineSystem = true, pmpEntries = 8, virtualMemoryLevels = 3,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true, registeredMemoryRequests = true, registeredMemoryAddress = true,
        registeredTranslationHeads = true, virtualRamLoadPrecheck = true,
        canonicalVirtualStoreOverlap = true)

    test("canonical virtual-store overlap is independently default off") {
        assert(!OooParams().canonicalVirtualStoreOverlap)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!c.coreParams.canonicalVirtualStoreOverlap)
        }
        val off = legal.copy(canonicalVirtualStoreOverlap = false)
        assert(legal == off.copy(canonicalVirtualStoreOverlap = true))
        assert(legal.postedProofConfig == off.postedProofConfig)
    }

    test("canonical guard rejects its own missing transport prerequisites") {
        val message = "canonical virtual store overlap requires load precheck and registered buffered parallel memory ownership"
        def rejected(make: => OooParams): Unit = {
            val error = intercept[IllegalArgumentException] { make }
            assert(error.getMessage.contains(message))
        }
        rejected(OooParams(canonicalVirtualStoreOverlap = true))
        for (remove <- Seq[OooParams => OooParams](
            _.copy(virtualRamLoadPrecheck = false),
            _.copy(bufferedRamStores = false),
            _.copy(registeredMemoryRequests = false),
            _.copy(registeredMemoryAddress = false),
            _.copy(registeredTranslationHeads = false),
            _.copy(memoryEntries = 1))) rejected(remove(legal))
        val serial = legal.copy(canonicalVirtualStoreOverlap = false, virtualRamLoadPrecheck = false,
            memoryEntries = 1)
        assert(serial.memoryEntries == 1)
    }

    test("existing load-precheck authority guards remain mandatory") {
        for (remove <- Seq[OooParams => OooParams](
            _.copy(virtualMemoryLevels = 0), _.copy(pmpEntries = 0), _.copy(speculativeRamBytes = 0))) {
            val error = intercept[IllegalArgumentException] { remove(legal) }
            assert(error.getMessage.contains("virtual RAM load precheck requires staged addresses, VM/PMP"))
        }
    }

    test("independent legal LSU and store-buffer capacities stay configurable") {
        for (lsu <- Seq(2, 4); stores <- Seq(1, 2, 4)) {
            val p = legal.copy(memoryEntries = lsu, storeBufferEntries = stores)
            assert(p.memoryEntries == lsu && p.storeBufferEntries == stores)
        }
    }

    test("canonical metadata and tracker are absent from option-off module interfaces") {
        for (enabled <- Seq(false, true)) {
            val p = legal.copy(canonicalVirtualStoreOverlap = enabled)
            val backend = ChiselStage.emitCHIRRTL(new IntegerBackend(p))
            val adapter = ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p, registerCheckedRequests = true))
            assert(backend.contains("module CanonicalStoreTracker :") == enabled)
            assert(backend.contains("canonicalStoreEpoch :") == enabled)
            assert(backend.contains("canonicalStore :") == enabled)
            assert(adapter.contains("canonicalStoreOrigin :") == enabled)
            assert(adapter.contains("originalVirtualAddress :") == enabled)
            assert(adapter.contains("canonicalStoreCertificate :") == enabled)
            // The public memory port remains the original DataRequest/DataResponse type.
            assert(!(new DataRequest).elements.keys.exists(_.contains("canonical")))
        }
    }

    test("actual translation integration rejects a missing checked boundary") {
        val adapter = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new DataTranslationAdapter(legal, registerCheckedRequests = false))
        }
        assert(adapter.getMessage.contains("virtual load precheck requires a registered physical authorization boundary"))
        val mapped = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MappedMachineCore(legal, dataTranslation = true,
                stagedMemoryFabric = false))
        }
        assert(mapped.getMessage.contains("virtual load precheck requires the staged physical authorization adapter"))
    }
}
