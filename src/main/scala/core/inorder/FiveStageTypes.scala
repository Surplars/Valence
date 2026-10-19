package soc.core.inorder

import chisel3._
import chisel3.util._

class FiveStageFetchResponse extends Bundle {
    val instruction = UInt(32.W)
    val error = Bool()
    val pageFault = Bool()
    val compressed = Bool()
    val secondHalfFault = Bool()
}

/** One ordered request/response owner per port. Stores require an acknowledgement.
  * Addresses are byte addresses. Load response data is the containing aligned XLEN word.
  * Store data/mask are shifted to that word's byte lanes; size describes the actual access.
  */
class FiveStageDataRequest(val p: FiveStageConfig) extends Bundle {
    val address = UInt(p.xlen.W)
    val write = Bool()
    val size = UInt(2.W)
    val data = UInt(p.xlen.W)
    val mask = UInt((p.xlen / 8).W)
    val noAllocate = Bool()
    val atomic = Bool()
    val atomicOperation = UInt(5.W)
}

class FiveStageDataResponse(val p: FiveStageConfig) extends Bundle {
    val data = UInt(p.xlen.W)
    val error = Bool()
    val pageFault = Bool()
    val fetchSpan = Bool() // complete containing word was authorized for instruction fetch
    val parcelClasses = if (p.cacheFetchPredecode) Some(UInt(8.W)) else None
}

class FiveStageRetire(val p: FiveStageConfig) extends Bundle {
    val pc = UInt(p.xlen.W)
    val instruction = UInt(32.W)
    val nextPc = UInt(p.xlen.W)
    val rd = UInt(5.W)
    val writesRd = Bool()
    val data = UInt(p.xlen.W)
    val trap = Bool()
    val cause = UInt(p.xlen.W)
    val tval = UInt(p.xlen.W)
    val floating = if (p.withF) Some(new I1FloatingPointCommit) else None
}

object FiveStageAluOp {
    val add = 0.U(4.W)
    val subtract = 1.U(4.W)
    val shiftLeft = 2.U(4.W)
    val lessSigned = 3.U(4.W)
    val lessUnsigned = 4.U(4.W)
    val xorBits = 5.U(4.W)
    val shiftRight = 6.U(4.W)
    val shiftArithmetic = 7.U(4.W)
    val orBits = 8.U(4.W)
    val andBits = 9.U(4.W)
}

class FiveStageDecodeControl(val p: FiveStageConfig) extends Bundle {
    val legal = Bool()
    val rs1 = UInt(5.W)
    val rs2 = UInt(5.W)
    val rd = UInt(5.W)
    val usesRs1 = Bool()
    val usesRs2 = Bool()
    val writesRd = Bool()
    val immediate = UInt(p.xlen.W)
    val useImmediate = Bool()
    val usePc = Bool()
    val aluOp = UInt(4.W)
    val word = Bool()
    val branch = Bool()
    val jump = Bool()
    val jumpRegister = Bool()
    val funct3 = UInt(3.W)
    val load = Bool()
    val store = Bool()
    val mulDiv = Bool()
    val atomic = Bool()
    val atomicOperation = UInt(5.W)
    val csr = Bool()
    val csrAddress = UInt(12.W)
    val csrImmediate = Bool()
    val ecall = Bool()
    val ebreak = Bool()
    val mret = Bool()
    val sret = Bool()
    val sfence = Bool()
    val wfi = Bool()
    val fenceI = Bool()
    val serial = Bool()
    val floating = Bool()
    val fpExecute = Bool()
    val fpWrites = Bool()
}

class FiveStageInstruction(val p: FiveStageConfig) extends Bundle {
    val pc = UInt(p.xlen.W)
    val instruction = UInt(32.W)
    val fetchError = Bool()
    val fetchPageFault = Bool()
    val compressed = Bool()
    val fetchSecondHalfFault = Bool()
    val predictedNextPc = UInt(p.xlen.W)
}

class FiveStageExecutePacket(val p: FiveStageConfig) extends Bundle {
    val instruction = new FiveStageInstruction(p)
    val control = new FiveStageDecodeControl(p)
    val expanded = if (p.withF) Some(UInt(32.W)) else None
    val resultMask = if (p.fpgaTimingCuts) Some(UInt(5.W)) else None
    // Existing ID/RF/EX boundaries, not extra architectural stages.
    val operandEnable = if (p.fpgaTimingCuts) Some(UInt(2.W)) else None
    val numericalLegal = if (p.fpgaTimingCuts) Some(Bool()) else None
    val numericalRounding = if (p.fpgaTimingCuts && p.withF) Some(UInt(3.W)) else None
}

class FiveStageCompletion(val p: FiveStageConfig) extends Bundle {
    val instruction = new FiveStageInstruction(p)
    val control = new FiveStageDecodeControl(p)
    val result = UInt(p.xlen.W)
    val address = UInt(p.xlen.W)
    val storeData = UInt(p.xlen.W)
    val storeSource = UInt(p.xlen.W) // unshifted rs2 at the optional ADDR boundary
    val storeMask = UInt((p.xlen / 8).W)
    val nextPc = UInt(p.xlen.W)
    val branchTaken = Bool()
    val branchTarget = UInt(p.xlen.W)
    val fault = Bool()
    val cause = UInt(p.xlen.W)
    val tval = UInt(p.xlen.W)
    val csrWrite = Bool()
    val csrData = UInt(p.xlen.W)
    // Decoded at EX and carried through the existing owner; avoid late WB
    // CSR-address decode feeding frontend/MMU recovery on the same edge.
    val contextBarrier = if (p.fpgaTimingCuts) Some(Bool()) else None
    val translationInvalidate = if (p.fpgaTimingCuts) Some(Bool()) else None
    val floating = if (p.withF) Some(new I1FloatingPointCommit) else None
}

/** Real raw-response register boundary; load extraction and precise fault selection occur in CMP. */
class FiveStageMemoryReturn(val p: FiveStageConfig) extends Bundle {
    val completion = new FiveStageCompletion(p)
    val response = new FiveStageDataResponse(p)
    val accessed = Bool()
}
