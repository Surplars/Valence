package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.ip.bus.{RegisterPort, RegisterResponse}

/** Actual production router, with independent retained-response test endpoints. */
class I1PeripheralDecodeFixture(cuts: Boolean, disabled: Boolean) extends Module {
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val allow = Input(UInt(8.W))
        val forwarded = Output(UInt(8.W))
        val address = Output(UInt(64.W))
        val data = Output(UInt(64.W))
        val write = Output(Bool())
        val size = Output(UInt(3.W))
        val mask = Output(UInt(8.W))
    })
    val core = FiveStageConfig(resetVector = BigInt("10000", 16),
        cacheableBase = BigInt("80200000", 16), cacheableBytes = BigInt(1) << 31,
        instructionCacheBytes = 256, dataCacheBytes = 256, coherentCaches = true,
        withUser = true, withSupervisor = true,
        pipelineProfile = if (cuts) "fpga8" else "compact5", fpgaTimingCuts = cuts)
    val p = FiveStageSocConfig(core = core, withUart = !disabled, withTimer = !disabled,
        withInterrupts = !disabled, withJtagLoader = !disabled,
        managedPeripherals = !disabled, withNetwork = !disabled)
    val dut = Module(new FiveStagePeripherals(p))
    dut.io.registers <> io.control
    dut.io.uartRx := true.B; dut.io.externalIrq := false.B
    dut.io.ddrReady := true.B; dut.io.resetFault := false.B
    dut.io.externalUartIrq.foreach(_ := false.B)
    dut.io.networkIrqs.foreach(_ := 0.U)
    val forwards = Wire(Vec(8, Bool()))
    forwards.foreach(_ := false.B)
    val ports = Seq(dut.io.externalUart -> 0, Some(dut.io.loaderControl) -> 4,
        dut.io.gmacControl -> 5, dut.io.cmuControl -> 6, dut.io.networkDmaControl -> 7)
        .flatMap { case (port, number) => port.map(ip => (ip, number)) }
    for ((ip, number) <- ports) {
        val replies = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
        ip.request.ready := replies.io.enq.ready && io.allow(number)
        replies.io.enq.valid := ip.request.valid && io.allow(number)
        replies.io.enq.bits.error := false.B
        replies.io.enq.bits.data := ip.request.bits.address ^ (BigInt(number) << 56).U(64.W)
        ip.response <> replies.io.deq
        forwards(number) := ip.request.fire
    }
    io.forwarded := forwards.asUInt
    // Observe the ACTUAL selected child request, not a copy of the input.
    // A router payload mutation must therefore be visible to the byte oracle.
    val observed = Mux1H(ports.map { case (ip, number) => forwards(number) -> ip.request.bits })
    io.address := observed.address
    io.data := observed.data
    io.write := observed.write
    io.size := observed.size
    io.mask := observed.byteEnable
}

object I1PeripheralDecodeMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PeripheralDecodeFixture(args.contains("--timing-cuts"),
        args.contains("--disabled")), Array("--target-dir", args.head))
}
