package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class CommonFabricDmaExperimentSpec extends AnyFunSuite {
    private val profile = CommonCpuProfile.A1
    private val peripherals = CommonPeripheralConfig()
    private val boundary = CommonCpuTilePortParams()
    private def resolved(selection: Option[CommonFabricDmaExperiment]) =
        CommonFabricDmaExperiment.resolve(profile, peripherals, boundary, selection)

    test("absence preserves every FPGA field and all existing overlap defaults") {
        val actual = resolved(None)
        assert(actual.fpga == profile.fpga)
        assert(actual.fpga.productIterator.toSeq == profile.fpga.productIterator.toSeq)
        assert(!actual.completionFlow && !actual.readOverlap && !actual.probeOverlap)
        assert(CommonFabricDmaExperiment.fromOptions("a1", Seq.empty).isEmpty)
        assert(CommonFabricDmaExperiment.fromOptions("i1", Seq.empty).isEmpty)
        val runtimeBoundary = boundary.copy(runtimeMaintenance = true, runtimeCancellation = true)
        val unchangedI1 = CommonFabricDmaExperiment.resolve(CommonCpuProfile.I1, peripherals,
            runtimeBoundary, None, runtime = true)
        assert(unchangedI1 == CommonFabricDmaExperiment.Resolved(CommonCpuProfile.I1.fpga))
    }

    test("matched experiments change only Probe selection and do not mutate CPU resolution") {
        val cpu = CommonSocConfig(profile).cpuConfig(boundary)
        val off = resolved(Some(CommonFabricDmaExperiment.ReadBaseline))
        val on = resolved(Some(CommonFabricDmaExperiment.ProbeAcquire))
        assert(off.copy(probeOverlap = true) == on)
        assert(off.completionFlow && off.readOverlap && !off.probeOverlap && on.probeOverlap)
        assert(on.fpga.dmaLineTransfers && on.fpga.dmaLineEntries == 2 && on.fpga.lineReadChannel)
        assert(on.fpga.ddrWriteCollectionFlow && on.fpga.dmaLineThresholdRewrite && !on.fpga.dmaSingleReadWait)
        assert(CommonSocConfig(profile).cpuConfig(boundary) == cpu)
        assert(profile.fpga != on.fpga)
        assert(on.fpga.copy(ddrWriteCollectionFlow = profile.fpga.ddrWriteCollectionFlow,
            dmaLineTransfers = profile.fpga.dmaLineTransfers, dmaLineEntries = profile.fpga.dmaLineEntries,
            lineReadChannel = profile.fpga.lineReadChannel,
            dmaLineThresholdRewrite = profile.fpga.dmaLineThresholdRewrite,
            dmaSingleReadWait = profile.fpga.dmaSingleReadWait) == profile.fpga)
    }

    test("explicit CLI rejects duplicate unknown and unsupported selectors") {
        val off = "--experimental-fabric-dma=read-baseline"
        val on = "--experimental-fabric-dma=probe-acquire"
        assert(CommonFabricDmaExperiment.fromOptions("a1", Seq(off)).contains(CommonFabricDmaExperiment.ReadBaseline))
        assert(CommonFabricDmaExperiment.fromOptions("a1", Seq(on)).contains(CommonFabricDmaExperiment.ProbeAcquire))
        intercept[IllegalArgumentException] { CommonFabricDmaExperiment.fromOptions("a1", Seq(off, on)) }
        intercept[IllegalArgumentException] { CommonFabricDmaExperiment.fromOptions("a1", Seq(on, on)) }
        intercept[IllegalArgumentException] { CommonFabricDmaExperiment.fromOptions("a1", Seq("--experimental-fabric-dma=other")) }
        intercept[IllegalArgumentException] { CommonFabricDmaExperiment.fromOptions("i1", Seq(on)) }
        intercept[IllegalArgumentException] { CommonFabricDmaExperiment.fromOptions("--soc-config=unused.json", Seq(on)) }
        intercept[IllegalArgumentException] {
            CommonSocConfigFile.select("a1", Seq(on, on), "")
        }
    }

    test("real resolver rejects unsupported clock runtime and absent DMA scopes") {
        val selected = Some(CommonFabricDmaExperiment.ProbeAcquire)
        intercept[IllegalArgumentException] {
            CommonFabricDmaExperiment.resolve(CommonCpuProfile.I1, peripherals, boundary, selected)
        }
        intercept[IllegalArgumentException] {
            CommonFabricDmaExperiment.resolve(CommonCpuProfile.A1Boot50, peripherals, boundary, selected)
        }
        intercept[IllegalArgumentException] {
            CommonFabricDmaExperiment.resolve(profile, peripherals, boundary, selected, runtime = true)
        }
        intercept[IllegalArgumentException] {
            CommonFabricDmaExperiment.resolve(profile, peripherals,
                boundary.copy(runtimeMaintenance = true, runtimeCancellation = true), selected)
        }
        intercept[IllegalArgumentException] {
            CommonFabricDmaExperiment.resolve(profile, peripherals.copy(memoryCopyDma = false), boundary, selected)
        }
        intercept[IllegalArgumentException] {
            val wider = boundary.copy(coherent = boundary.coherent.copy(sourceBits = 4, sinkBits = 2),
                homeAcquireEntries = 4, homeWritebackEntries = 4)
            CommonFabricDmaExperiment.resolve(profile, peripherals, wider, selected)
        }
    }
}
