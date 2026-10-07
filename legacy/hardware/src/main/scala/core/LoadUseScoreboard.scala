package soc.core

import chisel3._
import soc.core.pipeline.MemOpType

class LoadUseScoreboard(XLEN: Int) extends Module {
    val io = IO(new Bundle {
        val flush = Input(Bool())

        val aluValid = Input(Bool())
        val aluRegWrite = Input(Bool())
        val aluRd = Input(UInt(5.W))
        val aluPc = Input(UInt(XLEN.W))
        val aluMemOp = Input(MemOpType.Type())

        val lsuLoadDataValid = Input(Bool())
        val lsuLoadDataRd = Input(UInt(5.W))
        val wbRegWrite = Input(Bool())
        val wbRd = Input(UInt(5.W))

        val decodeValid = Input(Bool())
        val decodeRs1 = Input(UInt(5.W))
        val decodeRs2 = Input(UInt(5.W))

        val decodeUsesPending = Output(Bool())
        val pending = Output(Bool())
        val pendingRd = Output(UInt(5.W))
        val newLoadLike = Output(Bool())
        val complete = Output(Bool())
        val issued = Output(Bool())
        val issuedRd = Output(UInt(5.W))
    })

    private def isLoadLikeOp(op: MemOpType.Type): Bool =
        op === MemOpType.Load || op === MemOpType.LR || op === MemOpType.SC || op === MemOpType.AMO

    private def usesRd(rs1: UInt, rs2: UInt, rd: UInt): Bool =
        rd =/= 0.U && ((rs1 === rd && rs1 =/= 0.U) || (rs2 === rd && rs2 =/= 0.U))

    val pending = RegInit(false.B)
    val pendingRd = RegInit(0.U(5.W))
    val issued = RegInit(false.B)
    val issuedPc = RegInit(0.U(XLEN.W))
    val issuedRd = RegInit(0.U(5.W))

    val aluLoadLike = io.aluValid && io.aluRegWrite && io.aluRd =/= 0.U && isLoadLikeOp(io.aluMemOp)
    val newLoadLike = aluLoadLike && (!issued || issuedPc =/= io.aluPc || issuedRd =/= io.aluRd)
    val lsuCompletesPending = io.lsuLoadDataValid && io.lsuLoadDataRd === pendingRd
    val wbCompletesPending = io.wbRegWrite && io.wbRd === pendingRd
    val complete = pending && (lsuCompletesPending || wbCompletesPending)
    val newLoadLikeComplete = newLoadLike && io.lsuLoadDataValid && io.lsuLoadDataRd === io.aluRd

    val decodeUsesPendingReg =
        pending && !complete && io.decodeValid && usesRd(io.decodeRs1, io.decodeRs2, pendingRd)
    val decodeUsesAluLoadLike =
        newLoadLike && io.decodeValid && usesRd(io.decodeRs1, io.decodeRs2, io.aluRd)

    io.decodeUsesPending := !io.flush && (decodeUsesPendingReg || decodeUsesAluLoadLike)

    when(io.flush) {
        pending := false.B
        pendingRd := 0.U
    }.elsewhen(complete) {
        // A new load-like instruction can enter ALU in the same cycle that the
        // previous load completes. Preserve the new dependency unless it also
        // returns immediately.
        pending := newLoadLike && !newLoadLikeComplete
        pendingRd := Mux(newLoadLike && !newLoadLikeComplete, io.aluRd, 0.U)
    }.elsewhen(newLoadLike) {
        pending := !newLoadLikeComplete
        pendingRd := Mux(newLoadLikeComplete, 0.U, io.aluRd)
    }

    when(io.flush) {
        issued := false.B
        issuedPc := 0.U
        issuedRd := 0.U
    }.elsewhen(aluLoadLike) {
        issued := true.B
        issuedPc := io.aluPc
        issuedRd := io.aluRd
    }.otherwise {
        issued := false.B
        issuedPc := 0.U
        issuedRd := 0.U
    }

    io.pending := pending
    io.pendingRd := pendingRd
    io.newLoadLike := newLoadLike
    io.complete := complete
    io.issued := issued
    io.issuedRd := issuedRd
}
