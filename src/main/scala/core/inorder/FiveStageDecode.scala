package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.isa.Opcode

/** Independent decoder: architectural encodings only, no OoO/legacy control dependencies. */
class FiveStageDecode(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val control = Output(new FiveStageDecodeControl(p))
    })
    val i = io.instruction
    val c = WireDefault(0.U.asTypeOf(new FiveStageDecodeControl(p)))
    def sext(value: UInt): UInt = if (value.getWidth == p.xlen) value else
        Cat(Fill(p.xlen - value.getWidth, value(value.getWidth - 1)), value)
    c.rs1 := i(19, 15); c.rs2 := i(24, 20); c.rd := i(11, 7); c.funct3 := i(14, 12)
    c.csrAddress := i(31, 20); c.immediate := sext(i(31, 20)); c.aluOp := FiveStageAluOp.add
    val f3 = i(14, 12)
    val f7 = i(31, 25)
    val isWord = i(6, 0) === Opcode.OP_32 || i(6, 0) === Opcode.OP_IMM_32
    val shiftEncoding = if (p.xlen == 64) Mux(isWord, f7 === 0.U, i(31, 26) === 0.U) else f7 === 0.U
    val arithmeticShiftEncoding = if (p.xlen == 64)
        Mux(isWord, f7 === 32.U, i(31, 26) === 16.U) else f7 === 32.U
    switch(i(6, 0)) {
        is(Opcode.LUI) {
            c.legal := true.B; c.writesRd := true.B; c.useImmediate := true.B
            c.immediate := sext(Cat(i(31, 12), 0.U(12.W)))
        }
        is(Opcode.AUIPC) {
            c.legal := true.B; c.writesRd := true.B; c.usePc := true.B; c.useImmediate := true.B
            c.immediate := sext(Cat(i(31, 12), 0.U(12.W)))
        }
        is(Opcode.OP_IMM, Opcode.OP_IMM_32, Opcode.OP, Opcode.OP_32) {
            val immediate = i(6, 0) === Opcode.OP_IMM || i(6, 0) === Opcode.OP_IMM_32
            c.usesRs1 := true.B; c.usesRs2 := !immediate; c.writesRd := true.B
            c.useImmediate := immediate; c.word := isWord
            val validAlu = WireDefault(false.B)
            switch(f3) {
                is(0.U) {
                    c.aluOp := Mux(!immediate && f7 === 32.U, FiveStageAluOp.subtract, FiveStageAluOp.add)
                    validAlu := immediate || f7 === 0.U || f7 === 32.U
                }
                is(1.U) { c.aluOp := FiveStageAluOp.shiftLeft; validAlu := Mux(immediate, shiftEncoding, f7 === 0.U) }
                is(2.U) { c.aluOp := FiveStageAluOp.lessSigned; validAlu := immediate || f7 === 0.U }
                is(3.U) { c.aluOp := FiveStageAluOp.lessUnsigned; validAlu := immediate || f7 === 0.U }
                is(4.U) { c.aluOp := FiveStageAluOp.xorBits; validAlu := immediate || f7 === 0.U }
                is(5.U) {
                    c.aluOp := Mux(Mux(immediate, arithmeticShiftEncoding, f7 === 32.U),
                        FiveStageAluOp.shiftArithmetic, FiveStageAluOp.shiftRight)
                    validAlu := Mux(immediate, shiftEncoding || arithmeticShiftEncoding, f7 === 0.U || f7 === 32.U)
                }
                is(6.U) { c.aluOp := FiveStageAluOp.orBits; validAlu := immediate || f7 === 0.U }
                is(7.U) { c.aluOp := FiveStageAluOp.andBits; validAlu := immediate || f7 === 0.U }
            }
            c.legal := validAlu && (!isWord || f3 === 0.U || f3 === 1.U || f3 === 5.U) &&
                (!isWord || (p.xlen == 64).B)
            if (p.withM) {
                when(!immediate && f7 === 1.U) {
                    c.mulDiv := true.B
                    c.legal := (!isWord || (p.xlen == 64).B) && (!isWord || f3 === 0.U || f3 >= 4.U)
                }
            }
        }
        is(Opcode.LOAD, Opcode.STORE) {
            val store = i(6, 0) === Opcode.STORE
            c.load := !store; c.store := store; c.usesRs1 := true.B; c.usesRs2 := store
            c.writesRd := !store; c.useImmediate := true.B
            c.immediate := Mux(store, sext(Cat(i(31, 25), i(11, 7))), sext(i(31, 20)))
            c.legal := f3(1, 0) <= (if (p.xlen == 64) 3 else 2).U &&
                Mux(store, !f3(2), f3 =/= 7.U && ((p.xlen == 64).B || f3 =/= 6.U))
        }
        is(Opcode.BRANCH) {
            c.branch := true.B; c.usesRs1 := true.B; c.usesRs2 := true.B
            c.immediate := sext(Cat(i(31), i(7), i(30, 25), i(11, 8), 0.U(1.W)))
            c.legal := f3 === 0.U || f3 === 1.U || f3 >= 4.U
        }
        is("h2f".U) {
            if (p.withA) {
                val operation = i(31, 27)
                val lr = operation === 2.U
                val sc = operation === 3.U
                val amo = Seq(0, 1, 4, 8, 12, 16, 20, 24, 28).map(n => operation === n.U).reduce(_ || _)
                c.atomic := true.B; c.atomicOperation := operation
                c.load := lr; c.store := !lr; c.writesRd := true.B
                c.usesRs1 := true.B; c.usesRs2 := !lr; c.immediate := 0.U
                // Fully ordered for both aq/rl domains. No unacknowledged store or AMO can overtake.
                c.serial := true.B
                c.legal := (f3 === 2.U || ((p.xlen == 64).B && f3 === 3.U)) &&
                    (lr || sc || amo) && (!lr || c.rs2 === 0.U)
            }
        }
        is(Opcode.JAL) {
            c.jump := true.B; c.writesRd := true.B; c.legal := true.B
            c.immediate := sext(Cat(i(31), i(19, 12), i(20), i(30, 21), 0.U(1.W)))
        }
        is(Opcode.JALR) {
            c.jump := true.B; c.jumpRegister := true.B; c.usesRs1 := true.B; c.writesRd := true.B
            c.legal := f3 === 0.U
        }
        is(Opcode.MISC_MEM) {
            c.legal := f3 === 0.U || (f3 === 1.U && i(31, 20) === 0.U && c.rs1 === 0.U && c.rd === 0.U)
            c.fenceI := f3 === 1.U; c.serial := true.B
        }
        is(Opcode.SYSTEM) {
            c.serial := true.B
            when(f3 =/= 0.U && f3 =/= 4.U) {
                c.legal := true.B; c.csr := true.B; c.writesRd := true.B
                c.csrImmediate := f3(2); c.usesRs1 := !f3(2)
            }.otherwise {
                c.ecall := i === "h00000073".U; c.ebreak := i === "h00100073".U
                c.mret := i === "h30200073".U
                c.sret := p.withSupervisor.B && i === "h10200073".U
                c.sfence := p.withSupervisor.B && i(31, 25) === "b0001001".U && i(11, 7) === 0.U
                c.wfi := i === "h10500073".U
                c.legal := c.ecall || c.ebreak || c.mret || c.sret || c.sfence || c.wfi
            }
        }
    }
    if (p.withF) {
        val fp = I1FloatingPointDecode
        when(i(6, 0) === "h07".U || i(6, 0) === "h27".U || i(6, 0) === "h53".U ||
            fp.fused(i)) {
            c.floating := true.B; c.fpExecute := !fp.memory(i)
            c.fpWrites := fp.writesFp(i); c.writesRd := fp.writesInteger(i)
            c.usesRs1 := fp.readsInteger(i); c.usesRs2 := false.B
            c.load := fp.load(i); c.store := fp.store(i)
            c.useImmediate := fp.memory(i)
            c.immediate := Mux(fp.store(i), sext(Cat(i(31, 25), i(11, 7))), sext(i(31, 20)))
            c.serial := true.B
            c.legal := fp.supported(i, p.floatingConfig)
        }
    }
    io.control := c
}
