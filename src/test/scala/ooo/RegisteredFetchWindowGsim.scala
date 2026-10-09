package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class ScalarWindowPacket extends Bundle {
    val valid = Bool()
    val data = UInt(64.W)
    val access = UInt(2.W)
    val page = UInt(2.W)
}

/** Scalarized GSIM boundary only; address/context logic is the production module. */
class RegisteredFetchWindowGsim(capacity: Int, previousPacket: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val queryBase = Input(UInt(64.W))
        val readBase = Input(UInt(64.W))
        val queryContext = Input(UInt(3.W))
        val readContext = Input(UInt(3.W))
        val invalidate = Input(Bool())
        val query0 = Input(new ScalarWindowPacket)
        val query1 = Input(new ScalarWindowPacket)
        val query2 = Input(new ScalarWindowPacket)
        val query3 = Input(new ScalarWindowPacket)
        val query4 = Input(new ScalarWindowPacket)
        val packet0 = Output(new ScalarWindowPacket)
        val packet1 = Output(new ScalarWindowPacket)
        val packet2 = Output(new ScalarWindowPacket)
        val pcOffset = Input(UInt(3.W))
        val alignedValid = Output(UInt(4.W))
        val alignedAccess = Output(UInt(4.W))
        val alignedPage = Output(UInt(4.W))
        val instruction0 = Output(UInt(32.W))
        val instruction1 = Output(UInt(32.W))
        val instruction2 = Output(UInt(32.W))
        val instruction3 = Output(UInt(32.W))
        val fault0 = Output(UInt(5.W))
        val fault1 = Output(UInt(5.W))
        val fault2 = Output(UInt(5.W))
        val fault3 = Output(UInt(5.W))
    })
    val window = Module(new RegisteredFetchWindow(capacity, previousPacket = previousPacket))
    window.io.queryBase := io.queryBase
    window.io.readBase := io.readBase
    window.io.queryContext := io.queryContext
    window.io.readContext := io.readContext
    window.io.invalidate := io.invalidate
    val queries = Seq(io.query0, io.query1, io.query2, io.query3, io.query4)
    for (row <- 0 until capacity) {
        window.io.query(row).valid := queries(row).valid
        window.io.query(row).bits.data := queries(row).data
        window.io.query(row).bits.accessFaults := queries(row).access
        window.io.query(row).bits.pageFaults := queries(row).page
    }
    for ((port, row) <- Seq(io.packet0, io.packet1, io.packet2).zipWithIndex) {
        port.valid := window.io.packets(row).valid
        port.data := window.io.packets(row).bits.data
        port.access := window.io.packets(row).bits.accessFaults
        port.page := window.io.packets(row).bits.pageFaults
    }
    // Exercise the production packet-to-instruction contract, including a
    // 32-bit instruction spanning history packet0 and primary packet1.
    val width = if (capacity == 3) 2 else 4
    val alignment = Module(new ParallelFetchAlignment(width))
    alignment.io.pcOffset := io.pcOffset
    alignment.io.present := VecInit(window.io.packets.map(_.valid)).asUInt
    for (row <- 0 until 3) {
        alignment.io.packets(row) := window.io.packets(row).bits.data
        alignment.io.errors(row) := window.io.packets(row).bits.accessFaults
        alignment.io.pages(row) := window.io.packets(row).bits.pageFaults
    }
    io.alignedValid := VecInit(alignment.io.instructions.map(_.valid)).asUInt
    io.alignedAccess := alignment.io.errorsOut.asUInt
    io.alignedPage := alignment.io.pagesOut.asUInt
    for ((data, lane) <- Seq(io.instruction0, io.instruction1, io.instruction2, io.instruction3).zipWithIndex)
        data := (if (lane < width) alignment.io.instructions(lane).bits else 0.U)
    for ((fault, lane) <- Seq(io.fault0, io.fault1, io.fault2, io.fault3).zipWithIndex)
        fault := (if (lane < width) alignment.io.faultOffsets(lane) else 0.U)
}

object RegisteredFetchWindowGsimMain extends App {
    require(args.length == 2 || args.length == 3, "expected output directory, capacity, optional previousPacket")
    ChiselStage.emitCHIRRTLFile(new RegisteredFetchWindowGsim(args(1).toInt, args.lift(2).exists(_.toBoolean)),
        Array("--target-dir", args.head))
}
