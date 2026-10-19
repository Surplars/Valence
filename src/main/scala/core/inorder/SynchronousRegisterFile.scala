package soc.core.inorder

import chisel3._
import chisel3.util._

/** Two synchronous 1R1W RAM replicas, not a 32-way FF mux. RAM payload is not reset.
  * A 32-bit bitmap supplies deterministic unwritten-register reads. Same-edge WB/ID collisions
  * bypass explicitly. Response holding protects EX stalls from disabled-read memory semantics.
  */
class SynchronousRegisterFile(xlen: Int, storage: String = "block") extends Module {
    require(Set(32, 64).contains(xlen))
    require(Set("block", "distributed", "auto").contains(storage))
    // CIRCT supports AttributeAnnotation on modules, not smem operations. Vivado UG912
    // allows RAM_STYLE on hierarchy; the actual generated RAM submodule is audited at export.
    if (storage != "auto") {
        chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
            s"ram_style = \"$storage\"")))
    }
    val io = IO(new Bundle {
        val readEnable = Input(Bool())
        val rs1 = Input(UInt(5.W))
        val rs2 = Input(UInt(5.W))
        val data1 = Output(UInt(xlen.W))
        val data2 = Output(UInt(xlen.W))
        val writeEnable = Input(Bool())
        val rd = Input(UInt(5.W))
        val writeData = Input(UInt(xlen.W))
    })
    private val initialized = RegInit(0.U(32.W))
    private val write = io.writeEnable && io.rd =/= 0.U
    when(write) { initialized := initialized | UIntToOH(io.rd, 32) }
    private val responseValid = RegNext(io.readEnable, false.B)
    private val collisionData = RegEnable(io.writeData, io.readEnable && write)
    for ((address, result) <- Seq(io.rs1 -> io.data1, io.rs2 -> io.data2)) {
        // Undefined RDW is safe because collisions are bypassed; also matches pinned GSIM syntax.
        val bank = SyncReadMem(32, UInt(xlen.W))
        when(write) { bank.write(io.rd, io.writeData) }
        val readData = bank.read(address, io.readEnable)
        val collision = RegEnable(write && io.rd === address, false.B, io.readEnable)
        val nonzero = RegEnable(address =/= 0.U, false.B, io.readEnable)
        val defined = RegEnable(initialized(address) || (write && io.rd === address), false.B, io.readEnable)
        val response = Mux(nonzero && defined, Mux(collision, collisionData, readData), 0.U)
        val held = Reg(UInt(xlen.W))
        when(responseValid) { held := response }
        result := Mux(responseValid, response, held)
    }
}
