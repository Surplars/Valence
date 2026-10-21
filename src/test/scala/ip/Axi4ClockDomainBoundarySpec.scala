package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.axi.Axi4ClockDomainBoundary

class Axi4ClockDomainBoundarySpec extends AnyFunSuite {
    test("five complete independent AXI channels preserve wide address and ID fields") {
        for ((address, id) <- Seq((32, 1), (64, 8))) {
            val fir = ChiselStage.emitCHIRRTL(new Axi4ClockDomainBoundary(address, id, 4))
            assert(fir.linesIterator.count(_.contains(" of HeldResponseCdcDataFifo")) == 5)
            for (field <- Seq("aw", "w", "b", "ar", "r", "lock", "cache", "prot", "qos", "last", "resp")) {
                assert(fir.contains(field))
            }
            assert(fir.contains("fabricTransportEmpty") && fir.contains("ddrTransportEmpty"))
            assert(!fir.contains("quiesce") && !fir.contains("ClockRateControl"))
        }
    }
    test("low-clock platform cannot silently omit its fixed-domain crossings") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new soc.platform.CommonMachinePlatform(
                soc.platform.CommonCpuProfile.named("i1", "boot50-static")))
        }
        for (kind <- Seq("i1", "a1")) {
            val fir = ChiselStage.emitCHIRRTL(new soc.platform.CommonMachinePlatform(
                soc.platform.CommonCpuProfile.named(kind, "boot50-static"), hardwareClocks = false,
                independentDdrClock = true, independentTimebaseClock = true, independentDebugClock = true))
            for (module <- Seq("Axi4ClockDomainBoundary", "FixedTimebaseBoundary", "DebugDmiClockBoundary")) {
                assert(fir.contains(s"of $module"))
            }
        }
    }
    test("invalid capacity is rejected") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new Axi4ClockDomainBoundary(depth = 3)) }
    }
}

object Axi4ClockDomainBoundaryMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new Axi4ClockDomainBoundary(32, 4, 4),
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

/** Bit-exact channel conservation fixture. Synthetic independent channel payloads
  * are not a memory model or evidence of real AXI transaction-owner drain.
  */
class Axi4CdcFixture extends chisel3.RawModule {
    import chisel3._
    import chisel3.util._
    val fabricClock = IO(Input(Clock())); val ddrClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val inValid = IO(Input(UInt(5.W))); val inReady = IO(Output(UInt(5.W)))
    val outValid = IO(Output(UInt(5.W))); val outReady = IO(Input(UInt(5.W)))
    val inData = IO(Input(Vec(5, UInt(64.W)))); val inMeta = IO(Input(Vec(5, UInt(16.W))))
    val outData = IO(Output(Vec(5, UInt(64.W)))); val outMeta = IO(Output(Vec(5, UInt(16.W))))
    val empty = IO(Output(UInt(2.W))); val link = IO(Output(UInt(2.W)))
    val dut = Module(new Axi4ClockDomainBoundary(32, 4, 4))
    dut.fabricClock := fabricClock; dut.ddrClock := ddrClock; dut.commonColdReset := commonColdReset
    val ready = Wire(Vec(5, Bool())); val valid = Wire(Vec(5, Bool()))
    def lane[T <: Data](n: Int, input: DecoupledIO[T], output: DecoupledIO[T]): Unit = {
        input.valid := inValid(n); input.bits := Cat(inMeta(n), inData(n)).asTypeOf(input.bits)
        ready(n) := input.ready; valid(n) := output.valid; output.ready := outReady(n)
        val bits = output.bits.asUInt.pad(80)
        outData(n) := bits(63, 0); outMeta(n) := bits(79, 64)
    }
    lane(0, dut.fabric.aw, dut.ddr.aw); lane(1, dut.fabric.w, dut.ddr.w)
    lane(2, dut.ddr.b, dut.fabric.b); lane(3, dut.fabric.ar, dut.ddr.ar)
    lane(4, dut.ddr.r, dut.fabric.r)
    inReady := ready.asUInt; outValid := valid.asUInt
    empty := Cat(dut.ddrTransportEmpty, dut.fabricTransportEmpty)
    link := Cat(dut.ddrLinkReady, dut.fabricLinkReady)
}
class Axi4CdcSameClock extends chisel3.Module {
    import chisel3._
    val dut = Module(new Axi4CdcFixture)
    dut.fabricClock := clock; dut.ddrClock := clock; dut.commonColdReset := reset.asAsyncReset
    val inValid = IO(Input(UInt(5.W))); val inReady = IO(Output(UInt(5.W)))
    val outValid = IO(Output(UInt(5.W))); val outReady = IO(Input(UInt(5.W)))
    val inData = Seq.tabulate(5)(n => IO(Input(UInt(64.W))).suggestName(s"inData$n"))
    val inMeta = Seq.tabulate(5)(n => IO(Input(UInt(16.W))).suggestName(s"inMeta$n"))
    val outData = Seq.tabulate(5)(n => IO(Output(UInt(64.W))).suggestName(s"outData$n"))
    val outMeta = Seq.tabulate(5)(n => IO(Output(UInt(16.W))).suggestName(s"outMeta$n"))
    val empty = IO(Output(UInt(2.W))); val link = IO(Output(UInt(2.W)))
    dut.inValid := inValid; inReady := dut.inReady; outValid := dut.outValid; dut.outReady := outReady
    for (n <- 0 until 5) {
        dut.inData(n) := inData(n); dut.inMeta(n) := inMeta(n)
        outData(n) := dut.outData(n); outMeta(n) := dut.outMeta(n)
    }
    empty := dut.empty; link := dut.link
}
object Axi4CdcSameClockMain extends App {
    ChiselStage.emitCHIRRTLFile(new Axi4CdcSameClock, Array("--target-dir", args(0)))
}
object Axi4CdcFixtureMain extends App {
    ChiselStage.emitSystemVerilogFile(new Axi4CdcFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
