package soc.core.ooo

import chisel3._
import chisel3.util._

/** Vivado blk_mem_gen_0: Native dual-port ROM, 32768 x 32, ENA/ENB, no output registers.
  * Both read ports have one cycle of latency. Initialization is owned by the IP COE file.
  */
class VivadoBootRom extends BlackBox {
    override def desiredName: String = "blk_mem_gen_0"
    val io = IO(new Bundle {
        val clka = Input(Clock())
        val ena = Input(Bool())
        val addra = Input(UInt(15.W))
        val douta = Output(UInt(32.W))
        val clkb = Input(Clock())
        val enb = Input(Bool())
        val addrb = Input(UInt(15.W))
        val doutb = Output(UInt(32.W))
    })
}

/** One write port and one read port on a common clock. Byte enables remain 8 bits, not
  * 9-bit ECC lanes. READ_FIRST plus >=3 read stages enables the UltraRAM output register.
  * No INIT file is supplied: boot firmware loads executable RAM at runtime.
  */
class VivadoUltraRam(bytes: Int, readLatency: Int) extends BlackBox(Map(
    "MEMORY_SIZE" -> bytes * 8,
    "MEMORY_PRIMITIVE" -> "ultra",
    "CLOCKING_MODE" -> "common_clock",
    "MEMORY_INIT_FILE" -> "none",
    "MEMORY_INIT_PARAM" -> "0",
    "USE_MEM_INIT" -> 0,
    "ECC_MODE" -> "no_ecc",
    "ADDR_WIDTH_A" -> log2Ceil(bytes / 8),
    "ADDR_WIDTH_B" -> log2Ceil(bytes / 8),
    "WRITE_DATA_WIDTH_A" -> 64,
    "READ_DATA_WIDTH_B" -> 64,
    "BYTE_WRITE_WIDTH_A" -> 8,
    "READ_LATENCY_B" -> readLatency,
    "WRITE_MODE_B" -> "read_first",
    "READ_RESET_VALUE_B" -> "0",
    "RST_MODE_B" -> "SYNC",
    "CASCADE_HEIGHT" -> 1,
    "AUTO_SLEEP_TIME" -> 0,
    "WAKEUP_TIME" -> "disable_sleep",
    "MESSAGE_CONTROL" -> 0,
    "SIM_ASSERT_CHK" -> 1
)) {
    override def desiredName: String = "xpm_memory_sdpram"
    val io = IO(new Bundle {
        val clka = Input(Clock())
        val ena = Input(Bool())
        val wea = Input(UInt(8.W))
        val addra = Input(UInt(log2Ceil(bytes / 8).W))
        val dina = Input(UInt(64.W))
        val clkb = Input(Clock())
        val enb = Input(Bool())
        val addrb = Input(UInt(log2Ceil(bytes / 8).W))
        val doutb = Output(UInt(64.W))
        val rstb = Input(Bool())
        val regceb = Input(Bool())
        val sleep = Input(Bool())
        val injectsbiterra = Input(Bool())
        val injectdbiterra = Input(Bool())
        val sbiterrb = Output(Bool())
        val dbiterrb = Output(Bool())
    })
}
