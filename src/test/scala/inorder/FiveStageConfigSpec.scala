package inorder

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import soc.core.inorder._

class FiveStageConfigSpec extends AnyFlatSpec with Matchers {
    "I1 coherent fabric" should "keep coherence and managed clocks explicit, removable and non-aliasing" in {
        FiveStageConfig().coherentCaches shouldBe false
        FiveStageConfig().coherentControlCuts shouldBe false
        FiveStageConfig().coherentBandwidth shouldBe false
        FiveStageConfig().coherentWholeLine shouldBe false
        FiveStageConfig().coherentLineGrants shouldBe false
        FiveStageConfig().coherentMissTurnover shouldBe false
        FiveStageConfig().coherentWritebackOverlap shouldBe false
        FiveStageConfig().coherentReadOverlap shouldBe false
        FiveStageConfig().dataReplyHandoff shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(coherentReadOverlap = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(dataReplyHandoff = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(coherentLineGrants = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(coherentMissTurnover = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(coherentWritebackOverlap = true) }
        val opts = Array("out", "64", "--pipeline=fpga8", "--timing-cuts",
            "--coherent-caches", "--icache=2048", "--dcache=2048", "--soc-fabric-cuts",
            "--soc-network", "--soc-clock-hz=300000000")
        val p = FiveStageSocArguments.config(opts)
        p.core.coherentCaches shouldBe true
        p.fabricTimingCuts shouldBe true
        p.withNetwork shouldBe true
        p.clockHz shouldBe 300000000
        p.networkDmaBase shouldBe BigInt("10005000", 16)
        p.ddrSlots shouldBe 2
        p.core.copy(coherentControlCuts = true).coherentControlCuts shouldBe true
        intercept[IllegalArgumentException] { FiveStageConfig(coherentControlCuts = true) }
        intercept[IllegalArgumentException] { p.core.copy(coherentBandwidth = true) }
        val bandwidth = FiveStageSocArguments.config(opts ++ Array("--coherent-control-cuts", "--coherent-bandwidth"))
        bandwidth.core.coherentBandwidth shouldBe true
        bandwidth.ddrSlots shouldBe p.ddrSlots
        bandwidth.core.tlbEntries shouldBe p.core.tlbEntries
        intercept[IllegalArgumentException] { p.core.copy(coherentWholeLine = true) }
        bandwidth.core.copy(coherentWholeLine = true).cachePayloadBits shouldBe bandwidth.core.cachePayloadBits
        val whole = FiveStageSocArguments.config(opts ++ Array("--coherent-control-cuts",
            "--coherent-bandwidth", "--coherent-whole-line"))
        whole.core.coherentWholeLine shouldBe true
        val overlapped = FiveStageSocArguments.config(opts ++ Array("--coherent-control-cuts",
            "--coherent-bandwidth", "--coherent-whole-line", "--coherent-line-grants",
            "--coherent-miss-turnover", "--coherent-writeback-overlap", "--coherent-ways=2"))
        overlapped.core.coherentLineGrants shouldBe true
        overlapped.core.coherentMissTurnover shouldBe true
        overlapped.core.coherentWritebackOverlap shouldBe true
        val paired = overlapped.core.copy(coherentReadOverlap = true, dataReplyHandoff = true,
            earlyMemoryIssue = true, overlapDataRetirement = true, directFastDataIssue = true,
            fastDataTranslation = true, pmpEntries = 8)
        paired.cachePayloadBits shouldBe overlapped.core.cachePayloadBits
        overlapped.core.cachePayloadBits shouldBe whole.core.cachePayloadBits
        overlapped.ddrSlots shouldBe whole.ddrSlots
        intercept[IllegalArgumentException] { whole.core.copy(coherentMissTurnover = true) }
        whole.ddrSlots shouldBe p.ddrSlots
        p.core.copy(coherentCacheWays = 2).cachePayloadBits shouldBe p.core.cachePayloadBits
        intercept[IllegalArgumentException] { p.core.copy(coherentCacheWays = 4) }
        intercept[IllegalArgumentException] {
            p.core.copy(coherentCacheWays = 2, instructionCacheBytes = 128, dataCacheBytes = 128)
        }
        intercept[IllegalArgumentException] { p.copy(networkDmaBase = BigInt("10002000", 16)) }
        intercept[IllegalArgumentException] { p.copy(core = p.core.copy(coherentCaches = false)) }
        intercept[IllegalArgumentException] { p.copy(withInterrupts = false) }
        intercept[IllegalArgumentException] { p.core.copy(dataCacheBytes = 4096) }
        intercept[IllegalArgumentException] { p.core.copy(instructionCacheBytes = 0, dataCacheBytes = 0) }
        intercept[IllegalArgumentException] { p.core.copy(xlen = 32) }
        for (bytes <- Seq(128, 2048, 32768)) {
            p.core.copy(instructionCacheBytes = bytes, dataCacheBytes = bytes).coherentCaches shouldBe true
        }
    }
    "Orbital-I1" should "have exactly five in-order stages and an honest ISA contract" in {
        FiveStageConfig().pipeline shouldBe Seq("IF", "ID", "EX", "MEM", "WB")
        FiveStageConfig().isa shouldBe "rv64im_zicsr_zifencei"
        FiveStageConfig(xlen = 32, withM = false).isa shouldBe "rv32i_zicsr_zifencei"
        FiveStageConfig().registerFileStorageBits shouldBe 4096
    }
    it should "select real pipeline stages independently of width and ISA features" in {
        val expected = Seq(
            "compact5" -> Seq("IF", "ID", "EX", "MEM", "WB"),
            "balanced7" -> Seq("IF", "ID", "EX", "ADDR", "MEM", "CMP", "WB"),
            "fpga8" -> Seq("IF", "ID", "RF", "EX", "ADDR", "MEM", "CMP", "WB"))
        for ((profile, stages) <- expected; width <- Seq(32, 64); bypass <- Seq(false, true)) {
            val p = FiveStageArguments.config(Array("out", width.toString, "--c", "--a",
                "--pipeline=" + profile)).copy(memoryBypass = bypass)
            p.pipeline shouldBe stages
            p.isa shouldBe ("rv" + width + "imac_zicsr_zifencei")
            p.registerReadStage shouldBe (profile == "fpga8")
            p.addressStage shouldBe (profile != "compact5")
            p.completionStage shouldBe (profile != "compact5")
        }
        FiveStageConfig().pipelineProfile shouldBe "compact5"
        intercept[IllegalArgumentException] { FiveStageConfig(pipelineProfile = "nine") }
        intercept[IllegalArgumentException] {
            FiveStageArguments.config(Array("out", "64", "--pipeline=ten"))
        }
    }
    it should "keep full F and D as independently selectable elaboration-time extensions" in {
        for (profile <- Seq("compact5", "balanced7", "fpga8")) {
            val f = FiveStageArguments.config(Array("out", "64", "--f", "--pipeline=" + profile))
            val fd = FiveStageArguments.config(Array("out", "64", "--f", "--d", "--c", "--a",
                "--pipeline=" + profile))
            f.isa shouldBe "rv64imf_zicsr_zifencei"
            f.flen shouldBe 32
            f.floatingConfig.complete shouldBe true
            f.withD shouldBe false
            fd.isa shouldBe "rv64imafdc_zicsr_zifencei"
            fd.flen shouldBe 64
            fd.floatingConfig.complete shouldBe true
        }
        FiveStageConfig().withF shouldBe false
        FiveStageConfig().withD shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(withD = true) }
        intercept[IllegalArgumentException] { FiveStageArguments.config(Array("out", "64", "--d")) }
        intercept[IllegalArgumentException] { FiveStageConfig(xlen = 32, withF = true) }
    }
    it should "keep timing cuts independent from removable ISA hardware" in {
        FiveStageConfig().fpgaTimingCuts shouldBe false
        for (m <- Seq(false, true); a <- Seq(false, true); c <- Seq(false, true);
             features <- Seq((false, false), (true, false), (true, true))) {
            val p = FiveStageConfig(pipelineProfile = "fpga8", fpgaTimingCuts = true,
                withM = m, withA = a, withC = c, withF = features._1, withD = features._2)
            p.pipeline.size shouldBe 8
            p.isa.takeWhile(_ != '_').contains("f") shouldBe features._1
            p.isa.takeWhile(_ != '_').contains("d") shouldBe features._2
        }
        intercept[IllegalArgumentException] { FiveStageConfig(fpgaTimingCuts = true) }
    }
    it should "keep fast data permission proofs optional without adding TLB entries" in {
        FiveStageConfig().fastDataTranslation shouldBe false
        FiveStageConfig().directFastDataIssue shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(directFastDataIssue = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(fastDataTranslation = true) }
        intercept[IllegalArgumentException] {
            FiveStageConfig(pipelineProfile = "fpga8", fpgaTimingCuts = true, fastDataTranslation = true)
        }
        val p = FiveStageArguments.config(Array("out", "64", "--pipeline=fpga8", "--timing-cuts",
            "--sv39", "--pmp=4", "--tlb=4", "--fast-data-translation"))
        p.fastDataTranslation shouldBe true
        p.tlbEntries shouldBe 4
        p.pipeline.size shouldBe 8
        val direct = FiveStageArguments.config(Array("out", "64", "--pipeline=fpga8", "--timing-cuts",
            "--sv39", "--pmp=4", "--tlb=4", "--fast-data-translation", "--direct-fast-data-issue"))
        direct.directFastDataIssue shouldBe true
        direct.tlbEntries shouldBe p.tlbEntries
        direct.pipeline shouldBe p.pipeline
        FiveStageConfig(xlen = 32, pipelineProfile = "fpga8", fpgaTimingCuts = true,
            pmpEntries = 4, fastDataTranslation = true).tlbEntries shouldBe 4
    }
    it should "replace only a consumed registered data owner without growing capacity" in {
        FiveStageConfig().overlapDataRetirement shouldBe false
        FiveStageConfig().readOnlyDataRetirement shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(readOnlyDataRetirement = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(overlapDataRetirement = true) }
        intercept[IllegalArgumentException] {
            FiveStageConfig(pipelineProfile = "fpga8", fpgaTimingCuts = true,
                pmpEntries = 4, overlapDataRetirement = true)
        }
        for (fast <- Seq(false, true)) {
            val p = FiveStageArguments.config(Array("out", "64", "--pipeline=fpga8", "--timing-cuts",
                "--sv39", "--pmp=4", "--tlb=4", "--early-memory-issue", "--overlap-data-retirement") ++
                (if (fast) Array("--fast-data-translation") else Array.empty[String]))
            p.overlapDataRetirement shouldBe true
            p.fastDataTranslation shouldBe fast
            p.tlbEntries shouldBe 4
            p.pipeline.size shouldBe 8
            p.copy(readOnlyDataRetirement = true).readOnlyDataRetirement shouldBe true
        }
    }
    it should "accept both FPGA multiplier profiles and remove M at elaboration" in {
        for (xlen <- Seq(32, 64); m <- Seq(false, true); mode <- Seq("dsp", "dsp-tiled", "iterative"); bypass <- Seq(false, true)) {
            val p = FiveStageConfig(xlen, m, mode, bypass)
            p.xlen shouldBe xlen
            p.withM shouldBe m
        }
    }
    it should "keep throughput experiments independently removable and five-stage" in {
        FiveStageConfig().earlyMemoryIssue shouldBe false
        FiveStageConfig().overlapWriteLookup shouldBe false
        val p = FiveStageArguments.config(Array("out", "64", "--dsp-tiled", "--early-memory-issue",
            "--overlap-write-lookup", "--icache=2048", "--dcache=2048", "--predictor=64"))
        p.multiplyMode shouldBe "dsp-tiled"
        p.earlyMemoryIssue shouldBe true
        p.overlapWriteLookup shouldBe true
        p.pipeline shouldBe Seq("IF", "ID", "EX", "MEM", "WB")
        intercept[IllegalArgumentException] {
            FiveStageArguments.config(Array("out", "64", "--dsp-tiled", "--iterative"))
        }
    }
    it should "parameterize cache payload and prediction without changing architectural stages" in {
        for (bytes <- Seq(0, 512, 2048, 8192, 32768); entries <- Seq(0, 16, 64, 256)) {
            val p = FiveStageConfig(instructionCacheBytes = bytes, dataCacheBytes = bytes,
                branchPredictorEntries = entries)
            p.cachePayloadBits shouldBe 16 * bytes
            p.pipeline.size shouldBe 5
        }
        intercept[IllegalArgumentException] { FiveStageConfig(instructionCacheBytes = 1000) }
        intercept[IllegalArgumentException] { FiveStageConfig(dataCacheBytes = 64) }
        intercept[IllegalArgumentException] { FiveStageConfig(branchPredictorEntries = 3) }
        intercept[IllegalArgumentException] { FiveStageConfig(cacheLineBytes = 4) }
        val p = FiveStageArguments.config(Array("out", "64", "--icache=2048", "--dcache=8192", "--predictor=64"))
        p.instructionCacheBytes shouldBe 2048
        p.dataCacheBytes shouldBe 8192
        p.branchPredictorEntries shouldBe 64
        intercept[IllegalArgumentException] { FiveStageArguments.config(Array("out", "64", "--predictor=4", "--predictor=8")) }
        intercept[IllegalArgumentException] { FiveStageArguments.config(Array("out", "64", "--icache=2048=bad")) }
    }
    it should "reject unsupported widths, multiplier modes and non-aligned vectors" in {
        for (xlen <- Seq(16, 128)) intercept[IllegalArgumentException] { FiveStageConfig(xlen = xlen) }
        intercept[IllegalArgumentException] { FiveStageConfig(multiplyMode = "unknown") }
        intercept[IllegalArgumentException] { FiveStageConfig(resetVector = 3) }
        intercept[IllegalArgumentException] { FiveStageConfig(trapVector = BigInt(1) << 64) }
        intercept[IllegalArgumentException] { FiveStageConfig(hartId = -1) }
        intercept[IllegalArgumentException] { FiveStageConfig(registerFileStorage = "flip-flops") }
        intercept[IllegalArgumentException] { FiveStageArguments.config(Array("out", "64", "--unknown")) }
        intercept[IllegalArgumentException] {
            FiveStageArguments.config(Array("out", "64", "--rf-auto", "--rf-distributed"))
        }
    }
    it should "bound a parameterized bare SoC and preserve full physical DDR addresses" in {
        val p = FiveStageSocConfig()
        p.ddrBase + p.ddrBytes shouldBe BigInt("100200000", 16)
        p.core.pipeline.size shouldBe 5
        p.ddrSlots shouldBe 2
        p.core.resetVector shouldBe BigInt("10000", 16)
        p.withJtagLoader shouldBe false
        p.withBootRom shouldBe true
        FiveStageSocArguments.config(Array("out", "64", "--soc-no-uart", "--soc-no-timer",
            "--soc-no-irq", "--soc-ddr-one", "--no-m")).withUart shouldBe false
        intercept[IllegalArgumentException] { FiveStageSocConfig(ddrSlots = 4) }
        intercept[IllegalArgumentException] { FiveStageSocConfig(core = FiveStageConfig()) }
        intercept[IllegalArgumentException] { FiveStageSocConfig(uartBaud = 10000000) }
        intercept[IllegalArgumentException] {
            FiveStageSocConfig(core = p.core.copy(cacheableBase = BigInt("10001000", 16), cacheableBytes = 8192),
                ddrBase = BigInt("10001000", 16), ddrBytes = 8192)
        }
    }
    it should "reserve shared FPGA JTAG only for a bounded boot-owned download" in {
        val p = FiveStageSocArguments.config(Array("out", "64", "--soc-jtag"))
        p.withJtagLoader shouldBe true
        p.plicSources shouldBe 8
        p.jtagDownloadBytes shouldBe (BigInt(64) << 20)
        intercept[IllegalArgumentException] { p.copy(jtagDownloadBytes = BigInt(1) << 31) }
        intercept[IllegalArgumentException] { p.copy(withBootRom = false) }
        intercept[IllegalArgumentException] { p.copy(plicSources = 2) }
        intercept[IllegalArgumentException] {
            FiveStageSocArguments.config(Array("out", "64", "--soc-jtag", "--soc-no-bootrom"))
        }
        FiveStageSocArguments.config(Array("out", "64", "--soc-no-bootrom")).core.resetVector shouldBe
            BigInt("80200000", 16)
    }
    it should "bind BSCAN scan length to explicit board topology without widening acceptance" in {
        I1BscanArguments.scanBits(Array("out", "64")) shouldBe 64
        for (bits <- Seq(64, 65, 66, 127)) {
            I1BscanArguments.scanBits(Array("out", "64", s"--soc-jtag-scan-bits=$bits")) shouldBe bits
        }
        for (bits <- Seq(-1, 0, 63, 128)) {
            intercept[IllegalArgumentException] {
                I1BscanArguments.scanBits(Array("out", "64", s"--soc-jtag-scan-bits=$bits"))
            }
        }
        intercept[IllegalArgumentException] {
            I1BscanArguments.scanBits(Array("--soc-jtag-scan-bits=65", "--soc-jtag-scan-bits=65"))
        }
        val args = Array("out", "64", "--soc-jtag", "--soc-jtag-scan-bits=65")
        FiveStageSocArguments.config(I1BscanArguments.removeScanBits(args)).withJtagLoader shouldBe true
    }
    it should "keep privilege, protection and translation independently removable" in {
        val p = FiveStageArguments.config(Array("out", "64", "--sv39", "--pmp=4", "--tlb=8"))
        p.withUser shouldBe true
        p.withSupervisor shouldBe true
        p.withSv39 shouldBe true
        p.isa shouldBe "rv64im_zicsr_zifencei_svade"
        p.pmpCsrEntries shouldBe 16
        p.pipeline.size shouldBe 5
        FiveStageConfig().withSupervisor shouldBe false
        FiveStageConfig().withSv39 shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(withSupervisor = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(withSv39 = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(xlen = 32, withUser = true,
            withSupervisor = true, withSv39 = true) }
        intercept[IllegalArgumentException] { FiveStageConfig(pmpEntries = 3) }
        intercept[IllegalArgumentException] { FiveStageConfig(tlbEntries = 3) }
    }
    it should "bind indexed data proofs to the bounded explicit FPGA mode" in {
        FiveStageConfig().indexedDataProofs shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(indexedDataProofs = true) }
        val p = FiveStageArguments.config(Array("out", "64", "--sv39", "--pipeline=fpga8",
            "--timing-cuts", "--fast-data-translation", "--indexed-data-proofs", "--tlb=8"))
        p.indexedDataProofs shouldBe true
        p.tlbEntries shouldBe 8
        intercept[IllegalArgumentException] { p.copy(tlbEntries = 16) }
        intercept[IllegalArgumentException] { p.copy(fastDataTranslation = false) }
        intercept[IllegalArgumentException] { p.copy(withSv39 = false) }
    }
    it should "keep larger prepared TLB proof banks explicit and preserve source-owned data proofs" in {
        FiveStageConfig().bankedTlbProofs shouldBe false
        FiveStageConfig(tlbEntries = 16).preparedTranslationProofs shouldBe false
        for (entries <- Seq(16, 32)) {
            val p = FiveStageArguments.config(Array("out", "64", "--sv39", "--pipeline=fpga8",
                "--timing-cuts", "--fast-data-translation", "--indexed-data-proofs",
                "--banked-tlb-proofs", s"--tlb=$entries"))
            p.bankedTlbProofs shouldBe true
            p.preparedTranslationProofs shouldBe true
            p.tlbEntries shouldBe entries
            intercept[IllegalArgumentException] { p.copy(bankedTlbProofs = false) }
            intercept[IllegalArgumentException] { p.copy(indexedDataProofs = false) }
            intercept[IllegalArgumentException] { p.copy(fpgaTimingCuts = false) }
            intercept[IllegalArgumentException] { p.copy(withSv39 = false) }
            intercept[IllegalArgumentException] { p.copy(tlbEntries = 8) }
        }
    }
    it should "keep IMSIC explicit and require the implemented RV64 M/S files" in {
        FiveStageConfig().withAia shouldBe false
        FiveStageConfig().externalFenceICompletion shouldBe false
        val p = FiveStageArguments.config(Array("out", "64", "--supervisor", "--aia"))
        p.withAia shouldBe true
        p.isa.contains("h") shouldBe false
        intercept[IllegalArgumentException] { FiveStageConfig(withAia = true) }
        intercept[IllegalArgumentException] { p.copy(xlen = 32) }
        intercept[IllegalArgumentException] { p.copy(withSupervisor = false) }
    }
    it should "parameterize C/A without advertising floating point or changing stages" in {
        val p = FiveStageArguments.config(Array("out", "64", "--c", "--a", "--sv39", "--pmp=4"))
        p.isa shouldBe "rv64imac_zicsr_zifencei_svade"
        p.pipeline shouldBe Seq("IF", "ID", "EX", "MEM", "WB")
        FiveStageConfig().withC shouldBe false
        FiveStageConfig().withA shouldBe false
        FiveStageConfig(withC = true, resetVector = BigInt("80000002", 16)).withC shouldBe true
        intercept[IllegalArgumentException] { FiveStageConfig(resetVector = BigInt("80000002", 16)) }
        FiveStageConfig(xlen = 32, withM = false, withC = true, withA = true).isa shouldBe
            "rv32iac_zicsr_zifencei"
    }
}
