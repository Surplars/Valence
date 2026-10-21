package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink._
import soc.ip.ethernet._

/** Actual GMAC CSR manager with deterministic external status and independent MDIO credits. */
class GmacReadyBatch extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val io = IO(new Bundle {
        val a = Flipped(Decoupled(new TLBundleA(params)))
        val d = Decoupled(new TLBundleD(params))
        val mdioReady = Input(UInt(4.W))
        val mdioResponse = Input(UInt(4.W))
        val busy = Input(UInt(4.W))
        val cmdValid = Output(UInt(4.W))
        val cmdPayload = Output(UInt(108.W))
        val controls = Output(UInt(16.W))
        val macs = Output(UInt(192.W))
        val rxStop = Output(UInt(4.W))
        val restart = Output(UInt(4.W))
        val irq = Output(UInt(4.W))
    })
    val dut = Module(new TileLinkGmacControl(GmacParams(
        ports = Seq.fill(4)(Rgmii1G), rxAdmissionStop = true,
        triSpeedExtensions = true, externalMdio = true), params))
    dut.io.tl.a <> io.a
    io.d <> dut.io.tl.d
    dut.io.tl.b.ready := true.B
    dut.io.tl.c.valid := false.B
    dut.io.tl.c.bits := 0.U.asTypeOf(dut.io.tl.c.bits)
    dut.io.tl.e.valid := false.B
    dut.io.tl.e.bits := 0.U.asTypeOf(dut.io.tl.e.bits)
    for (n <- 0 until 4) {
        val p = dut.io.ports(n)
        p.linkUp := true.B
        p.txBusy := io.busy(n)
        p.rxBusy := io.busy(n)
        p.rxStopDrained.get := true.B
        p.events := 0.U
        p.txBytes := 0.U
        p.rxBytes := 0.U
        p.mdioIn := true.B
        p.mdioCommand.get.ready := io.mdioReady(n)
        p.mdioResponse.get.valid := io.mdioResponse(n)
        p.mdioResponse.get.bits.data := (0xc000 + n).U
        p.mdioResponse.get.bits.noAck := (n % 2 == 1).B
        p.mediaStatus.get := (0x9000 + n).U
        p.phyCounters.get := VecInit(Seq.tabulate(3)(i => (0xa000 + n * 16 + i).U(64.W)))
        p.diagnosticDeltas.get := 0.U.asTypeOf(p.diagnosticDeltas.get)
    }
    io.cmdValid := VecInit(dut.io.ports.map(_.mdioCommand.get.valid)).asUInt
    io.cmdPayload := Cat(dut.io.ports.reverse.map { p =>
        val c = p.mdioCommand.get.bits
        Cat(c.register, c.phy, c.write, c.data)
    })
    io.controls := Cat(dut.io.ports.reverse.map(p => Cat(p.broadcastEnable, p.promiscuous, p.rxEnable, p.txEnable)))
    io.macs := Cat(dut.io.ports.reverse.map(_.macAddress))
    io.rxStop := VecInit(dut.io.ports.map(_.rxStopRequest.get)).asUInt
    io.restart := VecInit(dut.io.ports.map(_.restartPhy.get)).asUInt
    io.irq := dut.io.irq
}

object GmacReadyBatchMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new GmacReadyBatch, Array("--target-dir", args.head),
        Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info",
            "-default-layer-specialization=disable"))
}
