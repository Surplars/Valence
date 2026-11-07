package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.ip.interrupt.{Imsic, ImsicParams}
import soc.platform._

object GuestCounterTestParams {
    def apply(enabled: Boolean = true): OooParams = OooParams(
        hypervisorExperiment = true, robEntries = 16, physicalRegs = 48, memoryEntries = 2,
        machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16,
        basicCounters = enabled, atomicMemory = !enabled,
        speculativeRamBase = if (enabled) BigInt(0) else BigInt("80200000", 16),
        speculativeRamBytes = if (enabled) BigInt(0) else BigInt(65536))
}

/** Only genuine bank inputs: the driver independently predicts every same-clock edge. */
class BasicCounterBankGsim extends Module {
    val bank = Module(new BasicCounterBank(GuestCounterTestParams()))
    val io = IO(chiselTypeOf(bank.io))
    io <> bank.io
}
object BasicCounterBankGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new BasicCounterBankGsim, Array("--target-dir", args(0)))
}

/** Real MSU, with independently supplied architectural retirement events. The disabled
  * variant is A-enabled to prove A does not imply basic counters. IRQ sources stay zero.
  */
class GuestCountersSystemGsim(enabled: Boolean = true) extends Module {
    override def desiredName: String = if (enabled) "GuestCountersSystemGsim" else "GuestCountersAbsentSystemGsim"
    val p = GuestCounterTestParams(enabled)
    val io = IO(new Bundle {
        val start = Input(Bool()); val instruction = Input(UInt(32.W)); val operand = Input(UInt(64.W))
        val pc = Input(UInt(64.W)); val tokenIndex = Input(UInt(p.robBits.W)); val tokenTag = Input(UInt(p.tagBits.W))
        val ready = Output(Bool()); val completeReady = Input(Bool()); val complete = Output(Bool())
        val data = Output(UInt(64.W)); val exception = Output(Bool()); val cause = Output(UInt(64.W))
        val tval = Output(UInt(64.W)); val nextPc = Output(UInt(64.W)); val redirect = Output(Bool())
        val retired = Input(UInt(log2Ceil(p.commitWidth + 1).W)); val retire = Input(Bool())
        val retireIndex = Input(UInt(p.robBits.W)); val retireTag = Input(UInt(p.tagBits.W))
        val trap = Input(Bool()); val trapPc = Input(UInt(64.W)); val trapCause = Input(UInt(64.W))
        val trapTval = Input(UInt(64.W)); val trapReady = Output(Bool()); val trapTarget = Output(UInt(64.W))
        val privilege = Output(UInt(2.W)); val virtualized = Output(Bool()); val interruptPending = Output(Bool())
        val time = Input(UInt(64.W)); val cycle = Output(UInt(64.W)); val instret = Output(UInt(64.W))
        val inhibit = Output(UInt(3.W))
    })
    val system = Module(new MachineSystemUnit(p, experimentalHypervisor = true, guestFiles = 3))
    val imsic = Module(new Imsic(ImsicParams(guestFiles = 3)))
    system.io.start.valid := io.start
    system.io.start.bits.token.index := io.tokenIndex; system.io.start.bits.token.tag := io.tokenTag
    system.io.start.bits.instruction := io.instruction; system.io.start.bits.operand := io.operand
    system.io.start.bits.operand2.get := 0.U; system.io.start.bits.pc := io.pc
    io.ready := system.io.start.ready; system.io.complete.ready := io.completeReady
    io.complete := system.io.complete.valid; io.data := system.io.complete.bits.completion.data
    io.exception := system.io.complete.bits.completion.exception; io.cause := system.io.complete.bits.completion.cause
    io.tval := system.io.complete.bits.completion.tval; io.nextPc := system.io.complete.bits.completion.nextPc
    io.redirect := system.io.complete.bits.redirect
    system.io.acceptedCommits.foreach(_ := io.retired)
    system.io.counterRetire.foreach { retire =>
        retire.valid := io.retire; retire.bits.index := io.retireIndex; retire.bits.tag := io.retireTag
    }
    system.io.hMemory.get.request.ready := false.B; system.io.hMemory.get.response.valid := false.B
    system.io.hMemory.get.response.bits := 0.U.asTypeOf(system.io.hMemory.get.response.bits)
    system.io.hMemoryFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    system.io.imsic.request <> imsic.io.csrRequest; system.io.imsic.response <> imsic.io.csrResponse
    imsic.io.mmio.request.valid := false.B; imsic.io.mmio.request.bits := 0.U.asTypeOf(imsic.io.mmio.request.bits)
    imsic.io.mmio.response.ready := true.B
    system.io.trap.valid := io.trap; system.io.trap.bits.token := 0.U.asTypeOf(system.io.trap.bits.token)
    system.io.trap.bits.pc := io.trapPc; system.io.trap.bits.cause := io.trapCause
    system.io.trap.bits.tval := io.trapTval; system.io.trap.bits.guestFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    io.trapReady := system.io.trapReady; io.trapTarget := system.io.trapTarget
    system.io.externalInterrupt := false.B; system.io.supervisorExternalInterrupt := false.B
    system.io.timerInterrupt := false.B; system.io.guestExternal.get := 0.U
    system.io.guestTopIdentities.get := 0.U; system.io.timeValue := io.time
    system.io.vmFlushReady.get := true.B; system.io.fenceIFlushReady := true.B
    io.privilege := system.io.fetchPrivilege; io.virtualized := system.io.virtualized.get
    io.interruptPending := system.io.interruptPending
    io.cycle := system.basicCounterBank.map(b => BoringUtils.bore(b.io.cycle)).getOrElse(0.U)
    io.instret := system.basicCounterBank.map(b => BoringUtils.bore(b.io.instret)).getOrElse(0.U)
    io.inhibit := system.basicCounterBank.map(b => BoringUtils.bore(b.io.inhibit)).getOrElse(0.U)
}
object GuestCountersSystemGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestCountersSystemGsim, Array("--target-dir", args(0)))
}
object GuestCountersAbsentSystemGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestCountersSystemGsim(false), Array("--target-dir", args(0)))
}

