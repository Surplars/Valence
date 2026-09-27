package soc.ip.periph.i2c

import chisel3._
import chisel3.util._

class I2CParams(
	val addrWidth: Int = 7,
	val dataWidth: Int = 8,
	val fifoDepth: Int = 16
) {
	require(addrWidth >= 7 && addrWidth <= 10, "I2C address width must be between 7 and 10 bits")
	require(dataWidth == 8, "I2C data width must be 8 bits")
	require(fifoDepth >= 1 && fifoDepth <= 256, "I2C FIFO depth must be between 1 and 256")
}

class I2CPort extends Bundle {
	val sclIn = Input(Bool())
	val sclDriveLow = Output(Bool())

	val sdaIn = Input(Bool())
	val sdaDriveLow = Output(Bool())
}

class I2C(val p: I2CParams) extends Module {
	val io = IO(new Bundle {
		val bus = new I2CPort()
	})

	when(io.bus.sclIn) {

	}
}
