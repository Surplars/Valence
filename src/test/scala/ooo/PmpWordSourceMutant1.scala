package soc.core.ooo
import chisel3._
import chisel3.util._

/** Parallel range comparison followed by a priority encoder; no serial sixteen-entry decision chain.
  * A matching entry is the first one overlapping any byte, and must cover every byte.
  */
class PmpWordSourceMutant1(entries: Int = 16, alignedWordAccess: Boolean = false,
    naturalAlignedAccess: Boolean = false, val alignedLineAccess: Boolean = false,
    val decodedWordGranularity: Boolean = false) extends Module {
    // Preserve the original constructor for existing compiled/default callers.
    def this(entries: Int, alignedWordAccess: Boolean, naturalAlignedAccess: Boolean, alignedLineAccess: Boolean) =
        this(entries, alignedWordAccess, naturalAlignedAccess, alignedLineAccess, false)
    require(!decodedWordGranularity || alignedWordAccess,
        "decoded word PMP requires the fixed aligned four-byte access domain")
    require(Set(0, 8, 16).contains(entries))
    require(Seq(alignedWordAccess, naturalAlignedAccess, alignedLineAccess).count(identity) <= 1)
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
    if (alignedLineAccess) {
        assert(io.size === 6.U && io.address(5, 0) === 0.U,
            "aligned line PMP checker requires a 64-byte aligned 64-byte access")
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
            // This fixed domain cannot carry out of XLEN, including the last
            // aligned line. Preserve all 65 bits and the generic permission rules.
            else if (alignedLineAccess) Cat(0.U(1.W), io.address(63, 6), 63.U(6.W))
            else if (naturalAlignedAccess) start | lastOffset
            else start + lastOffset
        val overlap = Wire(Vec(entries, Bool()))
        val covers  = Wire(Vec(entries, Bool()))
        val allowed = Wire(Vec(entries, Bool()))
        for (i <- 0 until entries) {
            val cfg  = io.state.cfg(i)
            if (decodedWordGranularity) {
                // PmpState.decodeRegions (including the registered producer) defines
                // every active region in complete four-byte granules. An aligned
                // four-byte request overlaps iff the entire request is covered.
                // Keep bit 64 in both bounds: high addresses never alias low PA.
                when(io.state.regionActive(i)) {
                    assert(io.state.regionLow(i)(1, 0) === 0.U && io.state.regionEnd(i)(1, 0) === 3.U,
                        "word PMP requires complete decoded four-byte region granules")
                }
                val word = Cat(0.U(32.W), io.address(32, 2))
                overlap(i) := io.state.regionActive(i) && word >= io.state.regionLow(i)(64, 2) &&
                    word <= io.state.regionEnd(i)(64, 2)
                covers(i) := true.B
            } else {
                overlap(i) := io.state.regionActive(i) && start <= io.state.regionEnd(i) &&
                    end >= io.state.regionLow(i)
                covers(i) := start >= io.state.regionLow(i) && end <= io.state.regionEnd(i)
            }
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
