package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder._
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus.RegisterPort

object FiveStageTileLinkMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageTileLink(FiveStageArguments.config(args)),
        Array("--target-dir", args.head))
}

object FiveStageRouteMain extends App {
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 1, sizeBits = 3)
    ChiselStage.emitCHIRRTLFile(new FiveStageTileLinkRoute(params, BigInt("80200000", 16),
        BigInt(1) << 31, args.contains("--registers"), args.contains("--timing-cuts")),
        Array("--target-dir", args.head))
}

object FiveStageSocArguments {
    def config(args: Array[String]): FiveStageSocConfig = {
        require(args.drop(2).map(_.takeWhile(_ != '=')).distinct.length == args.length - 2, "duplicate option")
        val extra = Set("--soc-no-uart", "--soc-no-timer", "--soc-no-irq", "--soc-ddr-one",
            "--soc-no-bootrom", "--soc-jtag", "--soc-fabric-cuts", "--soc-network", "--soc-managed-uart")
        val bootFile = args.find(_.startsWith("--soc-boot-file=")).map(_.stripPrefix("--soc-boot-file="))
        val cpuHz = args.find(_.startsWith("--soc-clock-hz=")).map(_.stripPrefix("--soc-clock-hz=").toInt)
            .getOrElse(100000000)
        val p = FiveStageArguments.config(args.filterNot(a => extra(a) || a.startsWith("--soc-boot-file=") ||
            a.startsWith("--soc-clock-hz=")))
        val rom = !args.contains("--soc-no-bootrom")
        FiveStageSocConfig(core = p.copy(resetVector = BigInt(if (rom) "10000" else "80200000", 16),
            trapVector = BigInt("80200100", 16), cacheableBase = BigInt("80200000", 16),
            cacheableBytes = BigInt(1) << 31), withUart = !args.contains("--soc-no-uart"),
            withTimer = !args.contains("--soc-no-timer"), withInterrupts = !args.contains("--soc-no-irq"),
            ddrSlots = if (args.contains("--soc-ddr-one")) 1 else 2, withBootRom = rom,
            withJtagLoader = args.contains("--soc-jtag"),
            fabricTimingCuts = args.contains("--soc-fabric-cuts"),
            withNetwork = args.contains("--soc-network"),
            managedPeripherals = args.contains("--soc-network") || args.contains("--soc-managed-uart"),
            clockHz = cpuHz,
            bootRomFile = bootFile.getOrElse("src/main/resources/inorder/bootrom.hex"))
    }
}

object FiveStageSocMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageSoc(FiveStageSocArguments.config(args)),
        Array("--target-dir", args.head))
}

object FiveStageSocGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageSoc(FiveStageSocArguments.config(args), simulationRomInit = true),
        Array("--target-dir", args.head))
}

object FiveStagePlicMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStagePlicHarness, Array("--target-dir", args.head))
}

/** Pinned GSIM cannot emit C++ accessors for top-level Vec ports; packing is a test adapter only. */
class FiveStagePlicHarness extends Module {
    val io = IO(new Bundle {
        val mmio = Flipped(new RegisterPort); val levels = Input(UInt(9.W)); val irq = Output(UInt(2.W))
    })
    val dut = Module(new soc.ip.interrupt.Plic(8, 2, 3))
    dut.io.mmio <> io.mmio
    for (i <- 0 to 8) dut.io.levels(i) := io.levels(i)
    io.irq := dut.io.irq.asUInt
}

object FiveStageStartupMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageStartup(!args.contains("--soc-no-bootrom")),
        Array("--target-dir", args.head))
}

object FiveStageBootRomMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageBootRomHarness(args(2)), Array("--target-dir", args.head))
}

class FiveStageBootRomHarness(file: String) extends Module {
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 1, sizeBits = 3)
    val io = IO(new Bundle {
        val port0 = Flipped(new TLBundle(params)); val port1 = Flipped(new TLBundle(params))
        val initialize = Input(Valid(new FiveStageRomInitialization(4096)))
    })
    val dut = Module(new FiveStageBootRom(params, BigInt("10000", 16), 4096, file, simulationInit = true))
    dut.io.ports(0) <> io.port0; dut.io.ports(1) <> io.port1; dut.io.initialize.get := io.initialize
}

object I1BscanArguments {
    private val prefix = "--soc-jtag-scan-bits="
    def scanBits(args: Array[String]): Int = {
        val selected = args.filter(_.startsWith(prefix))
        require(selected.length <= 1, "duplicate BSCAN scan-length option")
        val bits = selected.headOption.map(_.stripPrefix(prefix).toInt).getOrElse(64)
        I1BscanRamTransport.validateScanBits(bits)
        bits
    }
    def removeScanBits(args: Array[String]): Array[String] = args.filterNot(_.startsWith(prefix))
}

object FiveStageFpgaShellMain extends App {
    val chain = args.find(_.startsWith("--soc-user-chain=")).map(_.stripPrefix("--soc-user-chain=").toInt).getOrElse(0)
    val p = FiveStageSocArguments.config(I1BscanArguments.removeScanBits(args).filterNot(_.startsWith("--soc-user-chain=")))
    ChiselStage.emitCHIRRTLFile(new FiveStageFpgaShell(p, chain, I1BscanArguments.scanBits(args)), Array("--target-dir", args.head))
}

object I1NetworkFpgaShellMain extends App {
    val chain = args.find(_.startsWith("--soc-user-chain=")).map(_.stripPrefix("--soc-user-chain=").toInt).getOrElse(0)
    val simulation = args.contains("--simulation-clocks")
    val p = FiveStageSocArguments.config(I1BscanArguments.removeScanBits(args).filterNot(a => a.startsWith("--soc-user-chain=") ||
        a == "--simulation-clocks"))
    ChiselStage.emitCHIRRTLFile(new I1NetworkFpgaShell(p, chain, hardwareClocks = !simulation,
        jtagScanBits = I1BscanArguments.scanBits(args)),
        Array("--target-dir", args.head))
}

object I1PeripheralFpgaShellMain extends App {
    val chain = args.find(_.startsWith("--soc-user-chain=")).map(_.stripPrefix("--soc-user-chain=").toInt).getOrElse(0)
    val simulation = args.contains("--simulation-clocks")
    val p = FiveStageSocArguments.config(I1BscanArguments.removeScanBits(args).filterNot(a => a.startsWith("--soc-user-chain=") ||
        a == "--simulation-clocks"))
    ChiselStage.emitCHIRRTLFile(new I1PeripheralFpgaShell(p, chain, hardwareClocks = !simulation,
        jtagScanBits = I1BscanArguments.scanBits(args)),
        Array("--target-dir", args.head))
}
