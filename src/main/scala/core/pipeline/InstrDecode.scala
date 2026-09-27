package soc.core.pipeline

import chisel3._
import chisel3.util._

import soc.config.Config
import soc.isa.Opcode
import soc.isa.Extension
import soc.core.pipeline.decode.InstrTable
import soc.isa.MCause
import soc.isa.PrivilegeLevel

class InstrDecode(XLEN: Int = 64, enabledExt: Set[Extension.Value] = Config.enabledExt) extends Module {
    val io = IO(new Bundle {
        val valid_in      = Input(Bool())
        val trap_valid    = Input(Bool())
        val pc_in         = Input(UInt(XLEN.W))
        val instr_in      = Input(UInt(32.W))
        val instr_len_in  = Input(UInt(2.W))
        val priv          = Input(UInt(2.W))
        val pred_taken_in = Input(Bool())
        val pred_target_in = Input(UInt(XLEN.W))
        val redirect      = Input(Bool())
        val stall         = Input(Bool())

        val reg_rd_rs1   = Output(UInt(5.W))
        val reg_rd_rs2   = Output(UInt(5.W))
        val reg_rs1_data = Input(UInt(XLEN.W))
        val reg_rs2_data = Input(UInt(XLEN.W))

        val valid_out      = Output(Bool())
        val decoded_out    = Output(new DecodedInstr(XLEN))
        val pc_out         = Output(UInt(XLEN.W))
        val pred_taken_out = Output(Bool())
        val pred_target_out = Output(UInt(XLEN.W))
        val trap_info      = Output(new TrapInfo(XLEN))
    })

    val valid     = !io.redirect && io.valid_in && !io.trap_valid
    val update_en = !io.stall
    val opcode    = io.instr_in(6, 0)
    val funct3    = io.instr_in(14, 12)
    val funct7    = io.instr_in(31, 25)
    val funct5    = io.instr_in(31, 27)
    val imm       = WireInit(0.U(XLEN.W))
    val rs1       = WireInit(0.U(5.W))
    val rs2       = WireInit(0.U(5.W))
    val rd        = io.instr_in(11, 7)

    val imm_i = Cat(Fill(XLEN - 12, io.instr_in(31)), io.instr_in(31, 20)) // I-type (12-bit, sign-extend)
    val imm_s =
        Cat(Fill(XLEN - 12, io.instr_in(31)), io.instr_in(31, 25), io.instr_in(11, 7)) // S-type (12-bit, sign-extend)
    val imm_b = Cat(
        Fill(XLEN - 13, io.instr_in(31)), // total B imm bits = 13 (12..0)
        io.instr_in(31), // imm[12]
        io.instr_in(7), // imm[11]
        io.instr_in(30, 25), // imm[10:5]
        io.instr_in(11, 8), // imm[4:1]
        0.U(1.W) // imm[0] = 0
    ) // B-type (12-bit effective, encoded as 13-bit with low 0, sign-extend)
    val imm_j = Cat(
        Fill(XLEN - 21, io.instr_in(31)), // total J imm bits = 21 (20..0)
        io.instr_in(31), // imm[20]
        io.instr_in(19, 12), // imm[19:12]
        io.instr_in(20), // imm[11]
        io.instr_in(30, 21), // imm[10:1]
        0.U(1.W) // imm[0] = 0
    ) // J-type (20-bit immediate + low 0 => 21 bits, sign-extend)
    val imm_u = Cat( // U-type: instr[31:12] << 12, then sign-extend bit31 up to XLEN
        Fill(XLEN - 32, io.instr_in(31)), // sign-extend from bit31 to high bits (32 = 20 + 12)
        io.instr_in(31, 12), // imm[31:12] (20 bits)
        Fill(12, 0.U) // low 12 bits zero
    )
    val shamt6 = io.instr_in(25, 20) // 6-bit shamt for RV64 shifts (use when isShift && XLEN==64)
    val csr_zimm = Cat(Fill(XLEN - 5, 0.U), io.instr_in(19, 15)) // zero-extend 5-bit zimm

    val ctrl           = Wire(new InstrSignals)
    val decoded        = Wire(new DecodedInstr(XLEN))
    val defaultDecoded = 0.U.asTypeOf(decoded)

    val op1_out = WireInit(0.U(XLEN.W))
    val op2_out = WireInit(0.U(XLEN.W))

    val isShiftImm64 = opcode === Opcode.OP_IMM &&
        (funct3 === "b001".U || funct3 === "b101".U)
    val isShiftImm32 = opcode === Opcode.OP_IMM_32 &&
        (funct3 === "b001".U || funct3 === "b101".U)

