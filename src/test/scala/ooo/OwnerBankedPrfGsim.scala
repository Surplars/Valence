package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Both real RAM and an independent register representation receive identical
  * scalar ports. Host is the data oracle; the legacy side is a second check.
  */
class OwnerBankedPrfPorts extends Bundle {
        val valid0 = Input(Bool()); val valid1 = Input(Bool())
        val address0 = Input(UInt(8.W)); val address1 = Input(UInt(8.W))
        val word0 = Input(UInt(64.W)); val word1 = Input(UInt(64.W))
        val read0 = Input(UInt(8.W)); val read1 = Input(UInt(8.W))
        val read2 = Input(UInt(8.W)); val read3 = Input(UInt(8.W))
        val result0 = Output(UInt(64.W)); val result1 = Output(UInt(64.W))
        val result2 = Output(UInt(64.W)); val result3 = Output(UInt(64.W))
        val legacy0 = Output(UInt(64.W)); val legacy1 = Output(UInt(64.W))
        val legacy2 = Output(UInt(64.W)); val legacy3 = Output(UInt(64.W))
}
class OwnerBankedPrfSlice(entries: Int) extends Module {
    val io = IO(new OwnerBankedPrfPorts)
    val dut = Module(new OwnerBankedPhysicalRegisterFile(entries, 4))
    val bits = log2Ceil(entries)
    val writeAddress = Seq(io.address0, io.address1)
    val writeValid = Seq(io.valid0, io.valid1)
    val writeData = Seq(io.word0, io.word1)
    val legacy = RegInit(VecInit(Seq.fill(entries)(0.U(64.W))))
    for (lane <- 0 until 2) {
        dut.io.write(lane).valid := writeValid(lane)
        dut.io.write(lane).bits.address := writeAddress(lane)(bits - 1, 0)
        dut.io.write(lane).bits.data := writeData(lane)
        val live = writeValid(lane) && writeAddress(lane) =/= 0.U && writeAddress(lane) < entries.U
        val safe = Mux(live, writeAddress(lane), 0.U)
        when(live) { legacy(safe) := writeData(lane) }
    }
    val addresses = Seq(io.read0, io.read1, io.read2, io.read3)
    val results = Seq(io.result0, io.result1, io.result2, io.result3)
    val references = Seq(io.legacy0, io.legacy1, io.legacy2, io.legacy3)
    for (port <- 0 until 4) {
        dut.io.address(port) := addresses(port)(bits - 1, 0)
        results(port) := dut.io.data(port)
        references(port) := Mux(addresses(port) < entries.U,
            legacy(Mux(addresses(port) < entries.U, addresses(port), 0.U)), 0.U)
    }
}
/** One generated small model contains the capacity matrix. Only the selected
  * slice receives writes; all reset together. No firmware or data oracle in RTL.
  */
class OwnerBankedPrfGsim extends Module {
    val io = IO(new OwnerBankedPrfPorts)
    val select = IO(Input(UInt(2.W)))
    val slices = Seq(48, 64, 128).map(n => Module(new OwnerBankedPrfSlice(n)))
    for ((slice, index) <- slices.zipWithIndex) {
        slice.io.valid0 := io.valid0 && select === index.U
        slice.io.valid1 := io.valid1 && select === index.U
        slice.io.address0 := io.address0; slice.io.address1 := io.address1
        slice.io.word0 := io.word0; slice.io.word1 := io.word1
        slice.io.read0 := io.read0; slice.io.read1 := io.read1
        slice.io.read2 := io.read2; slice.io.read3 := io.read3
    }
    io.result0 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.result0))
    io.result1 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.result1))
    io.result2 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.result2))
    io.result3 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.result3))
    io.legacy0 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.legacy0))
    io.legacy1 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.legacy1))
    io.legacy2 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.legacy2))
    io.legacy3 := Mux1H(slices.indices.map(i => (select === i.U) -> slices(i).io.legacy3))
}
object OwnerBankedPrfGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new OwnerBankedPrfGsim, Array("--target-dir", args.head))
}
