package soc.core.pipeline

import chisel3._
import chisel3.util._

import soc.core.pipeline.InstrSignals
import soc.core.pipeline.ALUOps
import soc.core.pipeline.ALUOut
import soc.core.pipeline.FwdSignals
import soc.isa.MCause

class ALU(XLEN: Int = 64) extends Module {
    val io = IO(new Bundle {
        val pc_in         = Input(UInt(XLEN.W))
        val next_pc_in    = Input(UInt(XLEN.W)) // 将要到来的指令的PC，用于判断分支预测是否正确
        val valid_in      = Input(Bool())
        val trap_valid    = Input(Bool())
        val decoded_in    = Input(new DecodedInstr(XLEN))
        val pred_taken_in = Input(Bool())
        val pred_target_in = Input(UInt(XLEN.W))
        val trap_info_in  = Input(new TrapInfo(XLEN))
        val stall         = Input(Bool())

        val fwd = Input(new FwdSignals(XLEN))

        val valid_out     = Output(Bool())
        val alu_out       = Output(new ALUOut(XLEN))
        val pc_out        = Output(UInt(XLEN.W))
        val br_info       = Output(new BranchInfo(XLEN))
        val trap_info_out = Output(new TrapInfo(XLEN))
        val instr_len_out = Output(UInt(2.W))
        // CSR读写
        val csr_valid   = Output(Bool())
        val csr_cmd     = Output(UInt(4.W))
        val csr_addr    = Output(UInt(12.W))
        val csr_write   = Output(Bool())
        val csr_wdata   = Output(UInt(XLEN.W))
        // CSR reads must see the current EX instruction combinationally, but
        // CSR writes are architectural side effects and are committed from the
        // registered EX slot so stalls/flushes cannot borrow the next decode
        // slot's CSR address or data.
        val csr_commit_valid = Output(Bool())
        val csr_commit_cmd   = Output(UInt(4.W))
        val csr_commit_addr  = Output(UInt(12.W))
        val csr_commit_write = Output(Bool())
        val csr_commit_wdata = Output(UInt(XLEN.W))
        val csr_rdata   = Input(UInt(XLEN.W))
        val csr_illegal = Input(Bool())
    })

    val mem_read      = io.decoded_in.ctrl.mem_read
    val mem_write     = io.decoded_in.ctrl.mem_write
    val mem_fence     = io.decoded_in.ctrl.mem_fence
    val mem_fence_i   = io.decoded_in.ctrl.mem_fence_i
    val mem_atomic    = io.decoded_in.ctrl.mem_atomic
    val csr_op        = io.decoded_in.ctrl.csr_op
    val op2_sel       = io.decoded_in.op2_sel
    val mem_imm       = io.decoded_in.mem_imm
    val op1           = WireInit(0.U(XLEN.W))
    val op2           = WireInit(0.U(XLEN.W))
    val alu_result    = WireInit(0.U(XLEN.W))
    val branch_target = WireInit(0.U(XLEN.W))
    val valid         = io.valid_in && !io.trap_valid
    val update_en     = !io.stall

    // Adjacent ALU-to-ALU bypass. Keep this as explicit state instead of
    // reading io.alu_out inside the module; io.alu_out is driven below from
    // alu_result, so using it as an operand source would create a fragile
    // self-reference. Older ALU results are supplied by Core's forwarding bus.
    val exBypassValid = RegInit(false.B)
    val exBypassRd    = RegInit(0.U(5.W))
    val exBypassData  = RegInit(0.U(XLEN.W))
    def fwdMatch(rs: UInt, valid: Bool, rd: UInt): Bool =
        rs =/= 0.U && valid && rs === rd

    val csr_addr_comb = WireInit(0.U(12.W))
    val trap_info = WireInit(0.U.asTypeOf(io.trap_info_in))

