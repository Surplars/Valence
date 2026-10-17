package soc.core.inorder

import chisel3._
import chisel3.util._

/** RV32/64 integer C expansion in ID: bit wiring/muxes, no arithmetic or sixth RF stage.
  * FP encodings stay illegal because this core has no F/D. HINTs retain their no-state-change semantics.
  * Architectural trace/tval keeps the original 16-bit instruction, not this expanded control word.
  */
class FiveStageCompressed(xlen: Int, withF: Boolean = false, withD: Boolean = false) extends Module {
    require(xlen == 32 || xlen == 64)
    require(!withD || withF)
    val io = IO(new Bundle {
        val instruction = Input(UInt(16.W))
        val expanded = Output(UInt(32.W))
        val legal = Output(Bool())
    })
    val c = io.instruction
    val rd = c(11, 7); val rs2 = c(6, 2)
    val prime1 = Cat("b01".U(2.W), c(9, 7)); val prime2 = Cat("b01".U(2.W), c(4, 2))
    def sign(v: UInt, bits: Int): UInt = Cat(Fill(bits - v.getWidth, v(v.getWidth - 1)), v)
    def imm(v: UInt, rs: UInt, f: Int, dest: UInt, opcode: Int = 0x13): UInt =
        Cat(v(11, 0), rs, f.U(3.W), dest, opcode.U(7.W))
    def reg(f7: Int, right: UInt, left: UInt, f3: Int, dest: UInt, opcode: Int = 0x33): UInt =
        Cat(f7.U(7.W), right, left, f3.U(3.W), dest, opcode.U(7.W))
    def store(v: UInt, right: UInt, left: UInt, f: Int, opcode: Int = 0x23): UInt =
        Cat(v(11, 5), right, left, f.U(3.W), v(4, 0), opcode.U(7.W))
    def jump(v: UInt, dest: UInt): UInt =
        Cat(v(20), v(10, 1), v(11), v(19, 12), dest, "h6f".U(7.W))
    def branch(v: UInt, left: UInt, f: Int): UInt =
        Cat(v(12), v(10, 5), 0.U(5.W), left, f.U(3.W), v(4, 1), v(11), "h63".U(7.W))
    val small = sign(Cat(c(12), c(6, 2)), 12)
    val shamt = Cat(0.U(6.W), c(12), c(6, 2))
    val jumpImmediate = sign(Cat(c(12), c(8), c(10, 9), c(6), c(7), c(2), c(11), c(5, 3), 0.U(1.W)), 21)
    val branchImmediate = sign(Cat(c(12), c(6, 5), c(2), c(11, 10), c(4, 3), 0.U(1.W)), 13)
    val lwOffset = Cat(c(5), c(12, 10), c(6), 0.U(2.W)).pad(12)
    val ldOffset = Cat(c(6, 5), c(12, 10), 0.U(3.W)).pad(12)
    io.expanded := 0.U; io.legal := false.B
    switch(c(1, 0)) {
        is(0.U) {
            switch(c(15, 13)) {
                is(0.U) {
                    val offset = Cat(c(10, 7), c(12, 11), c(5), c(6), 0.U(2.W)).pad(12)
                    io.expanded := imm(offset, 2.U(5.W), 0, prime2); io.legal := offset =/= 0.U
                }
                is(2.U) { io.expanded := imm(lwOffset, prime1, 2, prime2, 3); io.legal := true.B }
                is(1.U) { io.expanded := imm(ldOffset, prime1, 3, prime2, 7); io.legal := withD.B }
                is(5.U) { io.expanded := store(ldOffset, prime2, prime1, 3, 0x27); io.legal := withD.B }
                is(3.U) {
                    io.expanded := imm(ldOffset, prime1, 3, prime2, 3); io.legal := (xlen == 64).B
                }
                is(6.U) { io.expanded := store(lwOffset, prime2, prime1, 2); io.legal := true.B }
                is(7.U) {
                    io.expanded := store(ldOffset, prime2, prime1, 3); io.legal := (xlen == 64).B
                }
            }
        }
        is(1.U) {
            switch(c(15, 13)) {
                is(0.U) { io.expanded := imm(small, rd, 0, rd); io.legal := true.B }
                is(1.U) {
                    if (xlen == 32) { io.expanded := jump(jumpImmediate, 1.U(5.W)); io.legal := true.B }
                    else { io.expanded := imm(small, rd, 0, rd, 0x1b); io.legal := rd =/= 0.U }
                }
                is(2.U) { io.expanded := imm(small, 0.U(5.W), 0, rd); io.legal := true.B }
                is(3.U) {
                    val offset = sign(Cat(c(12), c(4, 3), c(5), c(2), c(6), 0.U(4.W)), 12)
                    when(rd === 2.U) {
                        io.expanded := imm(offset, rd, 0, rd); io.legal := offset =/= 0.U
                    }.otherwise {
                        io.expanded := Cat(sign(Cat(c(12), c(6, 2)), 20), rd, "h37".U(7.W))
                        io.legal := Cat(c(12), c(6, 2)) =/= 0.U
                    }
                }
                is(4.U) {
                    switch(c(11, 10)) {
                        is(0.U) {
                            io.expanded := imm(shamt, prime1, 5, prime1)
                            io.legal := (xlen == 64).B || !c(12)
                        }
                        is(1.U) {
                            io.expanded := imm(shamt | "h400".U, prime1, 5, prime1)
                            io.legal := (xlen == 64).B || !c(12)
                        }
                        is(2.U) { io.expanded := imm(small, prime1, 7, prime1); io.legal := true.B }
                        is(3.U) {
                            when(!c(12)) {
                                io.legal := true.B
                                io.expanded := MuxLookup(c(6, 5), reg(32, prime2, prime1, 0, prime1))(Seq(
                                    1.U -> reg(0, prime2, prime1, 4, prime1),
                                    2.U -> reg(0, prime2, prime1, 6, prime1),
                                    3.U -> reg(0, prime2, prime1, 7, prime1)))
                            }.otherwise {
                                io.legal := (xlen == 64).B && c(6, 5) <= 1.U
                                io.expanded := Mux(c(6, 5) === 0.U, reg(32, prime2, prime1, 0, prime1, 0x3b),
                                    reg(0, prime2, prime1, 0, prime1, 0x3b))
                            }
                        }
                    }
                }
                is(5.U) { io.expanded := jump(jumpImmediate, 0.U(5.W)); io.legal := true.B }
                is(6.U) { io.expanded := branch(branchImmediate, prime1, 0); io.legal := true.B }
                is(7.U) { io.expanded := branch(branchImmediate, prime1, 1); io.legal := true.B }
            }
        }
        is(2.U) {
            switch(c(15, 13)) {
                is(0.U) {
                    io.expanded := imm(shamt, rd, 1, rd); io.legal := (xlen == 64).B || !c(12)
                }
                is(2.U) {
                    val offset = Cat(c(3, 2), c(12), c(6, 4), 0.U(2.W)).pad(12)
                    io.expanded := imm(offset, 2.U(5.W), 2, rd, 3); io.legal := rd =/= 0.U
                }
                is(3.U) {
                    val offset = Cat(c(4, 2), c(12), c(6, 5), 0.U(3.W)).pad(12)
                    io.expanded := imm(offset, 2.U(5.W), 3, rd, 3); io.legal := (xlen == 64).B && rd =/= 0.U
                }
                is(4.U) {
                    io.legal := true.B
                    when(rs2 === 0.U) {
                        io.expanded := imm(0.U(12.W), rd, 0, Mux(c(12), 1.U(5.W), 0.U(5.W)), 0x67)
                        when(rd === 0.U) { io.expanded := "h00100073".U; io.legal := c(12) }
                    }.otherwise {
                        io.expanded := reg(0, rs2, Mux(c(12), rd, 0.U(5.W)), 0, rd)
                    }
                }
                is(6.U) {
                    val offset = Cat(c(8, 7), c(12, 9), 0.U(2.W)).pad(12)
                    io.expanded := store(offset, rs2, 2.U(5.W), 2); io.legal := true.B
                }
                is(7.U) {
                    val offset = Cat(c(9, 7), c(12, 10), 0.U(3.W)).pad(12)
                    io.expanded := store(offset, rs2, 2.U(5.W), 3); io.legal := (xlen == 64).B
                }
            }
        }
    }
    if (withF && xlen == 32) {
        when(c(1, 0) === 0.U && c(15, 13) === 3.U) {
            io.expanded := imm(lwOffset, prime1, 2, prime2, 7); io.legal := true.B
        }
        when(c(1, 0) === 0.U && c(15, 13) === 7.U) {
            io.expanded := store(lwOffset, prime2, prime1, 2, 0x27); io.legal := true.B
        }
        when(c(1, 0) === 2.U && c(15, 13) === 3.U) {
            val offset = Cat(c(3, 2), c(12), c(6, 4), 0.U(2.W)).pad(12)
            io.expanded := imm(offset, 2.U(5.W), 2, rd, 7); io.legal := true.B
        }
        when(c(1, 0) === 2.U && c(15, 13) === 7.U) {
            val offset = Cat(c(8, 7), c(12, 9), 0.U(2.W)).pad(12)
            io.expanded := store(offset, rs2, 2.U(5.W), 2, 0x27); io.legal := true.B
        }
    }
    if (withD) {
        when(c(1, 0) === 2.U && c(15, 13) === 1.U) {
            val offset = Cat(c(4, 2), c(12), c(6, 5), 0.U(3.W)).pad(12)
            io.expanded := imm(offset, 2.U(5.W), 3, rd, 7); io.legal := true.B
        }
        when(c(1, 0) === 2.U && c(15, 13) === 5.U) {
            val offset = Cat(c(9, 7), c(12, 10), 0.U(3.W)).pad(12)
            io.expanded := store(offset, rs2, 2.U(5.W), 3, 0x27); io.legal := true.B
        }
    }
}
