package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.platform._
import soc.core.inorder.FiveStageRetire

/** Real full-capacity I1 tile + shared Home/fabric, single clock and internal RAM.
  * No clock-gating, independent-clock CDC, DRP or FPGA timing qualification.
  */
class CommonI1RuntimeEpochFixture extends Module {
    val boundary = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true)
    val p = CommonCpuProfile.I1.i1
    val io = IO(new Bundle {
        val start = Input(Bool())
        val program = Input(Valid(new Bundle { val index = UInt(6.W); val data = UInt(32.W) }))
        val prepare = Flipped(Decoupled(UInt(8.W)))
        val resume = Flipped(Decoupled(UInt(8.W)))
        val cancel = Flipped(Decoupled(UInt(8.W)))
        val complete = Decoupled(new CommonRuntimeCompletion(boundary))
        val externalStop = Input(Bool())
        val holdReleaseAck = Input(Bool())
        val holdCompletion = Input(Bool())
        val releaseAckBlocked = Output(Bool())
        val completionBlocked = Output(Bool())
        val tileHeld = Valid(UInt(8.W))
        val fabricHeld = Valid(UInt(8.W))
        val retire = Valid(new FiveStageRetire(p))
        val trap = Output(Bool())
        val releaseBeats = Output(UInt(32.W))
        val coherentAcquires = Output(UInt(32.W))
        val fabricIdle = Output(Bool())
    })
    val started = RegInit(false.B)
    when(io.start) { started := true.B }
    when(started) { assert(io.start, "fixture CPU reset may not cancel accepted owners") }
    val tile = withReset(reset.asBool || !io.start) { Module(new CommonI1CpuTile(p, boundary, externalQuiesce = true)) }
    tile.io.quiesceRequest.get := io.externalStop
    val fabric = Module(new CommonMachineFabric(boundary = boundary,
        features = CommonPlatformFeatures(ethernetControl = false, networkDma = false,
            jtagDownload = false, clockManagement = false), ramBytes = 65536,
        externalDdr = false, romWords = 64, programmable = true, externalUart = false,
        ramResponseDelay = 7))
    fabric.io.tile <> tile.io.bus
    // Test-only transparent backpressure on actual ReleaseAck and epoch replies.
    // Payload and accepted ownership are untouched; no response is manufactured.
    val releaseAckBlocked = (0 until boundary.coherentClients).map { i =>
        val source = fabric.io.tile.coherent(i).d
        val destination = tile.io.bus.coherent(i).d
        val allow = !io.holdReleaseAck || source.bits.opcode =/= 6.U
        destination.valid := source.valid && allow
        source.ready := destination.ready && allow
        source.valid && !allow
    }
    io.releaseAckBlocked := releaseAckBlocked.reduce(_ || _)
    tile.io.bus.fabricDrainedEpoch.valid := fabric.io.tile.fabricDrainedEpoch.valid && !io.holdCompletion
    fabric.io.tile.fabricDrainedEpoch.ready := tile.io.bus.fabricDrainedEpoch.ready && !io.holdCompletion
    io.completionBlocked := fabric.io.tile.fabricDrainedEpoch.valid && io.holdCompletion
    fabric.io.program.get := io.program
    fabric.io.ramProgram.get.valid := false.B
    fabric.io.ramProgram.get.bits := 0.U.asTypeOf(fabric.io.ramProgram.get.bits)
    fabric.io.transportCpuEmptySynchronized := true.B // no CDC queues in this fixture
    fabric.io.fabricTransportEmpty := true.B
    fabric.io.externalMaintenance.valid := io.prepare.valid
    fabric.io.externalMaintenance.bits := 0.U.asTypeOf(fabric.io.externalMaintenance.bits)
    fabric.io.externalMaintenance.bits.epoch := io.prepare.bits
    io.prepare.ready := fabric.io.externalMaintenance.ready
    fabric.io.runtimeResume.get <> io.resume
    fabric.io.runtimeCancel.get <> io.cancel
    io.complete <> fabric.io.runtimeComplete.get
    io.tileHeld := tile.io.runtimeHeld.get
    io.fabricHeld := fabric.io.runtimeHeld.get
    io.retire := tile.io.retire
    io.trap := tile.io.trapTaken
    io.fabricIdle := fabric.io.allObligationsIdle
    fabric.io.timerTick := false.B
    fabric.io.sources := 0.U
    fabric.io.uartRx := true.B
    val releases = RegInit(0.U(32.W))
    val acquires = RegInit(0.U(32.W))
    releases := releases + PopCount(tile.io.bus.coherent.map(c => c.c.fire && c.c.bits.opcode === 7.U))
    acquires := acquires + PopCount(tile.io.bus.coherent.map(_.a.fire))
    io.releaseBeats := releases; io.coherentAcquires := acquires
}
object CommonI1RuntimeEpochMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new CommonI1RuntimeEpochFixture, Array("--target-dir", args(0)))
}
object CommonI1RuntimeEpochNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonI1RuntimeEpochFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