    imm := MuxLookup(opcode, 0.U(XLEN.W))(
        Seq(
            Opcode.LUI       -> imm_u,
            Opcode.AUIPC     -> imm_u,
            Opcode.JAL       -> imm_j,
            Opcode.JALR      -> imm_i,
            Opcode.OP_IMM    -> Mux(isShiftImm64, shamt6, imm_i),
            Opcode.OP_IMM_32 -> Mux(isShiftImm32, shamt6, imm_i),
            Opcode.BRANCH    -> imm_b,
            Opcode.LOAD      -> imm_i,
            Opcode.STORE     -> imm_s,
            Opcode.AMO       -> 0.U(XLEN.W),
            Opcode.MISC_MEM  -> 0.U(XLEN.W), // fence指令没有立即数
            Opcode.SYSTEM    -> imm_i,
            Opcode.OP        -> 0.U(XLEN.W)  // R-type指令没有立即数
        )
    )

    val decodeTable = InstrTable.getTable(enabledExt)
    val ctrlSignals = ListLookup(io.instr_in, InstrTable.defaultCtrl, decodeTable)
    val trap_info   = WireInit(0.U.asTypeOf(io.trap_info))

    val op1_sel     = OpSel.safe(ctrlSignals(1).asUInt)._1
    val op2_sel     = OpSel.safe(ctrlSignals(2).asUInt)._1
    val alu_op      = ALUOps.safe(ctrlSignals(3).asUInt)._1
    val reg_write   = ctrlSignals(4).asTypeOf(Bool())
    val mem_read    = ctrlSignals(5).asTypeOf(Bool())
    val mem_write   = ctrlSignals(6).asTypeOf(Bool())
    val csr_op      = CSROps.safe(ctrlSignals(7).asUInt)._1
    val branch_type = BranchType.safe(ctrlSignals(8).asUInt)._1
    val illegal     = io.valid_in &&
        (ctrlSignals(0) === false.B || branch_type === BranchType.ECALL || branch_type === BranchType.EBREAK)
    val isSfenceVma = opcode === Opcode.SYSTEM && funct3 === 0.U && funct7 === "b0001001".U && rd === 0.U

    ctrl.alu_op      := alu_op
    ctrl.reg_write   := reg_write
    ctrl.mem_read    := mem_read
    ctrl.mem_write   := mem_write
    ctrl.mem_fence   := valid && ctrlSignals(0) === true.B &&
        ((opcode === Opcode.MISC_MEM && funct3 === 0.U) || isSfenceVma)
    ctrl.mem_fence_i := valid && ctrlSignals(0) === true.B && opcode === Opcode.MISC_MEM && funct3 === "b001".U
    ctrl.mem_atomic  := valid && ctrlSignals(0) === true.B && opcode === Opcode.AMO
    ctrl.csr_op      := csr_op
    ctrl.branch_type := branch_type

    // 选择寄存器地址输出
    when(op1_sel === OpSel.RS1) {
        rs1           := io.instr_in(19, 15)
        io.reg_rd_rs1 := rs1
    }.otherwise {
        rs1           := 0.U
        io.reg_rd_rs1 := 0.U
    }
    when(csr_op === CSROps.RWI || csr_op === CSROps.RSI || csr_op === CSROps.RCI) {
        rs2           := io.instr_in(19, 15) // CSR zimm 指令 rs2 字段编码 zimm
        io.reg_rd_rs2 := 0.U
    }.elsewhen(op2_sel === OpSel.RS1) {
        rs2           := io.instr_in(19, 15) // CSR rs1
        io.reg_rd_rs2 := rs2
    }.elsewhen(op2_sel === OpSel.RS2) {
        rs2           := io.instr_in(24, 20)
        io.reg_rd_rs2 := rs2
    }.otherwise {
        rs2           := 0.U
        io.reg_rd_rs2 := 0.U
    }

    op1_out := MuxLookup(op1_sel, 0.U)(
        Seq(
            OpSel.ZERO -> 0.U,
            OpSel.RS1  -> io.reg_rs1_data,
            OpSel.RS2  -> io.reg_rs2_data,
            OpSel.IMM  -> imm,
            OpSel.PC   -> io.pc_in,
            OpSel.CSR  -> imm,
            OpSel.MEM  -> 0.U
        )
    )
    op2_out := MuxLookup(op2_sel, 0.U)(
        Seq(
            OpSel.ZERO -> 0.U,
            OpSel.RS1  -> io.reg_rs2_data,
            OpSel.RS2  -> io.reg_rs2_data,
            OpSel.IMM  -> imm,
            OpSel.PC   -> io.pc_in,
            OpSel.CSR  -> 0.U,
            OpSel.MEM  -> 0.U
        )
    )

