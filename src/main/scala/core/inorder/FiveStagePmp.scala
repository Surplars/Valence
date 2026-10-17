package soc.core.inorder

import chisel3._
import chisel3.util._

/** Parallel range checks + lowest-index winner, not a serial priority chain of XLEN comparators.
  * Checks the COMPLETE access; a partial first match denies even M-mode. G=0 (4-byte grain).
  * Permissions use the effective privilege. Implicit PTE reads must pass privilege=S.
  */
class FiveStagePmp(p: FiveStageConfig, registerComparisons: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val entries = Input(Vec(p.pmpEntries, new FiveStagePmpEntry(p)))
        val address = Input(UInt(p.xlen.W))
        val size = Input(UInt(4.W)) // log2 bytes, including a full cache-line permission probe
        val privilege = Input(UInt(2.W))
        val execute = Input(Bool()); val write = Input(Bool())
        val allow = Output(Bool())
        val capture = if (registerComparisons) Some(Input(Bool())) else None
    })
    val width = p.physicalBits + 1
    private val splitRelations = registerComparisons && p.fpgaTimingCuts
    private def captured(value: Bool): Bool =
        if (splitRelations) RegEnable(value, io.capture.get) else value
    private def checked(value: UInt): UInt =
        if (registerComparisons && !splitRelations) RegEnable(value, io.capture.get) else value
    val start = Cat(0.U(1.W), io.address(p.physicalBits - 1, 0))
    val length = (1.U(width.W) << io.size)(width - 1, 0)
    val end = start +& length
    // A legal PMP query is at most one page. Split the low-page carry
    // from high-address comparisons: do not cascade a 37-bit address
    // addition into every 37-bit TOR comparator on the authorization path.
    // Unaligned/partial overlaps remain legal INPUTS to this checker.
    val lowSum = io.address(11, 0) +& (1.U(13.W) << io.size)(12, 0)
    val lowEnd = lowSum(11, 0)
    // Exact power-of-two carry, expressed without relying on a sliced
    // adder's implicit carry propagation in an optimized simulator graph.
    // Also a parallel reduction tree, not an extra serial arithmetic stage.
    val lowCarry = MuxLookup(io.size, false.B)((0 to 12).map { shift =>
        shift.U -> (if (shift == 12) true.B else io.address(11, shift).andR)
    })
    val high = Cat(0.U(1.W), io.address(p.physicalBits - 1, 12))
    val nextHigh = high + 1.U
    def less(a: UInt, b: UInt): Bool = if (splitRelations) {
        val w = math.max(a.getWidth, b.getWidth)
        val left = a.pad(w); val right = b.pad(w)
        // Reuse the EXISTING comparison edge for bounded native relations.
        // Lexicographic/permission/priority reduction is AFTER that edge.
        // No extra authorization state, request slot or visible cycle.
        // The routed12-bit mapping has lower fanout/state than the trial8-bit
        // mapping on this FPGA. Keep the same comparison/authorization edge.
        val chunks = (0 until w by 12).map { low =>
            val high = math.min(w - 1, low + 11)
            (RegEnable(left(high, low) < right(high, low), io.capture.get),
                RegEnable(left(high, low) === right(high, low), io.capture.get))
        }
        chunks.indices.map(i => chunks(i)._1 &&
            chunks.drop(i + 1).map(_._2).foldLeft(true.B)(_ && _)).reduce(_ || _)
    } else if (p.fpgaTimingCuts) I1TimingMath.less(a, b) else a < b
    def equal(a: UInt, b: UInt): Bool =
        captured(if (p.fpgaTimingCuts) I1TimingMath.equal(a, b) else a === b)
    def endAtMost(boundary: UInt): Bool = {
        val boundHigh = boundary(p.physicalBits, 12)
        val boundLow = boundary(11, 0)
        val lowOk = !less(boundLow, lowEnd)
        Mux(captured(lowCarry),
            less(nextHigh, boundHigh) || (equal(nextHigh, boundHigh) && lowOk),
            less(high, boundHigh) || (equal(high, boundHigh) && lowOk))
    }
    val sizeAllowed = captured(io.size <= 12.U)
    val inRange = captured(if (p.xlen > p.physicalBits)
        io.address(p.xlen - 1, p.physicalBits) === 0.U else true.B) &&
        (if (p.fpgaTimingCuts) endAtMost((BigInt(1) << p.physicalBits).U(width.W))
         else end <= (BigInt(1) << p.physicalBits).U) && sizeAllowed
    val checkedRange = checked(inRange.asUInt).asBool
    val checkedMachine = checked(captured(io.privilege === 3.U).asUInt).asBool
    if (p.pmpEntries == 0) {
        io.allow := checkedRange
    } else {
        val matches = Wire(Vec(p.pmpEntries, Bool()))
        val grants = Wire(Vec(p.pmpEntries, Bool()))
        for (i <- 0 until p.pmpEntries) {
            val e = io.entries(i)
            val bottom = e.lower
            val top = e.upper
            val endsInside = if (p.fpgaTimingCuts) endAtMost(top) else end <= top
            val overlapsBottom = if (p.fpgaTimingCuts) !endAtMost(bottom) else end > bottom
            matches(i) := captured(e.config(4, 3) =/= 0.U) && less(start, top) && overlapsBottom
            val permission = Mux(io.execute, e.config(2), Mux(io.write, e.config(1), e.config(0)))
            grants(i) := !less(start, bottom) && endsInside &&
                captured((io.privilege === 3.U && !e.config(7)) || permission)
            if (p.fpgaTimingCuts) {
                val expectedEnd = captured(end <= top)
                val expectedOverlap = captured(end > bottom)
                val comparing = if (splitRelations) RegNext(io.capture.get, false.B) else true.B
                when(comparing && sizeAllowed) {
                    assert(endsInside === expectedEnd && overlapsBottom === expectedOverlap,
                        "page-split PMP end comparison must preserve unaligned/partial overlaps")
                }
            }
        }
        // Capture the parallel range relations before priority/permission
        // reduction. This is a cold authorization cut, not another request
        // owner; cached full-page proofs keep their existing hit protocol.
        val matched = checked(matches.asUInt)
        val granted = checked(grants.asUInt)
        val winners = (0 until p.pmpEntries).map { i =>
            matched(i) && (if (i == 0) true.B else !matched(i - 1, 0).orR)
        }
        val selectedGrant = VecInit(winners.zipWithIndex.map { case (win, i) =>
            win && granted(i)
        }).asUInt.orR
        io.allow := checkedRange && (selectedGrant || (!matched.orR && checkedMachine))
    }
}
