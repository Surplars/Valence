package soc.core.pipeline

import chisel3._
import chisel3.util._

class WirteBack(XLEN: Int = 64) extends Module {
    val io = IO(new Bundle {
        val pc_in     = Input(UInt(XLEN.W))
        val valid_in  = Input(Bool())
        val mem_in    = Input(new MemOut(XLEN))
        val trap_info = Input(new TrapInfo(XLEN))

        val reg_wb = Output(new RegWrite(XLEN))
        val commit_instr = Output(UInt(32.W))
        val commit_instr_len = Output(UInt(2.W))
        val commit_skip = Output(Bool())
    })

    io.reg_wb.reg_write := Mux(io.reg_wb.rd === 0.U, false.B, io.mem_in.reg_write && io.valid_in && !io.trap_info.valid)
    io.reg_wb.rd        := io.mem_in.rd
    io.reg_wb.data      := io.mem_in.result
    io.commit_instr     := Mux(io.valid_in && !io.trap_info.valid, io.mem_in.instr, 0.U)
    io.commit_instr_len := Mux(io.valid_in && !io.trap_info.valid, io.mem_in.instr_len, 0.U)
    io.commit_skip      := io.valid_in && !io.trap_info.valid && io.mem_in.diff_skip
}
