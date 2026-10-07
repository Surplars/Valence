package soc.core

import chisel3._
import soc.core.pipeline.BranchInfo
import soc.isa.CSR

class SatpWriteBarrier(XLEN: Int) extends Module {
    val io = IO(new Bundle {
        val decodeValid = Input(Bool())
        val decodeCsrWrite = Input(Bool())
        val decodeCsrAddr = Input(UInt(12.W))
        val lsuMemoryIdle = Input(Bool())

        val commitValid = Input(Bool())
        val commitCsrWrite = Input(Bool())
        val commitCsrAddr = Input(UInt(12.W))
        val commitPc = Input(UInt(XLEN.W))
        val commitInstrLen = Input(UInt(2.W))

        val holdDecode = Output(Bool())
        val frontendFlush = Output(Bool())
        val redirect = Output(new BranchInfo(XLEN))
    })

    private val decodeSatpWrite = io.decodeValid && io.decodeCsrWrite && io.decodeCsrAddr === CSR.SATP
    private val commitSatpWrite = io.commitValid && io.commitCsrWrite && io.commitCsrAddr === CSR.SATP
    private val commitStep = Mux(io.commitInstrLen === 2.U, 2.U(XLEN.W), 4.U(XLEN.W))

    io.holdDecode := decodeSatpWrite && !io.lsuMemoryIdle
    // Instructions fetched before satp commits were translated with the old
    // address space. Discard them and re-fetch the fall-through PC after the
    // CSR update becomes architectural. This is also required by Linux's
    // relocate_enable_mmu trampoline: its first satp write deliberately makes
    // the physical fall-through PC fault and redirects through stvec.
    io.frontendFlush := commitSatpWrite
    io.redirect.pc := Mux(commitSatpWrite, io.commitPc, 0.U)
    io.redirect.valid := commitSatpWrite
    io.redirect.is_branch := false.B
    io.redirect.taken := commitSatpWrite
    io.redirect.target := Mux(commitSatpWrite, io.commitPc + commitStep, 0.U)
    io.redirect.redirect := commitSatpWrite
}