    trap_info.valid  := valid && Mux(io.csr_illegal, true.B, io.trap_info_in.valid)
    trap_info.pc     := Mux(io.csr_illegal, io.pc_in, io.trap_info_in.pc)
    trap_info.cause  := Mux(io.csr_illegal, MCause.IllegalInstr, io.trap_info_in.cause)
    // CSR legality is checked in EX, after the decode-stage trap metadata was
    // formed.  An illegal CSR access must still report the faulting instruction
    // in mtval/stval, just like any other illegal-instruction exception.
    trap_info.value  := Mux(io.csr_illegal, io.decoded_in.instr, io.trap_info_in.value)
    trap_info.is_ret := valid && io.trap_info_in.is_ret
    trap_info.ret_type := Mux(valid && io.trap_info_in.is_ret, io.trap_info_in.ret_type, TrapReturnType.None)

    // 数据转发，优先级：mem > wb > alu输入
    when(!valid) {
        op1 := 0.U
    }.elsewhen(csr_op =/= CSROps.None) { // CSR指令，op1来自CSR寄存器
        csr_addr_comb := io.decoded_in.op1(11, 0)
        op1         := io.csr_rdata
    }.elsewhen(io.decoded_in.rs1 === 0.U) { // 立即数指令
        op1 := io.decoded_in.op1
    }.elsewhen(fwdMatch(io.decoded_in.rs1, exBypassValid, exBypassRd)) {
        op1 := exBypassData
    }.elsewhen(fwdMatch(io.decoded_in.rs1, io.fwd.load_valid, io.fwd.load_rd)) {
        op1 := io.fwd.load_data
    }.elsewhen(fwdMatch(io.decoded_in.rs1, io.fwd.reg_write, io.fwd.rd)) {
        op1 := io.fwd.alu_result
    }.elsewhen(fwdMatch(io.decoded_in.rs1, io.fwd.prev_reg_write, io.fwd.prev_rd)) {
        op1 := io.fwd.prev_data
    }.elsewhen(fwdMatch(io.decoded_in.rs1, io.fwd.wb_reg_write, io.fwd.wb_rd)) {
        op1 := io.fwd.wb_data
    }.otherwise {
        op1 := io.decoded_in.op1
    }
    when(!valid) {
        op2 := 0.U
    }.elsewhen(csr_op === CSROps.RWI || csr_op === CSROps.RSI || csr_op === CSROps.RCI) {
        op2 := Cat(Fill(XLEN - 5, 0.U), io.decoded_in.rs2) // CSR zimm 指令，0扩展
    }.elsewhen(io.decoded_in.rs2 === 0.U) { // 立即数指令
        op2 := io.decoded_in.op2
    }.elsewhen(fwdMatch(io.decoded_in.rs2, exBypassValid, exBypassRd)) {
        op2 := exBypassData
    }.elsewhen(fwdMatch(io.decoded_in.rs2, io.fwd.load_valid, io.fwd.load_rd)) {
        op2 := io.fwd.load_data
    }.elsewhen(fwdMatch(io.decoded_in.rs2, io.fwd.reg_write, io.fwd.rd)) {
        op2 := io.fwd.alu_result
    }.elsewhen(fwdMatch(io.decoded_in.rs2, io.fwd.prev_reg_write, io.fwd.prev_rd)) {
        op2 := io.fwd.prev_data
    }.elsewhen(fwdMatch(io.decoded_in.rs2, io.fwd.wb_reg_write, io.fwd.wb_rd)) {
        op2 := io.fwd.wb_data
    }.otherwise {
        op2 := io.decoded_in.op2
    }

    val op1_32  = op1(31, 0)
    val op2_32  = op2(31, 0)
    val shamt64 = op2(5, 0).asUInt
    val shamt32 = op2(4, 0).asUInt
    val xlenMin = (BigInt(1) << (XLEN - 1)).U(XLEN.W)
    val wordMin = "h80000000".U(32.W)
    val signedProduct = (Cat(op1(XLEN - 1), op1).asSInt * Cat(op2(XLEN - 1), op2).asSInt).asUInt
    val signedUnsignedProduct = (Cat(op1(XLEN - 1), op1).asSInt * Cat(0.U(1.W), op2).asSInt).asUInt
    val unsignedProduct = Cat(0.U(1.W), op1) * Cat(0.U(1.W), op2)

