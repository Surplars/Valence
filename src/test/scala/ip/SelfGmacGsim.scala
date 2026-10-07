package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._

class EthernetCrc32Gsim extends Module {
    val io = IO(new Bundle {
        val state = Input(UInt(32.W))
        val data = Input(UInt(64.W))
        val keep = Input(UInt(8.W))
        val next = Output(UInt(32.W))
        val byteNext = Output(UInt(32.W))
        val legal = Output(Bool())
    })
    val (next, legal) = EthernetCrc32.prefix(io.state, io.data, io.keep, 8)
    io.next := next
    io.legal := legal
    io.byteNext := EthernetCrc32.update(io.state, io.data(7, 0), 1)
}
object EthernetCrc32GsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetCrc32Gsim, Array("--target-dir", args.head))
}
object MdioClause22GsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MdioClause22(clockHz = 20000000), Array("--target-dir", args.head))
}
object TileLinkGmacControlGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkGmacControl(GmacParams(controlClockHz = 20000000)),
        Array("--target-dir", args.head))
}
object SelfGmacFoundationRtlMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new TileLinkGmacControl(), Array("--target-dir", args.head + "/control"),
        Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info"))
    ChiselStage.emitSystemVerilogFile(new EthernetCrc32Gsim, Array("--target-dir", args.head + "/crc"),
        Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info"))
}
