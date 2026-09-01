package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline._

class ALUSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: ALU): Unit = {
        dut.io.pc_in.poke("h80000000".U)
        dut.io.next_pc_in.poke("h80000004".U)
        dut.io.valid_in.poke(true.B)
        dut.io.trap_valid.poke(false.B)
        dut.io.pred_taken_in.poke(false.B)
        dut.io.pred_target_in.poke(0.U)
        dut.io.stall.poke(false.B)

        dut.io.trap_info_in.valid.poke(false.B)
        dut.io.trap_info_in.pc.poke(0.U)
        dut.io.trap_info_in.cause.poke(0.U)
        dut.io.trap_info_in.value.poke(0.U)
        dut.io.trap_info_in.is_ret.poke(false.B)
        dut.io.trap_info_in.ret_type.poke(TrapReturnType.None)

        dut.io.decoded_in.rs1.poke(0.U)
        dut.io.decoded_in.rs2.poke(0.U)
        dut.io.decoded_in.instr.poke(0.U)
        dut.io.decoded_in.op1.poke(0.U)
        dut.io.decoded_in.op2.poke(0.U)
        dut.io.decoded_in.rd.poke(1.U)
        dut.io.decoded_in.funct3.poke(0.U)
        dut.io.decoded_in.op2_sel.poke(OpSel.IMM)
        dut.io.decoded_in.instr_len.poke(0.U)
        dut.io.decoded_in.br_imm.poke(0.U)
        dut.io.decoded_in.mem_imm.poke(0.U)
        dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
        dut.io.decoded_in.ctrl.reg_write.poke(true.B)
        dut.io.decoded_in.ctrl.mem_read.poke(false.B)
        dut.io.decoded_in.ctrl.mem_write.poke(false.B)
        dut.io.decoded_in.ctrl.mem_fence.poke(false.B)
        dut.io.decoded_in.ctrl.mem_fence_i.poke(false.B)
        dut.io.decoded_in.ctrl.mem_atomic.poke(false.B)
        dut.io.decoded_in.ctrl.csr_op.poke(CSROps.None)
        dut.io.decoded_in.ctrl.branch_type.poke(BranchType.None)