    private def sext32(value: UInt): UInt = Cat(Fill(XLEN - 32, value(31)), value)
    private def sext8(value: UInt): UInt = Cat(Fill(XLEN - 8, value(7)), value(7, 0))
    private def sext16(value: UInt): UInt = Cat(Fill(XLEN - 16, value(15)), value(15, 0))
    private def zext16(value: UInt): UInt = Cat(0.U((XLEN - 16).W), value(15, 0))
    private def zext32(value: UInt): UInt = Cat(0.U((XLEN - 32).W), value(31, 0))
    private def lowestSetBitIndex(value: UInt): UInt = {
        Mux(value === 0.U, XLEN.U, PriorityEncoder(value))
    }
    private def lowestSetBitIndex32(value: UInt): UInt = {
        Mux(value(31, 0) === 0.U, 32.U, PriorityEncoder(value(31, 0)))
    }
    private def leadingZeroCount(value: UInt): UInt = {
        Mux(value === 0.U, XLEN.U, PriorityEncoder(Reverse(value)))
    }
    private def leadingZeroCount32(value: UInt): UInt = {
        Mux(value(31, 0) === 0.U, 32.U, PriorityEncoder(Reverse(value(31, 0))))
    }
    private def rotateLeft(value: UInt, amount: UInt): UInt = {
        ((value << amount) | (value >> ((XLEN.U - amount)(log2Ceil(XLEN) - 1, 0))))(XLEN - 1, 0)
    }
    private def rotateRight(value: UInt, amount: UInt): UInt = {
        ((value >> amount) | (value << ((XLEN.U - amount)(log2Ceil(XLEN) - 1, 0))))(XLEN - 1, 0)
    }
    private def rotateLeft32(value: UInt, amount: UInt): UInt = {
        val word = value(31, 0)
        val amt = amount(4, 0)
        val rotated = ((word << amt) | (word >> ((32.U - amt)(4, 0))))(31, 0)
        sext32(rotated)
    }
    private def rotateRight32(value: UInt, amount: UInt): UInt = {
        val word = value(31, 0)
        val amt = amount(4, 0)
        val rotated = ((word >> amt) | (word << ((32.U - amt)(4, 0))))(31, 0)
        sext32(rotated)
    }
    private def orcByte(value: UInt): UInt = {
        Cat((0 until (XLEN / 8)).reverse.map { i =>
            Mux(value(8 * i + 7, 8 * i).orR, 0xff.U(8.W), 0.U(8.W))
        })
    }
    private def reverseBytes(value: UInt): UInt = {
        Cat((0 until (XLEN / 8)).map { i => value(8 * i + 7, 8 * i) })
    }
    val bitIndex = op2(log2Ceil(XLEN) - 1, 0)
    val bitMask = (1.U(XLEN.W) << bitIndex)(XLEN - 1, 0)

    val branch_type  = io.decoded_in.ctrl.branch_type
    val instrStep = Mux(io.decoded_in.instr_len === 2.U, 2.U(XLEN.W), 4.U(XLEN.W))
    val branch_valid = valid && (branch_type =/= BranchType.None) && !io.stall
    val branch_is_br = branch_valid && (branch_type =/= BranchType.JAL) && (branch_type =/= BranchType.JALR)
    val branch_taken = MuxLookup(branch_type, false.B)(
        Seq(
            BranchType.None -> false.B,
            BranchType.JAL  -> true.B,
            BranchType.JALR -> true.B,
            BranchType.BEQ  -> (op1 === op2),
            BranchType.BNE  -> (op1 =/= op2),
            BranchType.BLT  -> (op1.asSInt < op2.asSInt),
            BranchType.BGE  -> (op1.asSInt >= op2.asSInt),
            BranchType.BLTU -> (op1 < op2),
            BranchType.BGEU -> (op1 >= op2)
        )
    )
    val jalrTarget = (op1 + op2) & ~1.U(XLEN.W)
    branch_target := Mux(
        branch_type === BranchType.JAL,
        op1 + op2,
        Mux(branch_type === BranchType.JALR, jalrTarget, io.pc_in + io.decoded_in.br_imm)
    )

