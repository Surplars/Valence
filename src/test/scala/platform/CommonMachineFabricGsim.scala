package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.ooo.{InstructionRom, TileLinkInstructionRomAdapter}
import soc.platform.{CommonMachineFabric, CommonPlatformFeatures}

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
