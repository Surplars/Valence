package soc.core.ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

/** Combinational range checks: no state, one result per input, no backpressure. */
class SpeculativeRamRangeGsim extends Module {
    val io = IO(new Bundle {
        val address = Input(UInt(64.W))
        val size = Input(UInt(2.W))
        val contained = Output(UInt(12.W))
    })
    private val top = BigInt(1) << 64
    private val windows = Seq(
        (BigInt("80200000", 16), BigInt(512) << 20), // board DDR: not naturally aligned
        (BigInt("80200000", 16), BigInt(1) << 20),   // board UltraRAM
        (BigInt(0x1000), BigInt(0x100)),
        (BigInt(0x1008), BigInt(24)),               // multiple common-alignment blocks
        (BigInt(0x1000), BigInt(8)),                // one minimum-sized block
        (BigInt(0), BigInt(0)),                    // disabled
        (BigInt(3), BigInt(19)),                   // unaligned fallback
        (BigInt(0x1000), BigInt(3)),               // smaller than a doubleword
        (top - 4096, BigInt(4096)),                // exclusive limit exactly 2^64
        (BigInt(0), top),                          // whole address space
        (BigInt(0), BigInt(8)),
        (BigInt("100000000", 16), BigInt(3) << 20))
    io.contained := VecInit(windows.map { case (base, bytes) =>
        SpeculativeRamRange.contains(OooParams(speculativeRamBase = base, speculativeRamBytes = bytes),
            io.address, io.size)
    }).asUInt
}

object SpeculativeRamRangeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SpeculativeRamRangeGsim, Array("--target-dir", args.head))
}
