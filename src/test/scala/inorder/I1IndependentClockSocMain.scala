package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.inorder._

/** Explicit functional selections; neither is a qualified production board profile.
  * test-only is a short RV64IMA/2 KiB fixture; full-cpu restores the batch44
  * CPU feature/capacity selection. Neither changes the existing board profile.
  * C, F/D, S/U, Sv39 and PMP are excluded only from the small test-only fixture.
  * The 50 MHz declaration is the fabric UART/timer timebase. No CPU frequency
  * or physical timing qualification is implied by the asynchronous test ratios.
  */
object I1IndependentClockProfile {
    // CPU flags reconstructed from the checked-in selection chain:
    // coherent_network_acceptance.py:416-428,490-495 -> cpu_timing34_acceptance.py:48-55
    // (the documented r1 command uses its all-retirement/default fast-issue choices)
    // -> bandwidth36_acceptance.py:40-41 -> bandwidth37_acceptance.py:48-49.
    // bandwidth38..44 preserve that list. board_short_proof.py independently
    // requires the same 32 KiB/two-slot/full bandwidth profile. No TLB override
    // appears in that CPU selection: the public default remains four entries.
    val fullCpuFlags: Seq[String] = Seq(
        "--pipeline=fpga8", "--timing-cuts", "--dsp-tiled",
        "--icache=32768", "--dcache=32768", "--predictor=128",
        "--early-memory-issue", "--overlap-write-lookup", "--sv39", "--pmp=8",
        "--c", "--a", "--f", "--d", "--coherent-control-cuts", "--coherent-bandwidth",
        "--fast-data-translation", "--coherent-whole-line", "--coherent-caches",
        "--soc-fabric-cuts", "--coherent-ways=2", "--cache-fetch-predecode", "--indexed-data-proofs",
        "--overlap-data-retirement", "--direct-fast-data-issue", "--coherent-line-grants",
        "--coherent-miss-turnover", "--coherent-writeback-overlap", "--coherent-read-overlap",
        "--data-reply-handoff")

    /** Full CPU geometry/features only, NOT the complete batch44 board shell.
      * JTAG maintenance and managed UART/CMU remain blocked by the production
      * assembly's explicit requirements. The CPU has no reduced cache, MSHR,
      * TLB or DDR owner count. UART/timer now belong to the 50 MHz fabric.
      */
    def fullCpu(romFile: String): FiveStageSocConfig = FiveStageSocArguments.config(
        (Seq("unused", "64") ++ fullCpuFlags ++
            Seq("--soc-clock-hz=50000000", "--soc-boot-file=" + romFile)).toArray)

    def config(romFile: String, profile: String): FiveStageSocConfig = profile match {
        case "test-only" => testOnly(romFile)
        case "full-cpu" => fullCpu(romFile)
        case _ => throw new IllegalArgumentException("explicit test-only or full-cpu profile required")
    }

    private def testOnly(romFile: String): FiveStageSocConfig = FiveStageSocConfig(
        core = FiveStageConfig(
            resetVector = BigInt("10000", 16), trapVector = BigInt("80200100", 16),
            cacheableBase = BigInt("80200000", 16), cacheableBytes = BigInt(1) << 31,
            pipelineProfile = "fpga8", fpgaTimingCuts = true,
            withM = true, withA = true, withC = false, withF = false, withD = false,
            withUser = false, withSupervisor = false, withSv39 = false, pmpEntries = 0,
            instructionCacheBytes = 2048, dataCacheBytes = 2048, coherentCaches = true,
            coherentCacheWays = 2, coherentControlCuts = true, coherentBandwidth = true,
            coherentWholeLine = true, coherentLineGrants = true,
            coherentWritebackOverlap = true, coherentReadOverlap = true),
        clockHz = 50000000, uartBaud = 460800, ddrSlots = 2, bootRomFile = romFile,
        withJtagLoader = false, withNetwork = false, managedPeripherals = false,
        fabricTimingCuts = true)
}

/** Identical external pins in both modes. In single mode the real pre-existing
  * FiveStageSoc and all peripherals use cpuClock; the test drives matching clocks
  * for that control. Its cycle count is a control, never an asynchronous result.
  * Simulation-only coherent readback verifies dirty CPU data through the Home.
  */
