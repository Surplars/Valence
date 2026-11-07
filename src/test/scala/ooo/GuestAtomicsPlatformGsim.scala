package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.platform._

/** Native single-clock qualification of the explicitly A-enabled H tile and production
  * shared fabric. ROM, RAM, register decode, Home, APLIC and IMSIC are hardware.
  * The driver loads images only while CPU admission is disabled. The gates add
  * legal backpressure without substituting a reply or fabric owner.
  */
class GuestAtomicsPlatformGsim extends Module {
    val boundary = CommonCpuTilePortParams()
    val features = CommonPlatformFeatures(memoryCopyDma = false)
    val cpu = Module(new CommonHypervisorCpuTile(boundary = boundary, ramBytes = 65536, romBytes = 16384,
        mmioRegions = CommonPlatformAbi.cpuMmioRegions(features), atomicMemory = true))
    val fabric = Module(new CommonMachineFabric(boundary, features = features,
        ramBytes = 65536, externalDdr = false, romWords = 4096, programmable = true,
        ramResponseDelay = 3, externalUart = false, experimentalGuestFiles = 3))
    val io = IO(new Bundle {
        val enable = Input(Bool())
        val commitEnable = Input(Bool())
        val sources = Input(UInt(31.W))
        val program = chiselTypeOf(fabric.io.program.get)
        val ramProgram = chiselTypeOf(fabric.io.ramProgram.get)
        val allowRequest = Input(UInt(2.W))
        val allowResponse = Input(UInt(2.W))
        val allowMsi = Input(Bool())
        val allowMsiResponse = Input(Bool())
        val allowDrain = Input(Bool())
        val commit0 = chiselTypeOf(cpu.io.commit0)
        val commit1 = chiselTypeOf(cpu.io.commit1)
        val trap = chiselTypeOf(cpu.io.trap)
        val fetchPc = Output(UInt(64.W))
        val virtualized = Output(Bool())
        val scalar0Request = Output(Valid(new CommonTileScalarRequest(boundary)))
        val scalar1Request = Output(Valid(new CommonTileScalarRequest(boundary)))
        val scalarRequestReady = Output(UInt(2.W))
        val scalar0Response = Output(Valid(new CommonTileScalarResponse(boundary)))
        val scalar1Response = Output(Valid(new CommonTileScalarResponse(boundary)))
        val scalarResponseReady = Output(UInt(2.W))
        val msiRequest = Output(Valid(chiselTypeOf(cpu.io.bus.msi.request.bits)))
        val msiRequestReady = Output(Bool())
        val msiResponse = Output(Valid(chiselTypeOf(cpu.io.bus.msi.response.bits)))
        val msiResponseReady = Output(Bool())
        val maintenance = Output(Valid(new CommonTileMaintenanceStatus(boundary)))
        val maintenanceReady = Output(Bool())
        val drained = Output(Valid(UInt(boundary.maintenanceEpochBits.W)))
        val drainedReady = Output(Bool())
        val msiError = Output(Bool())
    })
    fabric.io.tile <> cpu.io.bus
    cpu.io.enable := io.enable; cpu.io.commitEnable := io.commitEnable
    fabric.io.program.get := io.program; fabric.io.ramProgram.get := io.ramProgram
    fabric.io.transportCpuEmptySynchronized := true.B; fabric.io.fabricTransportEmpty := true.B
    fabric.io.externalMaintenance.valid := false.B
    fabric.io.externalMaintenance.bits := 0.U.asTypeOf(fabric.io.externalMaintenance.bits)
    fabric.io.timerTick := false.B; fabric.io.sources := io.sources; fabric.io.uartRx := true.B
    // An offered valid may never be withdrawn. The test may delay admission,
    // but once exposed to a receiver, keep the gate open through its handshake.
    def heldGate(valid: Bool, ready: Bool, allow: Bool): Bool = {
        val held = RegInit(false.B)
        val open = held || allow
        when(valid && open) { held := !ready }
        assert(!held || valid, "a gated source withdrew a held offer")
        open
    }
    for (i <- 0 until 2) {
        val c = cpu.io.bus.scalar(i); val f = fabric.io.tile.scalar(i)
        val requestOpen = heldGate(c.request.valid, f.request.ready, io.allowRequest(i))
        val responseOpen = heldGate(f.response.valid, c.response.ready, io.allowResponse(i))
        f.request.valid := c.request.valid && requestOpen
        c.request.ready := f.request.ready && requestOpen
        c.response.valid := f.response.valid && responseOpen
        f.response.ready := c.response.ready && responseOpen
        Seq(io.scalar0Request, io.scalar1Request)(i).valid := c.request.valid; Seq(io.scalar0Request, io.scalar1Request)(i).bits := c.request.bits
        Seq(io.scalar0Response, io.scalar1Response)(i).valid := f.response.valid; Seq(io.scalar0Response, io.scalar1Response)(i).bits := f.response.bits
    }
    io.scalarRequestReady := VecInit(cpu.io.bus.scalar.map(_.request.ready)).asUInt
    io.scalarResponseReady := VecInit(fabric.io.tile.scalar.map(_.response.ready)).asUInt
    val msiOpen = heldGate(fabric.io.tile.msi.request.valid, cpu.io.bus.msi.request.ready, io.allowMsi)
    val msiResponseOpen = heldGate(cpu.io.bus.msi.response.valid, fabric.io.tile.msi.response.ready, io.allowMsiResponse)
    cpu.io.bus.msi.request.valid := fabric.io.tile.msi.request.valid && msiOpen
    fabric.io.tile.msi.request.ready := cpu.io.bus.msi.request.ready && msiOpen
    fabric.io.tile.msi.response.valid := cpu.io.bus.msi.response.valid && msiResponseOpen
    cpu.io.bus.msi.response.ready := fabric.io.tile.msi.response.ready && msiResponseOpen
    io.msiRequest.valid := fabric.io.tile.msi.request.valid
    io.msiRequest.bits := fabric.io.tile.msi.request.bits
    io.msiRequestReady := fabric.io.tile.msi.request.ready
    io.msiResponse.valid := cpu.io.bus.msi.response.valid
    io.msiResponse.bits := cpu.io.bus.msi.response.bits
    io.msiResponseReady := cpu.io.bus.msi.response.ready
    val drainOpen = heldGate(fabric.io.tile.fabricDrainedEpoch.valid,
        cpu.io.bus.fabricDrainedEpoch.ready, io.allowDrain)
    cpu.io.bus.fabricDrainedEpoch.valid := fabric.io.tile.fabricDrainedEpoch.valid && drainOpen
    fabric.io.tile.fabricDrainedEpoch.ready := cpu.io.bus.fabricDrainedEpoch.ready && drainOpen
    io.maintenance.valid := cpu.io.bus.maintenanceStatus.valid
    io.maintenance.bits := cpu.io.bus.maintenanceStatus.bits
    io.maintenanceReady := cpu.io.bus.maintenanceStatus.ready
    io.drained.valid := fabric.io.tile.fabricDrainedEpoch.valid
    io.drained.bits := fabric.io.tile.fabricDrainedEpoch.bits
    io.drainedReady := fabric.io.tile.fabricDrainedEpoch.ready
    io.commit0 := cpu.io.commit0; io.commit1 := cpu.io.commit1; io.trap := cpu.io.trap
    io.fetchPc := cpu.io.fetchPc; io.virtualized := cpu.io.virtualized
    io.msiError := fabric.io.msiError
    when(io.program.valid || io.ramProgram.valid) {
        assert(!io.enable, "platform programming requires disabled CPU admission")
    }
}
object GuestAtomicsPlatformGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestAtomicsPlatformGsim, Array("--target-dir", args(0)))
}
