package soc.core.pipeline

import chisel3._
import chisel3.util._

object OpSel extends ChiselEnum {
    val ZERO, RS1, RS2, IMM, PC, CSR, MEM = Value
}

object CSROps extends ChiselEnum {
    val None, RW, RS, RC, RWI, RSI, RCI = Value
}

object ALUOps extends ChiselEnum {
    val NOP, ADD, SUB, OR, AND, XOR, SLL, SLT, SLTU, SRL, SRA, ADDW, SUBW, SLLW, SRLW, SRAW = Value
    val MUL, MULH, MULHSU, MULHU, DIV, DIVU, REM, REMU, MULW, DIVW, DIVUW, REMW, REMUW = Value
    val ANDN, ORN, XNOR, CLZ, CTZ, CPOP, CLZW, CTZW, CPOPW, MIN, MAX, MINU, MAXU, SEXTB, SEXTH, ZEXTH = Value
    val ROL, ROR, RORI, ROLW, RORW, RORIW, ORCB, REV8 = Value
    val BSET, BCLR, BINV, BEXT, SH1ADD, SH2ADD, SH3ADD, ADDUW, SLLIUW, SH1ADDUW, SH2ADDUW, SH3ADDUW = Value
}

object MemOpType extends ChiselEnum {
    val None, Load, Store, Fence, FenceI, LR, SC, AMO = Value
}

object AtomicOpType extends ChiselEnum {
    val None, LR, SC, Swap, Add, Xor, And, Or, Min, Max, MinU, MaxU = Value
}

object TrapReturnType extends ChiselEnum {
    val None, MRET, SRET, MNRET = Value
}

class MemoryAttrs extends Bundle {
    val cacheable  = Bool()
    val device     = Bool()
    val bufferable = Bool()
    val allocate   = Bool()
    val translate  = Bool()
    val executable = Bool()
}

class MemoryAccessInfo(XLEN: Int) extends Bundle {
    val valid  = Bool()
    val op     = MemOpType.Type()
    val vaddr  = UInt(XLEN.W)
    val paddr  = UInt(XLEN.W)
    val size   = UInt(3.W)
    val signed = Bool()
    val mask   = UInt((XLEN / 8).W)
    val wdata  = UInt(XLEN.W)
    val atomic = AtomicOpType.Type()
    val aq     = Bool()
    val rl     = Bool()
    val attrs  = new MemoryAttrs
}

class MemorySystemConfig(XLEN: Int) extends Bundle {
    val priv    = UInt(2.W)
    val data_priv = UInt(2.W)
    val mmu_en  = Bool()
    val satp    = UInt(XLEN.W)
    val pmpcfg0 = UInt(XLEN.W)
    val pmpaddr = Vec(8, UInt(XLEN.W))
    val mxr     = Bool()
    val sum     = Bool()
    val mprv    = Bool()
}

class MemoryFaultInfo(XLEN: Int) extends Bundle {
    val valid = Bool()
    val cause = UInt(XLEN.W)
    val value = UInt(XLEN.W)
}

class TrapInfo(XLEN: Int) extends Bundle {
    val valid  = Bool()
    val pc     = UInt(XLEN.W)
    val cause  = UInt(XLEN.W)
    val value  = UInt(XLEN.W)
    val is_ret = Bool()
    val ret_type = TrapReturnType.Type()
}

object BranchType extends ChiselEnum {
    val None                           = Value // 无分支
    val JAL                            = Value // 无条件直接分支
    val JALR                           = Value // 无条件间接分支
    val BEQ, BNE, BLT, BGE, BLTU, BGEU = Value // 条件分支
    val MRET, SRET, MNRET, ECALL, EBREAK = Value // 特权返回与同步异常指令
    val WFI                            = Value // 等待中断指令
}

class BranchInfo(XLEN: Int) extends Bundle {
    val pc        = UInt(XLEN.W) // 分支指令的PC
    val valid     = Bool()       // 是否分支指令
    val is_branch = Bool()       // 是否为条件分支指令
    val taken     = Bool()       // 实际是否跳转
    val target    = UInt(XLEN.W) // 实际目标地址
    val redirect  = Bool()       // 是否需要重定向
}

class InstrSignals extends Bundle {
    val alu_op      = ALUOps.Type()
    val reg_write   = Bool()
    val mem_read    = Bool()
    val mem_write   = Bool()
    val mem_fence   = Bool()
    val mem_fence_i = Bool()
    val mem_atomic  = Bool()
    val csr_op      = CSROps.Type()
    val branch_type = BranchType.Type()
}

class DecodedInstr(XLEN: Int) extends Bundle {
    val instr   = UInt(32.W)
    val rs1     = UInt(5.W)
    val rs2     = UInt(5.W)
    val op1     = UInt(XLEN.W)
    val op2     = UInt(XLEN.W)
    val rd      = UInt(5.W)
    val ctrl    = new InstrSignals
    val funct3  = UInt(3.W)
    val op2_sel = OpSel.Type()
    val atomic  = AtomicOpType.Type()
    val aq      = Bool()
    val rl      = Bool()
    val instr_len = UInt(2.W) // 0 means 32-bit, 2 means 16-bit
    val br_imm  = Output(UInt(XLEN.W))
    val mem_imm = Output(UInt(XLEN.W))
}

class ALUOut(XLEN: Int) extends Bundle {
    val instr     = UInt(32.W)
    val instr_len = UInt(2.W)
    val result    = UInt(XLEN.W)
    val funct3    = UInt(3.W)
    val rd        = UInt(5.W)
    val reg_write = Bool()
    val mem_read  = Bool()
    val mem_write = Bool()
    val mem_addr  = UInt(XLEN.W)
    val mem       = new MemoryAccessInfo(XLEN)
}

class MemOut(XLEN: Int) extends Bundle {
    val instr     = UInt(32.W)
    val instr_len = UInt(2.W)
    val result    = UInt(XLEN.W)
    val rd        = UInt(5.W)
    val reg_write = Bool()
    val diff_skip = Bool()
}

class RegWrite(XLEN: Int) extends Bundle {
    val data      = UInt(XLEN.W)
    val rd        = UInt(5.W)
    val reg_write = Bool()
}

class FwdSource(XLEN: Int) extends Bundle {
    val valid = Bool()
    val rd    = UInt(5.W)
    val data  = UInt(XLEN.W)
}

class FwdSignals(XLEN: Int) extends Bundle {
    val load_valid = Bool()
    val load_rd    = UInt(5.W)
    val load_data  = UInt(XLEN.W)
    val rd         = UInt(5.W)
    val alu_result = UInt(XLEN.W)
    val reg_write  = Bool()
    val wb_rd        = UInt(5.W)
    val wb_data      = UInt(XLEN.W)
    val wb_reg_write = Bool()
    val prev_rd        = UInt(5.W)
    val prev_data      = UInt(XLEN.W)
    val prev_reg_write = Bool()
}