    val csr_valid_comb = valid && csr_op =/= CSROps.None
    val csr_write_comb = csr_valid_comb && csr_addr_comb =/= 0.U &&
        !((csr_op === CSROps.RS || csr_op === CSROps.RC) && io.decoded_in.rs2 === 0.U) &&
        !((csr_op === CSROps.RSI || csr_op === CSROps.RCI) && io.decoded_in.rs2 === 0.U)
    val csr_cmd_comb = Mux(csr_write_comb, csr_op.asUInt, 0.U)
    val csr_wdata_comb = op2

    io.csr_valid := csr_valid_comb
    io.csr_addr  := csr_addr_comb
    io.csr_write := csr_write_comb
    io.csr_cmd   := csr_cmd_comb
    io.csr_wdata := csr_wdata_comb

    val isAtomic = mem_atomic
    val mem_addr_calc = op1 + mem_imm
    val mem_size      = Mux(valid && (mem_read || mem_write), Cat(0.U(1.W), io.decoded_in.funct3(1, 0)), 0.U(3.W))
    val atomic_size   = Mux(io.decoded_in.funct3 === "b010".U, 2.U(3.W), 3.U(3.W))
    val mem_signed    = mem_read && !io.decoded_in.funct3(2)
    val base_mask     = MuxLookup(mem_size, 0.U((XLEN / 8).W))(
        Seq(
            0.U -> 1.U,
            1.U -> 3.U,
            2.U -> 15.U,
            3.U -> 255.U
        )
    )
    val byteShift         = mem_addr_calc(log2Ceil(XLEN / 8) - 1, 0)
    val mem_mask          = base_mask << byteShift
    val mem_wdata_aligned = op2 << (byteShift << 3)
    val atomic_mask = Mux(atomic_size === 2.U, 15.U((XLEN / 8).W), 255.U((XLEN / 8).W)) << byteShift
    val atomic_wdata_aligned = Mux(atomic_size === 2.U, Fill(2, op2(31, 0)), op2) << (byteShift << 3)
    val mem_op = Mux(
        isAtomic,
        Mux(
            io.decoded_in.atomic === AtomicOpType.LR,
            MemOpType.LR,
            Mux(io.decoded_in.atomic === AtomicOpType.SC, MemOpType.SC, MemOpType.AMO)
        ),
        Mux(
            mem_read,
            MemOpType.Load,
            Mux(
                mem_write,
                MemOpType.Store,
                Mux(mem_fence, MemOpType.Fence, Mux(mem_fence_i, MemOpType.FenceI, MemOpType.None))
            )
        )
    )

