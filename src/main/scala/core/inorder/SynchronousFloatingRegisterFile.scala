package soc.core.inorder

import chisel3._
import chisel3.util._

/** Three 1R1W synchronous RAM replicas for fused operands; f0 is a real register.
  * Architectural writes only at WB. No payload reset. Explicit RDW and unwritten-zero qualification.
  * FP issue is serial in the first integration: no speculative FP state or mixed-bank alias.
  */
class SynchronousFloatingRegisterFile(flen: Int, storage: String = "block") extends Module {
    require(Set(32, 64).contains(flen))
    require(Set("block", "distributed", "auto").contains(storage))
    if (storage != "auto") {
        chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
            "ram_style = \"" + storage + "\"")))
    }
    val io = IO(new Bundle {
        val readEnable = Input(Bool())
        val rs1 = Input(UInt(5.W)); val rs2 = Input(UInt(5.W)); val rs3 = Input(UInt(5.W))
        val data1 = Output(UInt(flen.W)); val data2 = Output(UInt(flen.W)); val data3 = Output(UInt(flen.W))
        val writeEnable = Input(Bool()); val rd = Input(UInt(5.W)); val writeData = Input(UInt(flen.W))
    })
    val initialized = RegInit(0.U(32.W))
    when(io.writeEnable) { initialized := initialized | UIntToOH(io.rd, 32) }
    val responseValid = RegNext(io.readEnable, false.B)
    val collisionData = RegEnable(io.writeData, io.readEnable && io.writeEnable)
    for ((address, output) <- Seq(io.rs1 -> io.data1, io.rs2 -> io.data2, io.rs3 -> io.data3)) {
        val fpBank = SyncReadMem(32, UInt(flen.W))
        when(io.writeEnable) { fpBank.write(io.rd, io.writeData) }
        val payload = fpBank.read(address, io.readEnable)
        val collision = RegEnable(io.writeEnable && io.rd === address, false.B, io.readEnable)
        val defined = RegEnable(initialized(address) || (io.writeEnable && io.rd === address),
            false.B, io.readEnable)
        val response = Mux(defined, Mux(collision, collisionData, payload), 0.U)
        val held = Reg(UInt(flen.W))
        when(responseValid) { held := response }
        output := Mux(responseValid, response, held)
    }
}
