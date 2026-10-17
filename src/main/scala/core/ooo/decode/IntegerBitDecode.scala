package soc.core.ooo

import chisel3._

/** B 1.0.0 (Zba/Zbb/Zbs), RV64 only. Full fixed fields are checked, including unary rs2 selectors. Private core
  * controls; architectural/software reference tables are independent.
  */
class IntegerBitDecode(parallelLegality: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val instruction  = Input(UInt(32.W))
        val legal        = Output(Bool())
        val operation    = Output(UInt(6.W))
        val word         = Output(Bool())
        val singleSource = Output(Bool())
    })
    io.legal        := false.B
    io.operation    := 15.U
    io.word         := false.B
    io.singleSource := false.B
    // sh1add
    when((io.instruction & "hfe00707f".U) === "h20002033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sh1add
        io.word         := false.B
        io.singleSource := false.B
    }
    // sh1add.uw
    when((io.instruction & "hfe00707f".U) === "h2000203b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sh1addUw
        io.word         := false.B
        io.singleSource := false.B
    }
    // sh2add
    when((io.instruction & "hfe00707f".U) === "h20004033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sh2add
        io.word         := false.B
        io.singleSource := false.B
    }
    // sh2add.uw
    when((io.instruction & "hfe00707f".U) === "h2000403b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sh2addUw
        io.word         := false.B
        io.singleSource := false.B
    }
    // sh3add
    when((io.instruction & "hfe00707f".U) === "h20006033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sh3add
        io.word         := false.B
        io.singleSource := false.B
    }
    // sh3add.uw
    when((io.instruction & "hfe00707f".U) === "h2000603b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sh3addUw
        io.word         := false.B
        io.singleSource := false.B
    }
    // add.uw
    when((io.instruction & "hfe00707f".U) === "h0800003b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.addUw
        io.word         := false.B
        io.singleSource := false.B
    }
    // slli.uw
    when((io.instruction & "hfc00707f".U) === "h0800101b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.slliUw
        io.word         := false.B
        io.singleSource := true.B
    }
    // andn
    when((io.instruction & "hfe00707f".U) === "h40007033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.andn
        io.word         := false.B
        io.singleSource := false.B
    }
    // orn
    when((io.instruction & "hfe00707f".U) === "h40006033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.orn
        io.word         := false.B
        io.singleSource := false.B
    }
    // xnor
    when((io.instruction & "hfe00707f".U) === "h40004033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.xnor
        io.word         := false.B
        io.singleSource := false.B
    }
    // min
    when((io.instruction & "hfe00707f".U) === "h0a004033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.min
        io.word         := false.B
        io.singleSource := false.B
    }
    // minU
    when((io.instruction & "hfe00707f".U) === "h0a005033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.minU
        io.word         := false.B
        io.singleSource := false.B
    }
    // max
    when((io.instruction & "hfe00707f".U) === "h0a006033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.max
        io.word         := false.B
        io.singleSource := false.B
    }
    // maxU
    when((io.instruction & "hfe00707f".U) === "h0a007033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.maxU
        io.word         := false.B
        io.singleSource := false.B
    }
    // clz
    when((io.instruction & "hfff0707f".U) === "h60001013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.clz
        io.word         := false.B
        io.singleSource := true.B
    }
    // clzw
    when((io.instruction & "hfff0707f".U) === "h6000101b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.clz
        io.word         := true.B
        io.singleSource := true.B
    }
    // ctz
    when((io.instruction & "hfff0707f".U) === "h60101013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.ctz
        io.word         := false.B
        io.singleSource := true.B
    }
    // ctzw
    when((io.instruction & "hfff0707f".U) === "h6010101b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.ctz
        io.word         := true.B
        io.singleSource := true.B
    }
    // cpop
    when((io.instruction & "hfff0707f".U) === "h60201013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.cpop
        io.word         := false.B
        io.singleSource := true.B
    }
    // cpopw
    when((io.instruction & "hfff0707f".U) === "h6020101b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.cpop
        io.word         := true.B
        io.singleSource := true.B
    }
    // sextB
    when((io.instruction & "hfff0707f".U) === "h60401013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sextB
        io.word         := false.B
        io.singleSource := true.B
    }
    // sextH
    when((io.instruction & "hfff0707f".U) === "h60501013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.sextH
        io.word         := false.B
        io.singleSource := true.B
    }
    // zextH
    when((io.instruction & "hfff0707f".U) === "h0800403b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.zextH
        io.word         := false.B
        io.singleSource := true.B
    }
    // orcB
    when((io.instruction & "hfff0707f".U) === "h28705013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.orcB
        io.word         := false.B
        io.singleSource := true.B
    }
    // rev8
    when((io.instruction & "hfff0707f".U) === "h6b805013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.rev8
        io.word         := false.B
        io.singleSource := true.B
    }
    // rol
    when((io.instruction & "hfe00707f".U) === "h60001033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.rol
        io.word         := false.B
        io.singleSource := false.B
    }
    // ror
    when((io.instruction & "hfe00707f".U) === "h60005033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.ror
        io.word         := false.B
        io.singleSource := false.B
    }
    // rori
    when((io.instruction & "hfc00707f".U) === "h60005013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.ror
        io.word         := false.B
        io.singleSource := true.B
    }
    // rolw
    when((io.instruction & "hfe00707f".U) === "h6000103b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.rol
        io.word         := true.B
        io.singleSource := false.B
    }
    // rorw
    when((io.instruction & "hfe00707f".U) === "h6000503b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.ror
        io.word         := true.B
        io.singleSource := false.B
    }
    // roriw
    when((io.instruction & "hfe00707f".U) === "h6000501b".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.ror
        io.word         := true.B
        io.singleSource := true.B
    }
    // bclr
    when((io.instruction & "hfe00707f".U) === "h48001033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.bclr
        io.word         := false.B
        io.singleSource := false.B
    }
    // bclri
    when((io.instruction & "hfc00707f".U) === "h48001013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.bclr
        io.word         := false.B
        io.singleSource := true.B
    }
    // bset
    when((io.instruction & "hfe00707f".U) === "h28001033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.bset
        io.word         := false.B
        io.singleSource := false.B
    }
    // bseti
    when((io.instruction & "hfc00707f".U) === "h28001013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.bset
        io.word         := false.B
        io.singleSource := true.B
    }
    // binv
    when((io.instruction & "hfe00707f".U) === "h68001033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.binv
        io.word         := false.B
        io.singleSource := false.B
    }
    // binvi
    when((io.instruction & "hfc00707f".U) === "h68001013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.binv
        io.word         := false.B
        io.singleSource := true.B
    }
    // bext
    when((io.instruction & "hfe00707f".U) === "h48005033".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.bext
        io.word         := false.B
        io.singleSource := false.B
    }
    // bexti
    when((io.instruction & "hfc00707f".U) === "h48005013".U) {
        io.legal        := true.B
        io.operation    := IntegerOp.bext
        io.word         := false.B
        io.singleSource := true.B
    }
    if (parallelLegality) {
        val qualification = Module(new ParallelBitLegality)
        qualification.io.instruction := io.instruction
        io.legal := qualification.io.legal
    }
}