    alu_result := Mux(
        // 如果是无条件分支，则计算写回寄存器的值为PC+4，否则为正常的ALU运算结果
        (branch_type =/= BranchType.JAL && branch_type =/= BranchType.JALR),
        Mux(
            mem_write,
            op2,
            Mux(
                csr_op === CSROps.None,
                MuxLookup(io.decoded_in.ctrl.alu_op, 0.U)(
                    Seq(
                        ALUOps.ADD  -> (op1 + op2),
                        ALUOps.SUB  -> (op1 - op2),
                        ALUOps.SLL  -> (op1 << shamt64),
                        ALUOps.SLT  -> (op1.asSInt < op2.asSInt).asUInt,
                        ALUOps.SLTU -> (op1 < op2).asUInt,
                        ALUOps.SRA  -> (op1.asSInt >> shamt64).asUInt,
                        ALUOps.SRL  -> (op1 >> shamt64),
                        ALUOps.AND  -> (op1 & op2),
                        ALUOps.OR   -> (op1 | op2),
                        ALUOps.XOR  -> (op1 ^ op2),
                        ALUOps.ADDW -> {
                            val sum33    = op1_32.asUInt +& op2_32.asUInt         // width = 33
                            val sum32    = sum33(31, 0)                           // 取低32位
                            val addw_res = Cat(Fill(32, sum32(31)), sum32).asUInt // 符号扩展到 64 位
                            addw_res
                        },
                        ALUOps.SUBW -> {
                            val diff33   = op1_32.asSInt - op2_32.asSInt // SInt，可能为 33 位
                            val diff32   = diff33.asUInt(31, 0)
                            val subw_res = Cat(Fill(32, diff32(31)), diff32)
                            subw_res
                        },
                        ALUOps.SLLW -> {
                            val shifted = (op1_32 << shamt32)(31, 0)
                            Cat(Fill(32, shifted(31)), shifted)
                        },
                        ALUOps.SRLW -> {
                            val shifted = (op1_32 >> shamt32)(31, 0)
                            Cat(Fill(32, shifted(31)), shifted)
                        },
                        ALUOps.SRAW -> {
                            val shifted = (op1_32.asSInt >> shamt32).asUInt(31, 0)
                            Cat(Fill(32, shifted(31)), shifted)
                        },
                        ALUOps.MUL -> unsignedProduct(XLEN - 1, 0),
                        ALUOps.MULH -> signedProduct((2 * XLEN) - 1, XLEN),
                        ALUOps.MULHSU -> signedUnsignedProduct((2 * XLEN) - 1, XLEN),
                        ALUOps.MULHU -> unsignedProduct((2 * XLEN) - 1, XLEN),
                        ALUOps.DIV -> {
                            val divByZero = op2 === 0.U
                            val overflow = op1 === xlenMin && op2 === Fill(XLEN, 1.U(1.W))
                            Mux(divByZero, Fill(XLEN, 1.U(1.W)), Mux(overflow, op1, (op1.asSInt / op2.asSInt).asUInt))
                        },
                        ALUOps.DIVU -> Mux(op2 === 0.U, Fill(XLEN, 1.U(1.W)), op1 / op2),
                        ALUOps.REM -> {
                            val divByZero = op2 === 0.U
                            val overflow = op1 === xlenMin && op2 === Fill(XLEN, 1.U(1.W))
                            Mux(divByZero, op1, Mux(overflow, 0.U, (op1.asSInt % op2.asSInt).asUInt))
                        },
                        ALUOps.REMU -> Mux(op2 === 0.U, op1, op1 % op2),
                        ALUOps.MULW -> sext32((op1_32 * op2_32)(31, 0)),
                        ALUOps.DIVW -> {
                            val divByZero = op2_32 === 0.U
                            val overflow = op1_32 === wordMin && op2_32 === Fill(32, 1.U(1.W))
                            Mux(divByZero, Fill(XLEN, 1.U(1.W)), Mux(overflow, sext32(op1_32), sext32((op1_32.asSInt / op2_32.asSInt).asUInt)))
                        },
                        ALUOps.DIVUW -> Mux(op2_32 === 0.U, Fill(XLEN, 1.U(1.W)), sext32(op1_32 / op2_32)),
                        ALUOps.REMW -> {
                            val divByZero = op2_32 === 0.U
                            val overflow = op1_32 === wordMin && op2_32 === Fill(32, 1.U(1.W))
                            Mux(divByZero, sext32(op1_32), Mux(overflow, 0.U, sext32((op1_32.asSInt % op2_32.asSInt).asUInt)))
                        },
                        ALUOps.REMUW -> Mux(op2_32 === 0.U, sext32(op1_32), sext32(op1_32 % op2_32)),
                        ALUOps.ANDN -> (op1 & ~op2),
                        ALUOps.ORN -> (op1 | ~op2),
                        ALUOps.XNOR -> ~(op1 ^ op2),
                        ALUOps.CLZ -> leadingZeroCount(op1),
                        ALUOps.CTZ -> lowestSetBitIndex(op1),
                        ALUOps.CPOP -> PopCount(op1),
                        ALUOps.CLZW -> leadingZeroCount32(op1),
                        ALUOps.CTZW -> lowestSetBitIndex32(op1),
                        ALUOps.CPOPW -> PopCount(op1_32),
                        ALUOps.MIN -> Mux(op1.asSInt < op2.asSInt, op1, op2),
                        ALUOps.MAX -> Mux(op1.asSInt > op2.asSInt, op1, op2),
                        ALUOps.MINU -> Mux(op1 < op2, op1, op2),
                        ALUOps.MAXU -> Mux(op1 > op2, op1, op2),
                        ALUOps.SEXTB -> sext8(op1),
                        ALUOps.SEXTH -> sext16(op1),
                        ALUOps.ZEXTH -> zext16(op1),
                        ALUOps.ROL -> rotateLeft(op1, shamt64),
                        ALUOps.ROR -> rotateRight(op1, shamt64),
                        ALUOps.RORI -> rotateRight(op1, shamt64),
                        ALUOps.ROLW -> rotateLeft32(op1, op2),
                        ALUOps.RORW -> rotateRight32(op1, op2),
                        ALUOps.RORIW -> rotateRight32(op1, op2),
                        ALUOps.ORCB -> orcByte(op1),
                        ALUOps.REV8 -> reverseBytes(op1),
                        ALUOps.BSET -> (op1 | bitMask),
                        ALUOps.BCLR -> (op1 & ~bitMask),
                        ALUOps.BINV -> (op1 ^ bitMask),
                        ALUOps.BEXT -> ((op1 >> bitIndex)(0)),
                        ALUOps.SH1ADD -> ((op1 << 1) + op2),
                        ALUOps.SH2ADD -> ((op1 << 2) + op2),
                        ALUOps.SH3ADD -> ((op1 << 3) + op2),
                        ALUOps.ADDUW -> (zext32(op1) + op2),
                        ALUOps.SLLIUW -> ((zext32(op1) << shamt64)(XLEN - 1, 0)),
                        ALUOps.SH1ADDUW -> ((zext32(op1) << 1) + op2),
                        ALUOps.SH2ADDUW -> ((zext32(op1) << 2) + op2),
                        ALUOps.SH3ADDUW -> ((zext32(op1) << 3) + op2)
                    )
                ),
                op1 // CSR指令直接写回old CSR值
            )
        ),
        io.pc_in + instrStep
    )