/** Real tile, real scalar fetch, ROB/MSU, programmable ROM/RAM and production common
  * fabric. Every probe is passive. Backpressure is applied only to supported public
  * gates and held scalar handshakes. No synthetic memory response or fake completion.
  */
class GuestCountersPlatformGsim extends Module {
    val boundary = CommonCpuTilePortParams()
    val features = CommonPlatformFeatures(memoryCopyDma = false)
    val cpu = Module(new CommonHypervisorCpuTile(boundary = boundary, ramBytes = 65536, romBytes = 4096,
        mmioRegions = CommonPlatformAbi.cpuMmioRegions(features), basicCounters = true))
    val fabric = Module(new CommonMachineFabric(boundary, features = features,
        ramBytes = 65536, externalDdr = false, romWords = 1024, programmable = true,
        ramResponseDelay = 3, externalUart = false, experimentalGuestFiles = 3))
    val system = cpu.core.core.core.backend.systemUnit.get
    val io = IO(new Bundle {
        val enable = Input(Bool()); val commitEnable = Input(Bool())
        val program = chiselTypeOf(fabric.io.program.get); val ramProgram = chiselTypeOf(fabric.io.ramProgram.get)
        val allowRequest = Input(UInt(2.W)); val allowResponse = Input(UInt(2.W))
        val commit0 = chiselTypeOf(cpu.io.commit0); val commit1 = chiselTypeOf(cpu.io.commit1)
        val trap = chiselTypeOf(cpu.io.trap); val virtualized = Output(Bool()); val privilege = Output(UInt(2.W))
        val cycle = Output(UInt(64.W)); val instret = Output(UInt(64.W)); val inhibit = Output(UInt(3.W))
        val systemStart = Output(Bool()); val systemInstruction = Output(UInt(32.W))
        val systemPc = Output(UInt(64.W)); val systemOperand = Output(UInt(64.W))
        val systemToken = Output(new RobToken(cpu.core.p)); val systemExecute = Output(Bool())
        val systemComplete = Output(Bool())
        val systemData = Output(UInt(64.W)); val systemException = Output(Bool())
        val scalar0Request = Output(Valid(new CommonTileScalarRequest(boundary)))
        val scalar1Request = Output(Valid(new CommonTileScalarRequest(boundary)))
        val scalarRequestReady = Output(UInt(2.W))
        val scalar0Response = Output(Valid(new CommonTileScalarResponse(boundary)))
        val scalar1Response = Output(Valid(new CommonTileScalarResponse(boundary)))
        val scalarResponseReady = Output(UInt(2.W)); val interruptPending = Output(Bool())
        val msiActive = Output(Bool()); val msiError = Output(Bool())
    })
    fabric.io.tile <> cpu.io.bus
    cpu.io.enable := io.enable; cpu.io.commitEnable := io.commitEnable
    fabric.io.program.get := io.program; fabric.io.ramProgram.get := io.ramProgram
    fabric.io.transportCpuEmptySynchronized := true.B; fabric.io.fabricTransportEmpty := true.B
    fabric.io.externalMaintenance.valid := false.B
    fabric.io.externalMaintenance.bits := 0.U.asTypeOf(fabric.io.externalMaintenance.bits)
    fabric.io.timerTick := false.B; fabric.io.sources := 0.U; fabric.io.uartRx := true.B
    def heldGate(valid: Bool, ready: Bool, allow: Bool): Bool = {
        val held = RegInit(false.B); val open = held || allow
        when(valid && open) { held := !ready }
        assert(!held || valid, "counter test source withdrew held offer")
        open
    }
    for (i <- 0 until 2) {
        val c = cpu.io.bus.scalar(i); val f = fabric.io.tile.scalar(i)
        val rq = heldGate(c.request.valid, f.request.ready, io.allowRequest(i))
        val rp = heldGate(f.response.valid, c.response.ready, io.allowResponse(i))
        f.request.valid := c.request.valid && rq; c.request.ready := f.request.ready && rq
        c.response.valid := f.response.valid && rp; f.response.ready := c.response.ready && rp
        Seq(io.scalar0Request, io.scalar1Request)(i).valid := c.request.valid
        Seq(io.scalar0Request, io.scalar1Request)(i).bits := c.request.bits
        Seq(io.scalar0Response, io.scalar1Response)(i).valid := f.response.valid
        Seq(io.scalar0Response, io.scalar1Response)(i).bits := f.response.bits
    }
    io.scalarRequestReady := VecInit(cpu.io.bus.scalar.map(_.request.ready)).asUInt
    io.scalarResponseReady := VecInit(fabric.io.tile.scalar.map(_.response.ready)).asUInt
    io.commit0 := cpu.io.commit0; io.commit1 := cpu.io.commit1; io.trap := cpu.io.trap
    io.virtualized := cpu.io.virtualized; io.privilege := BoringUtils.bore(system.io.fetchPrivilege)
    io.cycle := BoringUtils.bore(system.basicCounterBank.get.io.cycle)
    io.instret := BoringUtils.bore(system.basicCounterBank.get.io.instret)
    io.inhibit := BoringUtils.bore(system.basicCounterBank.get.io.inhibit)
    io.systemStart := BoringUtils.bore(system.io.start.valid) && BoringUtils.bore(system.io.start.ready)
    io.systemInstruction := BoringUtils.bore(system.io.start.bits.instruction)
    io.systemPc := BoringUtils.bore(system.io.start.bits.pc)
    io.systemOperand := BoringUtils.bore(system.io.start.bits.operand)
    io.systemToken := BoringUtils.bore(system.io.start.bits.token)
    io.systemExecute := BoringUtils.bore(system.state) === system.execute
    io.systemComplete := BoringUtils.bore(system.io.complete.valid)
    io.systemData := BoringUtils.bore(system.io.complete.bits.completion.data)
    io.systemException := BoringUtils.bore(system.io.complete.bits.completion.exception)
    io.interruptPending := BoringUtils.bore(system.io.interruptPending)
    io.msiActive := fabric.io.tile.msi.request.valid || cpu.io.bus.msi.response.valid
    io.msiError := fabric.io.msiError
    when(io.program.valid || io.ramProgram.valid) { assert(!io.enable, "program only during cold hold") }
}
object GuestCountersPlatformGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new GuestCountersPlatformGsim, Array("--target-dir", args(0)))
}