        dut.io.fwd.load_valid.poke(false.B)
        dut.io.fwd.load_rd.poke(0.U)
        dut.io.fwd.load_data.poke(0.U)
        dut.io.fwd.rd.poke(0.U)
        dut.io.fwd.alu_result.poke(0.U)
        dut.io.fwd.reg_write.poke(false.B)
        dut.io.fwd.wb_rd.poke(0.U)
        dut.io.fwd.wb_data.poke(0.U)
        dut.io.fwd.wb_reg_write.poke(false.B)
        dut.io.fwd.prev_rd.poke(0.U)
        dut.io.fwd.prev_data.poke(0.U)
        dut.io.fwd.prev_reg_write.poke(false.B)
        dut.io.csr_rdata.poke(0.U)
        dut.io.csr_illegal.poke(false.B)
    }

    private def stepAlu(dut: ALU, op: ALUOps.Type, lhs: BigInt, rhs: BigInt): Unit = {
        dut.io.decoded_in.ctrl.alu_op.poke(op)
        dut.io.decoded_in.op1.poke(lhs.U)
        dut.io.decoded_in.op2.poke(rhs.U)
        dut.clock.step()
    }

    test("ALU uses six-bit shift amounts for RV64 shifts") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.SLL, 1, 63)
            dut.io.alu_out.result.expect(BigInt("8000000000000000", 16))

            stepAlu(dut, ALUOps.SRL, BigInt("8000000000000000", 16), 63)
            dut.io.alu_out.result.expect(1.U)
        }
    }

    test("ALU word shifts use five-bit amounts and sign extend the 32-bit result") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.SLLW, 1, 31)
            dut.io.alu_out.result.expect(BigInt("ffffffff80000000", 16))

            stepAlu(dut, ALUOps.SRLW, BigInt("80000000", 16), 1)
            dut.io.alu_out.result.expect(BigInt("0000000040000000", 16))
        }
    }

    test("ALU suppresses CSR write side effects for CSR read forms") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.csr_op.poke(CSROps.RS)
            dut.io.decoded_in.op1.poke("hf14".U) // mhartid
            dut.io.decoded_in.rs2.poke(0.U)
            dut.clock.step()
            dut.io.csr_valid.expect(true.B)
            dut.io.csr_write.expect(false.B)

            dut.io.decoded_in.ctrl.csr_op.poke(CSROps.RW)
            dut.io.decoded_in.rs2.poke(0.U)
            dut.clock.step()
            dut.io.csr_valid.expect(true.B)
            dut.io.csr_write.expect(true.B)

            dut.io.decoded_in.ctrl.csr_op.poke(CSROps.RSI)
            dut.io.decoded_in.rs2.poke(0.U)
            dut.clock.step()
            dut.io.csr_valid.expect(true.B)
            dut.io.csr_write.expect(false.B)
        }
    }

    test("ALU reports the faulting instruction for an illegal CSR access") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            val instruction = BigInt("da002573", 16) // csrr a0, scountovf
            dut.io.pc_in.poke("h40005268".U)
            dut.io.decoded_in.instr.poke(instruction.U)
            dut.io.decoded_in.ctrl.csr_op.poke(CSROps.RS)
            dut.io.decoded_in.op1.poke("hda0".U)
            dut.io.decoded_in.rs2.poke(0.U)
            dut.io.csr_illegal.poke(true.B)

            dut.clock.step()

            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect("h40005268".U)
            dut.io.trap_info_out.cause.expect(soc.isa.MCause.IllegalInstr)
            dut.io.trap_info_out.value.expect(instruction.U)
        }
    }

    test("ALU executes RV64M multiply variants") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.MUL, BigInt("ffffffffffffffff", 16), 3)
            dut.io.alu_out.result.expect(BigInt("fffffffffffffffd", 16))

            stepAlu(dut, ALUOps.MULH, BigInt("ffffffffffffffff", 16), 3)
            dut.io.alu_out.result.expect(BigInt("ffffffffffffffff", 16))

            stepAlu(dut, ALUOps.MULHSU, BigInt("ffffffffffffffff", 16), 3)
            dut.io.alu_out.result.expect(BigInt("ffffffffffffffff", 16))

            stepAlu(dut, ALUOps.MULHU, BigInt("ffffffffffffffff", 16), 2)
            dut.io.alu_out.result.expect(1.U)

            stepAlu(dut, ALUOps.MULW, BigInt("ffffffffffffffff", 16), 2)
            dut.io.alu_out.result.expect(BigInt("fffffffffffffffe", 16))
        }
    }

    test("ALU executes RV64M divide and remainder edge cases") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.DIV, 10, 3)
            dut.io.alu_out.result.expect(3.U)

            stepAlu(dut, ALUOps.REM, 10, 3)
            dut.io.alu_out.result.expect(1.U)

            stepAlu(dut, ALUOps.DIVU, 10, 0)
            dut.io.alu_out.result.expect(BigInt("ffffffffffffffff", 16))

            stepAlu(dut, ALUOps.REMU, 10, 0)
            dut.io.alu_out.result.expect(10.U)

            stepAlu(dut, ALUOps.DIV, BigInt("8000000000000000", 16), BigInt("ffffffffffffffff", 16))
            dut.io.alu_out.result.expect(BigInt("8000000000000000", 16))

            stepAlu(dut, ALUOps.REM, BigInt("8000000000000000", 16), BigInt("ffffffffffffffff", 16))
            dut.io.alu_out.result.expect(0.U)

            stepAlu(dut, ALUOps.DIVW, BigInt("fffffffffffffffe", 16), 2)
            dut.io.alu_out.result.expect(BigInt("ffffffffffffffff", 16))

            stepAlu(dut, ALUOps.REMUW, BigInt("ffffffffffffffff", 16), 2)
            dut.io.alu_out.result.expect(1.U)
        }
    }

    test("ALU executes Zbb logical, count, and minmax operations") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.ANDN, BigInt("ff00ff00ff00ff00", 16), BigInt("00ff00ff00ff00ff", 16))
            dut.io.alu_out.result.expect(BigInt("ff00ff00ff00ff00", 16))

            stepAlu(dut, ALUOps.ORN, BigInt("00000000000000f0", 16), BigInt("00000000000000ff", 16))
            dut.io.alu_out.result.expect(BigInt("fffffffffffffff0", 16))

            stepAlu(dut, ALUOps.XNOR, BigInt("aaaaaaaaaaaaaaaa", 16), BigInt("ffff0000ffff0000", 16))
            dut.io.alu_out.result.expect(BigInt("aaaa5555aaaa5555", 16))

            stepAlu(dut, ALUOps.CLZ, BigInt("0000000000001000", 16), 0)
            dut.io.alu_out.result.expect(51.U)

            stepAlu(dut, ALUOps.CTZ, BigInt("0000000000001000", 16), 0)
            dut.io.alu_out.result.expect(12.U)

            stepAlu(dut, ALUOps.CPOP, BigInt("f0f0000000000001", 16), 0)
            dut.io.alu_out.result.expect(9.U)

            stepAlu(dut, ALUOps.CLZW, BigInt("0000000000001000", 16), 0)
            dut.io.alu_out.result.expect(19.U)

            stepAlu(dut, ALUOps.CTZW, BigInt("0000000080000000", 16), 0)
            dut.io.alu_out.result.expect(31.U)

            stepAlu(dut, ALUOps.CPOPW, BigInt("00000000f0f00001", 16), 0)
            dut.io.alu_out.result.expect(9.U)

            stepAlu(dut, ALUOps.MIN, BigInt("fffffffffffffffe", 16), 3)
            dut.io.alu_out.result.expect(BigInt("fffffffffffffffe", 16))

            stepAlu(dut, ALUOps.MAXU, BigInt("fffffffffffffffe", 16), 3)
            dut.io.alu_out.result.expect(BigInt("fffffffffffffffe", 16))

            stepAlu(dut, ALUOps.SEXTB, BigInt("0000000000000080", 16), 0)
            dut.io.alu_out.result.expect(BigInt("ffffffffffffff80", 16))

            stepAlu(dut, ALUOps.SEXTH, BigInt("0000000000008001", 16), 0)
            dut.io.alu_out.result.expect(BigInt("ffffffffffff8001", 16))

            stepAlu(dut, ALUOps.ZEXTH, BigInt("ffffffffffff8001", 16), 0)
            dut.io.alu_out.result.expect(BigInt("0000000000008001", 16))

            stepAlu(dut, ALUOps.ORCB, BigInt("000000ff01008000", 16), 0)
            dut.io.alu_out.result.expect(BigInt("000000ffff00ff00", 16))

            stepAlu(dut, ALUOps.REV8, BigInt("0123456789abcdef", 16), 0)
            dut.io.alu_out.result.expect(BigInt("efcdab8967452301", 16))
        }
    }

    test("ALU executes Zbb rotate operations") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.ROL, BigInt("0123456789abcdef", 16), 8)
            dut.io.alu_out.result.expect(BigInt("23456789abcdef01", 16))

            stepAlu(dut, ALUOps.ROR, BigInt("0123456789abcdef", 16), 8)
            dut.io.alu_out.result.expect(BigInt("ef0123456789abcd", 16))

            stepAlu(dut, ALUOps.RORI, BigInt("0123456789abcdef", 16), 4)
            dut.io.alu_out.result.expect(BigInt("f0123456789abcde", 16))

            stepAlu(dut, ALUOps.ROLW, BigInt("0000000081234567", 16), 8)
            dut.io.alu_out.result.expect(BigInt("0000000023456781", 16))

            stepAlu(dut, ALUOps.RORW, BigInt("0000000081234567", 16), 8)
            dut.io.alu_out.result.expect(BigInt("0000000067812345", 16))

            stepAlu(dut, ALUOps.RORIW, BigInt("0000000012345678", 16), 4)
            dut.io.alu_out.result.expect(BigInt("ffffffff81234567", 16))
        }
    }

    test("ALU executes Zbs single-bit and Zba shifted-add operations") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            stepAlu(dut, ALUOps.BSET, 0, 40)
            dut.io.alu_out.result.expect(BigInt("0000010000000000", 16))

            stepAlu(dut, ALUOps.BCLR, BigInt("ffffffffffffffff", 16), 63)
            dut.io.alu_out.result.expect(BigInt("7fffffffffffffff", 16))

            stepAlu(dut, ALUOps.BINV, 0, 5)
            dut.io.alu_out.result.expect(32.U)

            stepAlu(dut, ALUOps.BEXT, BigInt("0000010000000000", 16), 40)
            dut.io.alu_out.result.expect(1.U)

            stepAlu(dut, ALUOps.SH1ADD, 3, 10)
            dut.io.alu_out.result.expect(16.U)

            stepAlu(dut, ALUOps.SH3ADD, 3, 10)
            dut.io.alu_out.result.expect(34.U)

            stepAlu(dut, ALUOps.ADDUW, BigInt("ffffffff00000005", 16), 10)
            dut.io.alu_out.result.expect(15.U)

            stepAlu(dut, ALUOps.SH2ADDUW, BigInt("ffffffff00000005", 16), 10)
            dut.io.alu_out.result.expect(30.U)

            stepAlu(dut, ALUOps.SLLIUW, BigInt("ffffffff00000005", 16), 4)
            dut.io.alu_out.result.expect(80.U)
        }
    }

    test("ALU emits memory access metadata for RV64A atomics") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.mem_atomic.poke(true.B)
            dut.io.decoded_in.atomic.poke(AtomicOpType.Add)
            dut.io.decoded_in.aq.poke(true.B)
            dut.io.decoded_in.rl.poke(true.B)
            dut.io.decoded_in.funct3.poke("b011".U) // amoadd.d
            dut.io.decoded_in.op1.poke("h10000008".U)
            dut.io.decoded_in.op2.poke(5.U)
            dut.clock.step()
            dut.io.alu_out.mem.valid.expect(true.B)
            dut.io.alu_out.mem.op.expect(MemOpType.AMO)
            dut.io.alu_out.mem.atomic.expect(AtomicOpType.Add)
            dut.io.alu_out.mem.size.expect(3.U)
            dut.io.alu_out.mem.mask.expect("hff".U)
            dut.io.alu_out.mem.wdata.expect(5.U)
            dut.io.alu_out.mem.aq.expect(true.B)
            dut.io.alu_out.mem.rl.expect(true.B)

            dut.io.decoded_in.atomic.poke(AtomicOpType.SC)
            dut.io.decoded_in.aq.poke(false.B)
            dut.io.decoded_in.rl.poke(false.B)
            dut.io.decoded_in.funct3.poke("b010".U) // sc.w at the upper word lane
            dut.io.decoded_in.op1.poke("h10000004".U)
            dut.io.decoded_in.op2.poke("h0000000012345678".U)
            dut.clock.step()
            dut.io.alu_out.mem.valid.expect(true.B)
            dut.io.alu_out.mem.op.expect(MemOpType.SC)
            dut.io.alu_out.mem.size.expect(2.U)
            dut.io.alu_out.mem.mask.expect("hf0".U)
            dut.io.alu_out.mem.wdata.expect(BigInt("1234567800000000", 16))
        }
    }

    test("ALU emits a fence memory operation for SFENCE.VMA-style barriers") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.mem_fence.poke(true.B)
            dut.clock.step()

            dut.io.alu_out.mem.valid.expect(true.B)
            dut.io.alu_out.mem.op.expect(MemOpType.Fence)
            dut.io.alu_out.reg_write.expect(false.B)
        }
    }

    test("ALU forwards LSU load-like results by forwarding rd") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.rs1.poke(3.U)
            dut.io.decoded_in.rs2.poke(0.U)
            dut.io.decoded_in.op1.poke(1.U)
            dut.io.decoded_in.op2.poke(1.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
            dut.io.fwd.load_valid.poke(true.B)
            dut.io.fwd.load_rd.poke(3.U)
            dut.io.fwd.load_data.poke(41.U)
            dut.clock.step()
            dut.io.alu_out.result.expect(42.U)

            dut.io.decoded_in.rs1.poke(0.U)
            dut.io.decoded_in.rs2.poke(4.U)
            dut.io.decoded_in.op1.poke(1.U)
            dut.io.decoded_in.op2.poke(1.U)
            dut.io.fwd.load_rd.poke(4.U)
            dut.io.fwd.load_data.poke(9.U)
            dut.clock.step()
            dut.io.alu_out.result.expect(10.U)
        }
    }

    test("ALU forwards adjacent ALU result into store rs2 data") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            val storeData = BigInt("8877665544332211", 16)
            val staleRs2 = BigInt("40004000", 16)

            dut.io.decoded_in.rd.poke(6.U)
            dut.io.decoded_in.rs1.poke(0.U)
            dut.io.decoded_in.rs2.poke(0.U)
            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(storeData.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
            dut.io.decoded_in.ctrl.reg_write.poke(true.B)
            dut.clock.step()
            dut.io.alu_out.result.expect(storeData.U)

            dut.io.decoded_in.rd.poke(0.U)
            dut.io.decoded_in.rs1.poke(5.U)
            dut.io.decoded_in.rs2.poke(6.U)
            dut.io.decoded_in.op1.poke(staleRs2.U)
            dut.io.decoded_in.op2.poke(staleRs2.U)
            dut.io.decoded_in.mem_imm.poke(0.U)
            dut.io.decoded_in.funct3.poke(3.U)
            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.mem_write.poke(true.B)
            dut.clock.step()

            dut.io.alu_out.mem.wdata.expect(storeData.U)
        }
    }

    test("ALU forwards a multi-instruction immediate into an adjacent store") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            val storeData = BigInt("8877665544332211", 16)
            val staleRs2 = BigInt("40004000", 16)

            dut.io.decoded_in.rd.poke(6.U)
            dut.io.decoded_in.rs1.poke(0.U)
            dut.io.decoded_in.rs2.poke(0.U)
            dut.io.decoded_in.ctrl.reg_write.poke(true.B)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(BigInt("fffffffffe21e000", 16).U)
            dut.clock.step()

            dut.io.decoded_in.rs1.poke(6.U)
            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(BigInt("fffffffffffffd99", 16).U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADDW)
            dut.clock.step()

            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(12.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.SLL)
            dut.clock.step()

            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(0x551.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
            dut.clock.step()

            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(13.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.SLL)
            dut.clock.step()

            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(0x199.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
            dut.clock.step()

            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(13.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.SLL)
            dut.clock.step()

            dut.io.decoded_in.op1.poke(0.U)
            dut.io.decoded_in.op2.poke(0x211.U)
            dut.io.decoded_in.ctrl.alu_op.poke(ALUOps.ADD)
            dut.clock.step()
            dut.io.alu_out.result.expect(storeData.U)

            dut.io.decoded_in.rd.poke(0.U)
            dut.io.decoded_in.rs1.poke(5.U)
            dut.io.decoded_in.rs2.poke(6.U)
            dut.io.decoded_in.op1.poke(staleRs2.U)
            dut.io.decoded_in.op2.poke(staleRs2.U)
            dut.io.decoded_in.mem_imm.poke(0.U)
            dut.io.decoded_in.funct3.poke(3.U)
            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.mem_write.poke(true.B)
            dut.clock.step()

            dut.io.alu_out.mem.wdata.expect(storeData.U)
        }
    }

    test("ALU forwards writeback results to adjacent branch operands") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.BNE)
            dut.io.decoded_in.rs1.poke(5.U)
            dut.io.decoded_in.rs2.poke(6.U)
            dut.io.decoded_in.op1.poke("h40000000".U)
            dut.io.decoded_in.op2.poke("h45".U)
            dut.io.fwd.wb_reg_write.poke(true.B)
            dut.io.fwd.wb_rd.poke(6.U)
            dut.io.fwd.wb_data.poke("h40000000".U)
            dut.clock.step()

            dut.io.br_info.valid.expect(true.B)
            dut.io.br_info.taken.expect(false.B)
            dut.io.br_info.redirect.expect(false.B)
        }
    }

    test("ALU uses compressed instruction length for link and fallthrough") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.JAL)
            dut.io.decoded_in.instr_len.poke(2.U)
            dut.io.decoded_in.op1.poke("h80000000".U)
            dut.io.decoded_in.op2.poke(8.U)
            dut.clock.step()
            dut.io.alu_out.result.expect(BigInt("80000002", 16))
            dut.io.br_info.target.expect(BigInt("80000008", 16))

            init(dut)
            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.BNE)
            dut.io.decoded_in.instr_len.poke(2.U)
            dut.io.decoded_in.op1.poke(1.U)
            dut.io.decoded_in.op2.poke(1.U)
            dut.clock.step()
            dut.io.br_info.target.expect(BigInt("80000002", 16))
        }
    }

    test("ALU redirects Linux __delay halfword-aligned BLTU to the encoded target") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke("hffffffff800d2ef2".U)
            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.BLTU)
            dut.io.decoded_in.op1.poke(1.U)
            dut.io.decoded_in.op2.poke(2.U)
            dut.io.decoded_in.br_imm.poke(6.U)
            dut.clock.step()

            dut.io.br_info.valid.expect(true.B)
            dut.io.br_info.taken.expect(true.B)
            dut.io.br_info.redirect.expect(true.B)
            dut.io.br_info.target.expect("hffffffff800d2ef8".U)
        }
    }

    test("ALU clears bit zero for JALR branch targets") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.JALR)
            dut.io.decoded_in.op1.poke("h4000001f".U)
            dut.io.decoded_in.op2.poke(0.U)
            dut.clock.step()

            dut.io.br_info.valid.expect(true.B)
            dut.io.br_info.taken.expect(true.B)
            dut.io.br_info.redirect.expect(true.B)
            dut.io.br_info.target.expect("h4000001e".U)
        }
    }

    test("ALU suppresses redirect when predicted taken target is correct") {
        simulate(new ALU(64)) { dut =>
            init(dut)

            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.BNE)
            dut.io.decoded_in.op1.poke(1.U)
            dut.io.decoded_in.op2.poke(2.U)
            dut.io.decoded_in.br_imm.poke(16.U)
            dut.io.pred_taken_in.poke(true.B)
            dut.io.pred_target_in.poke("h80000010".U)
            dut.clock.step()

            dut.io.br_info.valid.expect(true.B)
            dut.io.br_info.taken.expect(true.B)
            dut.io.br_info.redirect.expect(false.B)
            dut.io.br_info.target.expect("h80000010".U)

            init(dut)
            dut.io.decoded_in.ctrl.reg_write.poke(false.B)
            dut.io.decoded_in.ctrl.branch_type.poke(BranchType.BNE)
            dut.io.decoded_in.op1.poke(1.U)
            dut.io.decoded_in.op2.poke(2.U)
            dut.io.decoded_in.br_imm.poke(16.U)
            dut.io.pred_taken_in.poke(true.B)
            dut.io.pred_target_in.poke("h80000020".U)
            dut.clock.step()

            dut.io.br_info.valid.expect(true.B)
            dut.io.br_info.taken.expect(true.B)
            dut.io.br_info.redirect.expect(true.B)
            dut.io.br_info.target.expect("h80000010".U)
        }
    }
}