class I1IndependentClockHarness(p: FiveStageSocConfig, independent: Boolean, fifoDepth: Int = 16) extends RawModule {
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new I1IndependentClockSocIO(p, simulationAgent = true))
    if (independent) {
        val dut = Module(new I1IndependentClockSoc(p, depth = fifoDepth,
            simulationRomInit = true, simulationAgent = true))
        dut.cpuClock := cpuClock; dut.fabricClock := fabricClock; dut.commonColdReset := commonColdReset
        dut.io.clockLocked := io.clockLocked; dut.io.ddrReady := io.ddrReady
        dut.io.uartRx := io.uartRx; dut.io.externalIrq := io.externalIrq
        io.uartTx := dut.io.uartTx; io.ddrAxi <> dut.io.ddrAxi
        dut.io.networkMemory.get <> io.networkMemory.get
        dut.io.romInitialize.get.valid := false.B
        dut.io.romInitialize.get.bits := 0.U.asTypeOf(dut.io.romInitialize.get.bits)
        io.retire := dut.io.retire; io.trapTaken := dut.io.trapTaken
        io.trapPc := dut.io.trapPc; io.trapCause := dut.io.trapCause
        io.cycles := dut.io.cycles; io.instructions := dut.io.instructions
        io.resetHeld := dut.io.resetHeld; io.resetFault := dut.io.resetFault
        io.cpuLinkReady := dut.io.cpuLinkReady; io.fabricLinkReady := dut.io.fabricLinkReady
        io.cpuTransportEmpty := dut.io.cpuTransportEmpty; io.fabricTransportEmpty := dut.io.fabricTransportEmpty
        io.timeSnapshot := dut.io.timeSnapshot
    } else {
        val dut = withClockAndReset(cpuClock, commonColdReset) {
            Module(new FiveStageSoc(p, simulationRomInit = true))
        }
        dut.io.clockLocked := io.clockLocked; dut.io.ddrReady := io.ddrReady
        dut.io.uartRx := io.uartRx; dut.io.externalIrq := io.externalIrq
        io.uartTx := dut.io.uartTx; io.ddrAxi <> dut.io.ddrAxi
        dut.io.networkMemory.get <> io.networkMemory.get
        dut.io.romInitialize.get.valid := false.B
        dut.io.romInitialize.get.bits := 0.U.asTypeOf(dut.io.romInitialize.get.bits)
        dut.io.jtagLinkUp := false.B; dut.io.jtagDmi.request.valid := false.B
        dut.io.jtagDmi.request.bits := 0.U.asTypeOf(dut.io.jtagDmi.request.bits)
        dut.io.jtagDmi.response.ready := true.B
        io.retire := dut.io.retire; io.trapTaken := dut.io.trapTaken
        io.trapPc := dut.io.trapPc; io.trapCause := dut.io.trapCause
        io.cycles := dut.io.cycles; io.instructions := dut.io.instructions
        io.resetHeld := dut.io.resetHeld; io.resetFault := dut.io.resetFault
        io.cpuLinkReady := !dut.io.resetHeld; io.fabricLinkReady := !dut.io.resetHeld
        // Legacy FiveStageSoc has no CDC transport or time-snapshot debug ports.
        io.cpuTransportEmpty := false.B; io.fabricTransportEmpty := false.B; io.timeSnapshot := 0.U
    }
}

/** Explicit mode is mandatory; native Icarus compatibility is standard firtool lowering. */
object I1IndependentClockSocMain extends App {
    require(args.length == 4 && Set("independent", "single").contains(args(1)) &&
        Set("test-only", "full-cpu").contains(args(2)),
        "usage: I1IndependentClockSocMain <output-directory> <independent|single> " +
            "<test-only|full-cpu> <checked-ROM-hex>")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))),
        "output directory must be fresh; refusing to overwrite prior evidence")
    require(java.nio.file.Files.isRegularFile(java.nio.file.Paths.get(args(3))), "ROM hex file is missing")
    val mode = args(1)
    val profile = args(2)
    val p = I1IndependentClockProfile.config(args(3), profile)
    val independent = mode == "independent"
    val fifoDepth = 16
    def romHash(): String = java.security.MessageDigest.getInstance("SHA-256")
        .digest(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(args(3))))
        .map(b => f"${b & 255}%02x").mkString
    val romSha256 = romHash()
    ChiselStage.emitSystemVerilogFile(
        new I1IndependentClockHarness(p, independent, fifoDepth),
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
    require(romHash() == romSha256, "ROM changed during emission; no profile receipt issued")
    // Values come from the configuration actually elaborated, not the CLI label.
    val storage = if (independent) "HeldResponseCdcDataFifo" else "synchronous"
    val depth = if (independent) fifoDepth else 0
    val receipt = s"""{
  "schema": 1,
  "mode": "$mode",
  "profile": "$profile",
  "isa": "${p.core.isa}",
  "instructionCacheBytes": ${p.core.instructionCacheBytes},
  "dataCacheBytes": ${p.core.dataCacheBytes},
  "coherentCacheWays": ${p.core.coherentCacheWays},
  "cacheLineBytes": ${p.core.cacheLineBytes},
  "ddrSlots": ${p.ddrSlots},
  "ddrWriteSlots": 1,
  "fabricClockHz": ${p.clockHz},
  "uartBaud": ${p.uartBaud},
  "heldFifo": "$storage",
  "fifoDepth": $depth,
  "tlbEntries": ${p.core.tlbEntries},
  "pmpEntries": ${p.core.pmpEntries},
  "branchPredictorEntries": ${p.core.branchPredictorEntries},
  "withJtagLoader": ${p.withJtagLoader},
  "managedPeripherals": ${p.managedPeripherals},
  "withNetwork": ${p.withNetwork},
  "fullBoardQualified": false,
  "loweringOptions": ["disallowLocalVariables", "disallowPackedArrays"],
  "defaultLayerSpecialization": "enable",
  "verificationFlavor": "if-else-fatal",
  "romSha256": "$romSha256"
}
"""
    java.nio.file.Files.write(java.nio.file.Paths.get(args(0), "emission-profile.json"),
        receipt.getBytes(java.nio.charset.StandardCharsets.UTF_8),
        java.nio.file.StandardOpenOption.CREATE_NEW, java.nio.file.StandardOpenOption.WRITE)
}
