package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline._
import soc.isa.{Extension, MCause, PrivilegeLevel}

class InstrDecodeSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: InstrDecode): Unit = {
        dut.io.valid_in.poke(true.B)
        dut.io.trap_valid.poke(false.B)
        dut.io.pc_in.poke("h80000000".U)
        dut.io.instr_in.poke("h00000013".U)
        dut.io.instr_len_in.poke(0.U)
        dut.io.priv.poke(PrivilegeLevel.Machine)
        dut.io.pred_taken_in.poke(false.B)
        dut.io.pred_target_in.poke(0.U)
        dut.io.redirect.poke(false.B)
        dut.io.stall.poke(false.B)
        dut.io.reg_rs1_data.poke(1.U)
        dut.io.reg_rs2_data.poke(0.U)
    }

    test("InstrDecode accepts RV64 shift-immediate instructions with shamt bit 5 set") {
        simulate(new InstrDecode(64)) { dut =>
            init(dut)

            dut.io.instr_in.poke("h03f0d093".U) // srli x1, x1, 63
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.SRL)
            dut.io.decoded_out.op2.expect(63.U)

            dut.io.instr_in.poke("h43f0d093".U) // srai x1, x1, 63
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.SRA)
            dut.io.decoded_out.op2.expect(63.U)
        }
    }

    test("InstrDecode reports ECALL cause for the current privilege mode") {
        simulate(new InstrDecode(64)) { dut =>
            init(dut)
            dut.io.instr_in.poke("h00000073".U) // ecall

            dut.io.priv.poke(PrivilegeLevel.Machine)
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
            dut.io.trap_info.cause.expect(MCause.EcallFromMMode)
            dut.io.trap_info.value.expect(0.U)

            dut.io.priv.poke(PrivilegeLevel.Supervisor)
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
            dut.io.trap_info.cause.expect(MCause.EcallFromSMode)
            dut.io.trap_info.value.expect(0.U)

            dut.io.priv.poke(PrivilegeLevel.User)
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
            dut.io.trap_info.cause.expect(MCause.EcallFromUMode)
            dut.io.trap_info.value.expect(0.U)
        }
    }

    test("InstrDecode reports EBREAK as a breakpoint at the faulting PC") {
        simulate(new InstrDecode(64)) { dut =>
            init(dut)
            dut.io.pc_in.poke("h40019494".U)
            dut.io.instr_in.poke("h00100073".U) // ebreak

            dut.clock.step()

            dut.io.trap_info.valid.expect(true.B)
            dut.io.trap_info.pc.expect("h40019494".U)
            dut.io.trap_info.cause.expect(MCause.Breakpoint)
            dut.io.trap_info.value.expect("h40019494".U)
        }
    }

    test("InstrDecode gates M and Zifencei instructions by enabled extensions") {
        simulate(new InstrDecode(64, Set(Extension.RV64I))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h022081b3".U) // mul x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
            dut.io.trap_info.cause.expect(MCause.IllegalInstr)
            dut.io.trap_info.value.expect("h022081b3".U)

            init(dut)
            dut.io.instr_in.poke("h0000100f".U) // fence.i
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
        }

        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.RV64M, Extension.Zifencei))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h022081b3".U) // mul x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.MUL)

            init(dut)
            dut.io.instr_in.poke("h0000100f".U) // fence.i
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_fence_i.expect(true.B)
        }
    }

    test("InstrDecode accepts base FENCE as a no-op memory barrier") {
        simulate(new InstrDecode(64, Set(Extension.RV64I))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h0310000f".U) // fence rw,w
            dut.clock.step()

            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_fence.expect(true.B)
            dut.io.decoded_out.ctrl.reg_write.expect(false.B)
        }
    }

    test("InstrDecode gates SFENCE.VMA on supervisor support and decodes it as a fence") {
        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.Zicsr))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h12000073".U) // sfence.vma x0, x0
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
        }

        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.Zicsr, Extension.S))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h12208073".U) // sfence.vma x1, x2
            dut.clock.step()

            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_fence.expect(true.B)
            dut.io.decoded_out.ctrl.reg_write.expect(false.B)
        }
    }

    test("InstrDecode gates RV64A atomic instructions by enabled extensions") {
        simulate(new InstrDecode(64, Set(Extension.RV64I))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h1400b1af".U) // lr.d.aq x3, (x1)
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
        }

        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.RV64A))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h1400b1af".U) // lr.d.aq x3, (x1)
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_atomic.expect(true.B)
            dut.io.decoded_out.atomic.expect(AtomicOpType.LR)
            dut.io.decoded_out.aq.expect(true.B)
            dut.io.decoded_out.rl.expect(false.B)

            init(dut)
            dut.io.instr_in.poke("h1a20b1af".U) // sc.d.rl x3, x2, (x1)
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_atomic.expect(true.B)
            dut.io.decoded_out.atomic.expect(AtomicOpType.SC)
            dut.io.decoded_out.aq.expect(false.B)
            dut.io.decoded_out.rl.expect(true.B)

            init(dut)
            dut.io.instr_in.poke("h0620b1af".U) // amoadd.d.aqrl x3, x2, (x1)
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_atomic.expect(true.B)
            dut.io.decoded_out.atomic.expect(AtomicOpType.Add)
            dut.io.decoded_out.aq.expect(true.B)
            dut.io.decoded_out.rl.expect(true.B)

            init(dut)
            dut.io.instr_in.poke("h1420b1af".U) // reserved: lr.d with rs2 != x0
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
        }
    }

    test("InstrDecode gates bit-manipulation extensions independently") {
        simulate(new InstrDecode(64, Set(Extension.RV64I))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h4020f1b3".U) // andn x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)

            init(dut)
            dut.io.instr_in.poke("h28509193".U) // bseti x3, x1, 5
            dut.clock.step()
            dut.io.trap_info.valid.expect(true.B)
        }

        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.Zbb, Extension.Zbs, Extension.Zba))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h4020f1b3".U) // andn x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.ANDN)

            init(dut)
            dut.io.instr_in.poke("h2a809193".U) // bseti x3, x1, 40
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.BSET)
            dut.io.decoded_out.op2.expect(40.U)

            init(dut)
            dut.io.instr_in.poke("h2020a1b3".U) // sh1add x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.SH1ADD)

            init(dut)
            dut.io.instr_in.poke("h602091b3".U) // rol x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.ROL)

            init(dut)
            dut.io.instr_in.poke("h6070d193".U) // rori x3, x1, 7
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.RORI)
            dut.io.decoded_out.op2.expect(7.U)

            init(dut)
            dut.io.instr_in.poke("h6b80d193".U) // rev8 x3, x1
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.REV8)

            init(dut)
            dut.io.instr_in.poke("h080741bb".U) // zext.h x3, x14
            dut.io.reg_rs1_data.poke(BigInt("ffffffffffff8001", 16).U)
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.ZEXTH)

            init(dut)
            dut.io.instr_in.poke("h082081bb".U) // add.uw x3, x1, x2
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.ADDUW)

            init(dut)
            dut.io.instr_in.poke("h0840919b".U) // slli.uw x3, x1, 4
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.SLLIUW)
            dut.io.decoded_out.op2.expect(4.U)
        }
    }

    test("InstrDecode preserves compressed instruction length metadata") {
        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.C))) { dut =>
            init(dut)
            dut.io.instr_len_in.poke(2.U)
            dut.io.instr_in.poke("h00100093".U) // addi x1, x0, 1 expanded from c.li/c.addi form
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.instr_len.expect(2.U)
        }
    }

    test("InstrDecode decodes Linux __delay BLTU immediate at halfword-aligned PC") {
        simulate(new InstrDecode(64, Set(Extension.RV64I, Extension.C))) { dut =>
            init(dut)
            dut.io.pc_in.poke("hffffffff800d2ef2".U)
            dut.io.instr_in.poke("h00a7e363".U) // bltu a5, a0, 0xffffffff800d2ef8
            dut.clock.step()

            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.branch_type.expect(BranchType.BLTU)
            dut.io.decoded_out.br_imm.expect(6.U)
            dut.io.decoded_out.instr_len.expect(0.U)
        }
    }

    test("InstrDecode maps RV64 word arithmetic to word ALU operations") {
        simulate(new InstrDecode(64, Set(Extension.RV64I))) { dut =>
            init(dut)
            dut.io.instr_in.poke("h00a484bb".U) // addw x9, x9, x10
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.ADDW)

            init(dut)
            dut.io.instr_in.poke("h40a484bb".U) // subw x9, x9, x10
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.alu_op.expect(ALUOps.SUBW)
        }
    }

    test("InstrDecode handles RV64 load/store register write semantics") {
        simulate(new InstrDecode(64, Set(Extension.RV64I))) { dut =>
            init(dut)

            dut.io.instr_in.poke("h00813403".U) // ld x8, 8(sp)
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_read.expect(true.B)
            dut.io.decoded_out.ctrl.reg_write.expect(true.B)
            dut.io.decoded_out.rd.expect(8.U)
            dut.io.decoded_out.mem_imm.expect(8.U)

            init(dut)
            dut.io.instr_in.poke("h00813423".U) // sd x8, 8(sp)
            dut.clock.step()
            dut.io.trap_info.valid.expect(false.B)
            dut.io.decoded_out.ctrl.mem_write.expect(true.B)
            dut.io.decoded_out.ctrl.reg_write.expect(false.B)
            dut.io.decoded_out.rd.expect(8.U)
            dut.io.decoded_out.mem_imm.expect(8.U)
        }
    }
}
