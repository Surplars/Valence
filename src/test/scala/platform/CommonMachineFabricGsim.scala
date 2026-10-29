package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.ooo.{InstructionRom, TileLinkInstructionRomAdapter}
import soc.platform.{CommonMachineFabric, CommonPeripheralConfig, CommonPlatformFeatures, CommonCpuTilePortParams}

/** Fabric-only native/MMIO/DDR test: real 128 KiB ROM and production 1024x4
  * Home/4-slot/2-write DDR. External managed peripherals are test endpoints.
  * This does not instantiate either CPU and makes no CDC/board claim.
  */
object CommonMachineFabricGsimMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabric(
        features = CommonPlatformFeatures(ethernetControl = true, networkDma = true,
            jtagDownload = true, clockManagement = true),
        programmable = true), Array("--target-dir", args(0)))
}

/** Same production fabric and DDR ledger, with explicit runtime epoch hold enabled. */
object CommonMachineFabricRuntimeGsimMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabric(
        boundary = CommonCpuTilePortParams(runtimeMaintenance = true),
        features = CommonPlatformFeatures(ethernetControl = true, networkDma = true,
            jtagDownload = true, clockManagement = true),
        programmable = true), Array("--target-dir", args(0)))
}

/** Runtime cancellation retains the external owner through terminal consumption. */
object CommonMachineFabricCancellationGsimMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabric(
        boundary = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true),
        features = CommonPlatformFeatures(ethernetControl = true, networkDma = true,
            jtagDownload = true, clockManagement = true),
        programmable = true), Array("--target-dir", args(0)))
}

/** Compare the unchanged default narrow-bank contract with complete-beat
  * reads. Permission extent and TL metadata remain the original narrow Get.
  */
class CommonInstructionRomContractGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val io = IO(new Bundle {
        val defaultPort = Flipped(new TLBundle(params))
        val completePort = Flipped(new TLBundle(params))
        val initialize = Input(Valid(new Bundle {
            val index = UInt(4.W)
            val data = UInt(32.W)
        }))
        val defaultMask = Output(UInt(2.W))
        val completeMask = Output(UInt(2.W))
    })
    private def attach(port: TLBundle, full: Boolean): UInt = {
        val manager = if (full) Module(new TileLinkInstructionRomAdapter(16, params = params,
            completeReadBeat = true)) else Module(new TileLinkInstructionRomAdapter(16, params = params))
        val rom = Module(new InstructionRom(16, BigInt("80000000", 16), programmable = true))
        manager.io.tl <> port
        rom.io.fetch <> manager.io.rom
        rom.io.write.get <> io.initialize
        manager.io.rom.requestMask
    }
    io.defaultMask := attach(io.defaultPort, false)
    io.completeMask := attach(io.completePort, true)
}

object CommonInstructionRomContractGsimMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonInstructionRomContractGsim, Array("--target-dir", args(0)))
}

/** Test-only scalar top ports avoid the pinned simulator's retained-Vec accessor
  * limitation. Every leaf wires directly to the unchanged production fabric.
  */
class CommonFabricFlatPort(fields: Seq[(String, Data)]) extends Record {
    import chisel3.reflect.DataMirror
    import chisel3.ActualDirection
    override val elements = scala.collection.immutable.ListMap(fields.map { case (name, data) =>
        val leaf = DataMirror.directionOf(data) match {
            case ActualDirection.Input => Input(chiselTypeOf(data))
            case ActualDirection.Output => Output(chiselTypeOf(data))
            case other => throw new IllegalArgumentException(s"unexpected fabric leaf direction $other")
        }
        name -> leaf
    }: _*)
}
class CommonMachineFabricFlatGsim(runtime: Boolean, cancellation: Boolean = false,
    jtagDownload: Boolean = true, memoryCopyDma: Boolean = true, network: Boolean = true) extends Module {
    val fabric = Module(new CommonMachineFabric(
        boundary = CommonCpuTilePortParams(runtimeMaintenance = runtime, runtimeCancellation = cancellation),
        features = CommonPeripheralConfig(jtagDownload = jtagDownload, memoryCopyDma = memoryCopyDma,
            network = network).features,
        programmable = true))
    private def leaves(data: Data, prefix: String): Seq[(String, Data)] = data match {
        case record: Record => record.elements.toSeq.flatMap { case (name, value) =>
            leaves(value, if (prefix.isEmpty) name else prefix + "__" + name)
        }
        case vector: Vec[_] => vector.zipWithIndex.flatMap { case (value, index) =>
            leaves(value, prefix + "_" + index)
        }.toSeq
        case leaf => Seq(prefix -> leaf)
    }
    private val fields = leaves(fabric.io, "")
    val io = IO(new CommonFabricFlatPort(fields))
    fields.foreach { case (name, leaf) => io.elements(name) <> leaf }
}
object CommonMachineFabricFlatGsimMain extends App {
    require(args.length == 2 || args.length == 3, "fresh output directory, runtime and optional cancellation flags required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(args(1).toBoolean, args.length == 3 && args(2).toBoolean),
        Array("--target-dir", args(0)))
}

/** Matched static fabric pair; no CPU, platform CDC or board qualification. */
object CommonMachineFabricJtagOptionGsimMain extends App {
    require(args.length == 2, "fresh output directory and on|off JTAG selection required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    val peripherals = CommonPeripheralConfig.jtagOption(args(1))
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(runtime = false,
        jtagDownload = peripherals.jtagDownload), Array("--target-dir", args(0)))
}

/** Ordinary DMA composition pair, keeping the independent network/JTAG producers enabled. */
object CommonMachineFabricMemoryDmaOptionGsimMain extends App {
    require(args.length == 2 && Set("on", "off").contains(args(1)),
        "fresh output directory and on|off ordinary DMA selection required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(runtime = false,
        memoryCopyDma = args(1) == "on"), Array("--target-dir", args(0)))
}
