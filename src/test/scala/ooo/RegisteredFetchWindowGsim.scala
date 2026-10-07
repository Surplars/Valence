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
class RegisteredFetchWindowGsim(capacity: Int) extends Module {
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
    })
    val window = Module(new RegisteredFetchWindow(capacity))
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
}

object RegisteredFetchWindowGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RegisteredFetchWindowGsim(args(1).toInt),
        Array("--target-dir", args.head))
}