    io.valid_out         := RegEnable(valid, false.B, update_en)
    io.alu_out.instr     := RegEnable(Mux(valid, io.decoded_in.instr, 0.U), 0.U, update_en)
    io.alu_out.instr_len := RegEnable(Mux(valid, io.decoded_in.instr_len, 0.U), 0.U, update_en)
    io.alu_out.funct3    := RegEnable(Mux(valid, io.decoded_in.funct3, 0.U), 0.U, update_en)
    io.alu_out.rd        := RegEnable(Mux(valid, io.decoded_in.rd, 0.U), 0.U, update_en)
    io.alu_out.reg_write := RegEnable(Mux(valid, io.decoded_in.ctrl.reg_write, false.B), false.B, update_en)
    io.alu_out.result    := RegEnable(Mux(valid, alu_result, 0.U), 0.U, update_en)
    io.alu_out.mem_read  := RegEnable(Mux(valid, mem_read, false.B), false.B, update_en)
    io.alu_out.mem_write := RegEnable(Mux(valid, mem_write, false.B), false.B, update_en)
    io.alu_out.mem_addr  := RegEnable(
        Mux(valid, Mux(mem_read || mem_write, mem_addr_calc, 0.U), 0.U),
        0.U,
        update_en
    )
    io.alu_out.mem.valid            := RegEnable(Mux(valid, mem_op =/= MemOpType.None, false.B), false.B, update_en)
    io.alu_out.mem.op               := RegEnable(Mux(valid, mem_op, MemOpType.None), MemOpType.None, update_en)
    io.alu_out.mem.vaddr            := RegEnable(Mux(valid, mem_addr_calc, 0.U), 0.U, update_en)
    io.alu_out.mem.paddr            := RegEnable(Mux(valid, mem_addr_calc, 0.U), 0.U, update_en)
    io.alu_out.mem.size             := RegEnable(Mux(isAtomic, atomic_size, mem_size), 0.U, update_en)
    io.alu_out.mem.signed           := RegEnable(mem_signed, false.B, update_en)
    io.alu_out.mem.mask             := RegEnable(Mux(isAtomic, atomic_mask, mem_mask), 0.U, update_en)
    io.alu_out.mem.wdata            := RegEnable(Mux(isAtomic, atomic_wdata_aligned, mem_wdata_aligned), 0.U, update_en)
    io.alu_out.mem.atomic           := RegEnable(Mux(isAtomic, io.decoded_in.atomic, AtomicOpType.None), AtomicOpType.None, update_en)
    io.alu_out.mem.aq               := RegEnable(Mux(isAtomic, io.decoded_in.aq, false.B), false.B, update_en)
    io.alu_out.mem.rl               := RegEnable(Mux(isAtomic, io.decoded_in.rl, false.B), false.B, update_en)
    io.alu_out.mem.attrs.cacheable  := RegEnable(Mux(valid, mem_read || mem_write || isAtomic, false.B), false.B, update_en)
    io.alu_out.mem.attrs.device     := RegEnable(false.B, false.B, update_en)
    io.alu_out.mem.attrs.bufferable := RegEnable(true.B, true.B, update_en)
    io.alu_out.mem.attrs.allocate   := RegEnable(Mux(valid, mem_read || mem_write || isAtomic, false.B), false.B, update_en)
    io.alu_out.mem.attrs.translate  := RegEnable(Mux(valid, mem_read || mem_write || isAtomic, false.B), false.B, update_en)
    io.alu_out.mem.attrs.executable := RegEnable(false.B, false.B, update_en)

