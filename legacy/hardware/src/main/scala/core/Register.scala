package soc.core

import chisel3._

class RegisterFile(XLEN: Int) extends Module {
    val io = IO(new Bundle {
        val write_en   = Input(Bool())
        val write_addr = Input(UInt(5.W))
        val write_data = Input(UInt(XLEN.W))

        val rs1_addr = Input(UInt(5.W))
        val rs2_addr = Input(UInt(5.W))

        val rs1_data = Output(UInt(XLEN.W))
        val rs2_data = Output(UInt(XLEN.W))

        val debug_addr = Input(UInt(5.W))
        val debug_rdata = Output(UInt(XLEN.W))
        val debug_write = Input(Bool())
        val debug_wdata = Input(UInt(XLEN.W))
        // Architectural snapshot for DiffTest/debug. Each entry includes the
        // same-cycle write bypass so retire-visible state is observable without
        // depending on backend register-file read semantics.
        val debug_snapshot = Output(Vec(32, UInt(XLEN.W)))
    })

    val regFile = Mem(32, UInt(XLEN.W))

    val writeEn = io.debug_write || io.write_en
    val writeAddr = Mux(io.debug_write, io.debug_addr, io.write_addr)
    val writeData = Mux(io.debug_write, io.debug_wdata, io.write_data)

    when(writeEn && (writeAddr =/= 0.U)) {
        regFile.write(writeAddr, writeData)
    }

    io.rs1_data := Mux(
        io.rs1_addr === 0.U,
        0.U,
        Mux(io.rs1_addr === io.write_addr && io.write_en, io.write_data, regFile.read(io.rs1_addr))
    )

    io.rs2_data := Mux(
		io.rs2_addr === 0.U,
		0.U,
		Mux(io.rs2_addr === io.write_addr && io.write_en, io.write_data, regFile.read(io.rs2_addr))
	)

    io.debug_rdata := Mux(io.debug_addr === 0.U, 0.U, regFile.read(io.debug_addr))
    for (i <- 0 until 32) {
        io.debug_snapshot(i) := Mux(
            i.U === 0.U,
            0.U,
            Mux(writeEn && writeAddr === i.U, writeData, regFile.read(i.U))
        )
    }
}
