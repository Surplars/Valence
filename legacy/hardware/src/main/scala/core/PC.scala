package soc.core

import chisel3._
import pipeline.BranchPredictor
import pipeline.BranchInfo

class PC(XLEN: Int, RESET_VECTOR: BigInt) extends Module {
    val io = IO(new Bundle {
        val br_info    = Input(new BranchInfo(XLEN))
        val stall      = Input(Bool())
        val trap_valid = Input(Bool())
        val trap_ret   = Input(Bool())
        val trap_pc    = Input(UInt(XLEN.W))
        val trap_epc   = Input(UInt(XLEN.W))
        val instr_len  = Input(UInt(2.W))

        val fetch_en   = Output(Bool())
        val pc_out     = Output(UInt(XLEN.W))
        val pred_taken = Output(Bool())
        val pred_target = Output(UInt(XLEN.W))
        val redirect   = Output(Bool())
    })

    val rst            = RegInit(true.B)
    val ProgramCounter = RegInit(RESET_VECTOR.U(XLEN.W))
    val bpu            = Module(new BranchPredictor(512))
    val redirect       = io.br_info.redirect || io.trap_valid || io.trap_ret
    val redirectHold   = RegNext(redirect, false.B)

    bpu.io.req_pc := ProgramCounter

    val stepBytes = Mux(io.instr_len === 2.U, 2.U(XLEN.W), 4.U(XLEN.W))
    val pc_next   = ProgramCounter + stepBytes
    val pred_pc = Mux(bpu.io.pred_taken, bpu.io.pred_target, pc_next)

    io.fetch_en := true.B

    when(rst) {
        ProgramCounter := RESET_VECTOR.U
        io.fetch_en    := false.B
        rst            := false.B
    }.elsewhen(redirect) {
        ProgramCounter := Mux(io.trap_ret, io.trap_epc, Mux(io.trap_valid, io.trap_pc, io.br_info.target))
    }.elsewhen(io.stall || redirectHold) {
        ProgramCounter := ProgramCounter
    }.otherwise {
        ProgramCounter := pred_pc
    }

    io.pc_out     := ProgramCounter
    io.pred_taken := bpu.io.pred_taken
    io.pred_target := bpu.io.pred_target
    io.redirect   := redirect

    bpu.io.update_valid  := io.br_info.valid
    bpu.io.update_pc     := io.br_info.pc
    bpu.io.update_taken  := io.br_info.taken
    bpu.io.update_target := io.br_info.target
    bpu.io.update_is_br  := io.br_info.is_branch
}