    val fallthroughTarget = io.pc_in + instrStep
    val redirectTarget = Mux(branch_taken, branch_target, fallthroughTarget)
    val correctTakenPrediction = io.pred_taken_in && branch_taken && io.pred_target_in === branch_target
    val forceTakenRedirect = branch_taken && !correctTakenPrediction &&
        ((branch_type === BranchType.JAL) || (branch_type === BranchType.JALR) || branch_is_br)
    val correctNotTaken = !branch_taken && io.pred_taken_in
    val branchRedirect = branch_valid && (forceTakenRedirect || correctNotTaken)
    val branchInfo = WireInit(0.U.asTypeOf(io.br_info))
    branchInfo.pc        := Mux(branch_valid, io.pc_in, 0.U)
    branchInfo.valid     := branch_valid
    branchInfo.is_branch := branch_is_br
    branchInfo.taken     := branch_taken
    branchInfo.target    := redirectTarget
    branchInfo.redirect  := branchRedirect
    dontTouch(branch_valid)
    dontTouch(branch_taken)
    dontTouch(branchRedirect)
    dontTouch(exBypassValid)
    dontTouch(exBypassRd)
    dontTouch(exBypassData)
    // Keep redirect metadata in the same pipeline slot as pc_out/alu_out.
    // Driving PC redirect directly from the current decode wires can mix a
    // previous ALU instruction (for example AUIPC) with the next instruction's
    // JALR control, producing a wrong indirect branch target.
    io.br_info := RegEnable(Mux(valid, branchInfo, 0.U.asTypeOf(io.br_info)), 0.U.asTypeOf(io.br_info), update_en)

    io.csr_commit_valid := RegEnable(csr_valid_comb, false.B, update_en)
    io.csr_commit_addr  := RegEnable(Mux(csr_valid_comb, csr_addr_comb, 0.U), 0.U, update_en)
    io.csr_commit_write := RegEnable(csr_write_comb, false.B, update_en)
    io.csr_commit_cmd   := RegEnable(Mux(csr_valid_comb, csr_cmd_comb, 0.U), 0.U, update_en)
    io.csr_commit_wdata := RegEnable(Mux(csr_valid_comb, csr_wdata_comb, 0.U), 0.U, update_en)

    // EX bypass is only valid for the next sequential consumer. Any redirect or
    // back-pressure cycle breaks that adjacency; otherwise a stalled load can
    // let an older ALU result override the decoded load value several cycles
    // later.
    when(io.trap_valid || branchRedirect || io.stall) {
        exBypassValid := false.B
        exBypassRd := 0.U
        exBypassData := 0.U
    }.elsewhen(update_en) {
        exBypassValid := valid && io.decoded_in.ctrl.reg_write && io.decoded_in.rd =/= 0.U &&
            !mem_read && !mem_write && !mem_atomic && !mem_fence && !mem_fence_i
        exBypassRd   := Mux(valid, io.decoded_in.rd, 0.U)
        exBypassData := Mux(valid, alu_result, 0.U)
    }

    io.trap_info_out := RegEnable(trap_info, 0.U.asTypeOf(io.trap_info_out), update_en)
    io.pc_out        := RegEnable(io.pc_in, 0.U, update_en)
    io.instr_len_out := RegEnable(Mux(valid, io.decoded_in.instr_len, 0.U), 0.U, update_en)
}
