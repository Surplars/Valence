package soc.core.ooo

import chisel3._
import chisel3.util._

class BasicCounterWrite(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val address = UInt(12.W)
    val data = UInt(64.W)
}

/** Single-clock RV64 counter bank, with one irrevocable SYSTEM write owner.
  * Reads are combinational; MSU retains the sampled CSR result. A legal write's
  * computed value is captured at execute and becomes visible only at its full
  * owner's actual retirement. No extra issue barrier, cancellation or rollback.
  * Reset clears counters/inhibit. Every later core-clock edge counts, including
  * admission/retirement holds; instret counts only successful ROB retirements.
  */
class BasicCounterBank(p: OooParams) extends Module {
    require(p.basicCounters)
    val io = IO(new Bundle {
        val write = Input(Valid(new BasicCounterWrite(p)))
        val retire = Input(Valid(new RobToken(p)))
        val acceptedCommits = Input(UInt(log2Ceil(p.commitWidth + 1).W))
        val cycle = Output(UInt(64.W))
        val instret = Output(UInt(64.W))
        val inhibit = Output(UInt(3.W))
    })
    val cycle = RegInit(0.U(64.W))
    val instret = RegInit(0.U(64.W))
    val inhibit = RegInit(0.U(3.W))
    val pending = RegInit(false.B)
    val owner = Reg(new BasicCounterWrite(p))
    val applyWrite = pending && io.retire.valid && io.retire.bits.asUInt === owner.token.asUInt

    // Old inhibit governs this edge, including the mcountinhibit retirement.
    when(!inhibit(0)) { cycle := cycle + 1.U }
    when(!inhibit(2)) { instret := instret + io.acceptedCommits }
    when(applyWrite) {
        assert(io.acceptedCommits === 1.U, "a counter CSR write retires alone, never with younger instructions")
        pending := false.B
        switch(owner.address) {
            // Writes override the increment, including this instruction's retirement.
            is(0xb00.U) { cycle := owner.data }
            is(0xb02.U) { instret := owner.data }
            is(0x320.U) { inhibit := owner.data(2, 0) & 5.U }
        }
    }
    when(io.write.valid) {
        assert(!pending, "serialized counter execute cannot replace an unretired write owner")
        assert(io.write.bits.address === 0xb00.U || io.write.bits.address === 0xb02.U ||
            io.write.bits.address === 0x320.U, "counter bank accepts only implemented writable CSRs")
        pending := true.B
        owner := io.write.bits
    }
    assert(io.acceptedCommits <= p.commitWidth.U, "counter increment is the successful ROB commit count")
    io.cycle := cycle
    io.instret := instret
    io.inhibit := inhibit
}