    decoded.ctrl    := ctrl
    decoded.instr   := io.instr_in
    decoded.rs1     := rs1
    decoded.rs2     := rs2
    decoded.op1     := op1_out
    decoded.op2     := op2_out
    decoded.rd      := rd
    decoded.funct3  := funct3
    decoded.op2_sel := op2_sel
    decoded.atomic := MuxLookup(funct5, AtomicOpType.None)(
        Seq(
            "b00010".U -> AtomicOpType.LR,
            "b00011".U -> AtomicOpType.SC,
            "b00001".U -> AtomicOpType.Swap,
            "b00000".U -> AtomicOpType.Add,
            "b00100".U -> AtomicOpType.Xor,
            "b01100".U -> AtomicOpType.And,
            "b01000".U -> AtomicOpType.Or,
            "b10000".U -> AtomicOpType.Min,
            "b10100".U -> AtomicOpType.Max,
            "b11000".U -> AtomicOpType.MinU,
            "b11100".U -> AtomicOpType.MaxU
        )
    )
    decoded.aq := io.instr_in(26)
    decoded.rl := io.instr_in(25)
    decoded.br_imm  := Mux(
        valid,
        Mux(
            ((ctrl.branch_type =/= BranchType.JAL) && (ctrl.branch_type =/= BranchType.JALR) && (ctrl.branch_type =/= BranchType.None)),
            imm,
            0.U
        ),
        0.U
    )
    decoded.mem_imm := Mux(valid && (ctrl.mem_read || ctrl.mem_write), imm, 0.U)
    decoded.instr_len := io.instr_len_in

    trap_info.valid := valid && illegal
    trap_info.pc    := io.pc_in
    trap_info.cause := Mux(
        illegal,
        MuxLookup(branch_type, MCause.IllegalInstr)(
            Seq(
                BranchType.ECALL -> MuxLookup(io.priv, MCause.EcallFromMMode)(
                    Seq(
                        PrivilegeLevel.User       -> MCause.EcallFromUMode,
                        PrivilegeLevel.Supervisor -> MCause.EcallFromSMode,
                        PrivilegeLevel.Machine    -> MCause.EcallFromMMode
                    )
                ),
                BranchType.EBREAK -> MCause.Breakpoint
            )
        ),
        0.U
    )
    trap_info.value := Mux(
        valid && branch_type === BranchType.EBREAK,
        io.pc_in,
        Mux(valid && illegal && branch_type =/= BranchType.ECALL, io.instr_in, 0.U)
    )
    trap_info.is_ret := valid && (branch_type === BranchType.MRET || branch_type === BranchType.SRET || branch_type === BranchType.MNRET)
    trap_info.ret_type := MuxLookup(branch_type, TrapReturnType.None)(
        Seq(
            BranchType.MRET  -> TrapReturnType.MRET,
            BranchType.SRET  -> TrapReturnType.SRET,
            BranchType.MNRET -> TrapReturnType.MNRET
        )
    )

    val validOutReg = RegInit(false.B)
    val decodedOutReg = RegInit(defaultDecoded)
    val pcOutReg = RegInit(0.U(XLEN.W))
    val predTakenOutReg = RegInit(false.B)
    val predTargetOutReg = RegInit(0.U(XLEN.W))
    val trapInfoReg = RegInit(0.U.asTypeOf(io.trap_info))

    when(io.trap_valid || io.redirect) {
        validOutReg := false.B
        decodedOutReg := defaultDecoded
        pcOutReg := 0.U
        predTakenOutReg := false.B
        predTargetOutReg := 0.U
        trapInfoReg := 0.U.asTypeOf(io.trap_info)
    }.elsewhen(update_en) {
        validOutReg := valid
        decodedOutReg := Mux(valid, decoded, defaultDecoded)
        pcOutReg := io.pc_in
        predTakenOutReg := io.pred_taken_in
        predTargetOutReg := io.pred_target_in
        trapInfoReg := trap_info
    }

    io.valid_out := validOutReg
    io.decoded_out := decodedOutReg
    io.pc_out := pcOutReg
    io.pred_taken_out := predTakenOutReg
    io.pred_target_out := predTargetOutReg
    io.trap_info := trapInfoReg
}
