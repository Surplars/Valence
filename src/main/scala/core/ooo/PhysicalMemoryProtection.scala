package soc.core.ooo

import chisel3._
import chisel3.util._

/** RV64 PMP state: 16 entries, 56-bit physical addresses and four-byte minimum granularity. */
class PmpState extends Bundle {
    val cfg  = Vec(16, UInt(8.W))
    val addr = Vec(16, UInt(54.W))
    // State-only PMP range decoding is shared by all address checkers.
    val regionLow = Vec(16, UInt(65.W))
    val regionEnd = Vec(16, UInt(65.W))
    val regionActive = Vec(16, Bool())
}

object PmpState {
    /** Drive the decoded range fields once, at the producer of a PMP state. */
    def decodeRegions(state: PmpState): Unit = {
        for (i <- 0 until 16) {
            val mode = state.cfg(i)(4, 3)
            val top = Cat(0.U(9.W), state.addr(i), 0.U(2.W))
            val low = if (i == 0) 0.U(65.W) else Cat(0.U(9.W), state.addr(i - 1), 0.U(2.W))
            val napotAddress = Cat(0.U(1.W), state.addr(i))
            val napotMask = (((napotAddress ^ (napotAddress + 1.U)) << 2) | 3.U)(55, 0)
            val napotBase = Cat(state.addr(i), 0.U(2.W)) & ~napotMask
            state.regionLow(i) := Mux(mode === 1.U, low,
                Mux(mode === 2.U, top, Cat(0.U(9.W), napotBase)))
            state.regionEnd(i) := Mux(mode === 1.U, top - 1.U,
                Mux(mode === 2.U, top + 3.U, Cat(0.U(9.W), napotBase | napotMask)))
            state.regionActive(i) := mode =/= 0.U && (mode =/= 1.U || top > low)
        }
    }
}

object PmpAccess {
    val read      = 0.U(2.W)
    val write     = 1.U(2.W)
    val execute   = 2.U(2.W)
    val readWrite = 3.U(2.W)
}

/** Parallel range comparison followed by a priority encoder; no serial sixteen-entry decision chain.
  * A matching entry is the first one overlapping any byte, and must cover every byte.
  */
class PmpChecker(entries: Int = 16, alignedWordAccess: Boolean = false,
    naturalAlignedAccess: Boolean = false) extends Module {
    require(Set(0, 8, 16).contains(entries))
    require(!alignedWordAccess || !naturalAlignedAccess)
    val io = IO(new Bundle {
        val state     = Input(new PmpState)
        val address   = Input(UInt(64.W))
        val size      = Input(UInt(3.W))
        val privilege = Input(UInt(2.W))
        val access    = Input(UInt(2.W))
        val denied    = Output(Bool())
    })
    if (alignedWordAccess) {
        assert(io.size === 2.U && io.address(1, 0) === 0.U,
            "aligned word PMP checker requires a four-byte aligned four-byte access")
    }
    if (naturalAlignedAccess) {
        val alignmentMask = MuxLookup(io.size, 7.U(3.W))(
            Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
        assert(io.size <= 3.U && (io.address(2, 0) & alignmentMask) === 0.U,
            "natural PMP checker requires an aligned access of at most eight bytes")
    }
    if (entries == 0) {
        io.denied := false.B
    } else {
        val start = Cat(0.U(1.W), io.address)
        // Decode length-1 before extending it. A dynamic 65-bit shift followed
        // by subtraction otherwise emits a 72-bit add/subtract chain for sizes 0..7.
        // Preserve bit 64 so an access wrapping XLEN can never fit a low PMP region.
        val lastOffset = MuxLookup(io.size, 0.U(7.W))(
            (0 to 7).map(s => s.U -> ((BigInt(1) << s) - 1).U(7.W)))
        // A four-byte aligned word cannot carry out of XLEN: its final byte is
        // simply the same upper address bits with low bits 11. Keep ALL 65 bits
        // and the exact first-overlap/whole-range/locked-M permission algorithm.
        val end = if (alignedWordAccess) Cat(0.U(1.W), io.address(63, 2), 3.U(2.W))
            else if (naturalAlignedAccess) start | lastOffset
            else start + lastOffset
        val overlap = Wire(Vec(entries, Bool()))
        val covers  = Wire(Vec(entries, Bool()))
        val allowed = Wire(Vec(entries, Bool()))
        for (i <- 0 until entries) {
            val cfg  = io.state.cfg(i)
            overlap(i) := io.state.regionActive(i) && start <= io.state.regionEnd(i) &&
                end >= io.state.regionLow(i)
            covers(i) := start >= io.state.regionLow(i) && end <= io.state.regionEnd(i)
            val permission = MuxLookup(io.access, false.B)(Seq(
                PmpAccess.read      -> cfg(0),
                PmpAccess.write     -> cfg(1),
                PmpAccess.execute   -> cfg(2),
                PmpAccess.readWrite -> (cfg(0) && cfg(1))
            ))
            allowed(i) := io.privilege === 3.U && !cfg(7) || permission
        }
        val hit = overlap.asUInt.orR
        val first = Wire(Vec(entries, Bool()))
        for (i <- 0 until entries) {
            val earlier = if (i == 0) false.B else VecInit(overlap.take(i)).asUInt.orR
            first(i) := overlap(i) && !earlier
        }
        val deniedMatch = VecInit((0 until entries).map(i =>
            first(i) && (!covers(i) || !allowed(i)))).asUInt.orR
        io.denied := deniedMatch || (!hit && io.privilege =/= 3.U)
    }
}
