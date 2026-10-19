package inorder

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.inorder._

class I1IndependentClockSocSpec extends AnyFunSuite {
    test("independent-clock functional profile retains coherent RV64IMA and unchanged DDR capacity") {
        val p = I1IndependentClockProfile.config("src/main/resources/inorder/bootrom.hex", "test-only")
        assert(p.core.isa == "rv64ima_zicsr_zifencei")
        assert(p.core.pipelineProfile == "fpga8" && p.ddrSlots == 2 && p.clockHz == 50000000)
        assert(p.core.instructionCacheBytes == 2048 && p.core.dataCacheBytes == 2048)
        assert(p.core.coherentCacheWays == 2 && p.core.coherentLineGrants && p.core.coherentReadOverlap)
        assert(!p.withJtagLoader && !p.withNetwork && !p.managedPeripherals)
    }


    test("full CPU preserves batch44 feature and capacity selection without claiming its board shell") {
        val p = I1IndependentClockProfile.config("src/main/resources/inorder/bootrom.hex", "full-cpu")
        val c = p.core
        assert(c.isa == "rv64imafdc_zicsr_zifencei_svade")
        assert(c.instructionCacheBytes == 32768 && c.dataCacheBytes == 32768 && c.coherentCacheWays == 2)
        assert(c.tlbEntries == 4 && c.pmpEntries == 8 && c.branchPredictorEntries == 128)
        assert(c.withUser && c.withSupervisor && c.withSv39 && c.multiplyMode == "dsp-tiled")
        assert(c.coherentLineGrants && c.coherentMissTurnover && c.coherentWritebackOverlap && c.coherentReadOverlap)
        assert(c.cacheFetchPredecode && c.indexedDataProofs && c.directFastDataIssue && c.dataReplyHandoff)
        assert(c.overlapDataRetirement && !c.readOnlyDataRetirement && p.ddrSlots == 2)
        assert(p.clockHz == 50000000 && !p.withJtagLoader && !p.managedPeripherals && !p.withNetwork)
        intercept[IllegalArgumentException] {
            I1IndependentClockProfile.config("src/main/resources/inorder/bootrom.hex", "default")
        }
    }

    test("ordered native crossing has separate asynchronous request and response storage") {
        val fir = ChiselStage.emitCHIRRTL(new I1OrderedDataClockBoundary(carriesClear = true))
        assert(fir.linesIterator.count(_.contains(" of HeldResponseCdcDataFifo")) == 2)
        assert(fir.contains("clearPending") && fir.contains("inFlight") && fir.contains("fabricClearReservation"))
        assert(!fir.contains("RegisterClockDomainBridge"))
    }

    test("unbuffered request admission is rejected before a clear/request ready loop can elaborate") {
        val p = I1IndependentClockProfile.config("src/main/resources/inorder/bootrom.hex", "test-only")
        val unbuffered = p.copy(core = p.core.copy(coherentBandwidth = false, coherentWholeLine = false,
            coherentLineGrants = false, coherentWritebackOverlap = false, coherentReadOverlap = false))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new I1IndependentClockSoc(unbuffered))
        }
    }

    test("unsupported external maintenance owner fails loudly") {
        val p = I1IndependentClockProfile.config("src/main/resources/inorder/bootrom.hex", "test-only")
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new I1IndependentClockSoc(p.copy(withJtagLoader = true)))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new I1IndependentClockSoc(p.copy(managedPeripherals = true)))
        }
    }
}
