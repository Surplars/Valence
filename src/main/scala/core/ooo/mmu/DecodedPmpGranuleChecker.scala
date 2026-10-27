package soc.core.ooo

import chisel3._
import chisel3.util._

/** A view of decoded PMP, not a second decoder or a permission certificate.
  * Active bounds are inclusive, ordered 4-byte granules below 2^56. Inactive
  * bounds carry no meaning (notably TOR top-zero's original 65-bit underflow).
  */
class DecodedPmpGranuleState extends Bundle {
    val cfg = Vec(16, UInt(8.W))
    val lowWord = Vec(16, UInt(54.W))
    val endWord = Vec(16, UInt(54.W))
    val active = Vec(16, Bool())
}

object DecodedPmpGranuleState {
    def fromDecoded(state: PmpState, entries: Int): DecodedPmpGranuleState = {
        require(Set(0, 8, 16).contains(entries))
        val result = Wire(new DecodedPmpGranuleState)
        for (i <- 0 until 16) {
            result.cfg(i) := state.cfg(i)
            result.lowWord(i) := state.regionLow(i)(55, 2)
            result.endWord(i) := state.regionEnd(i)(55, 2)
            result.active(i) := state.regionActive(i)
            if (i < entries) {
                when(state.regionActive(i)) {
                    assert(!state.regionLow(i)(64, 56).orR && !state.regionEnd(i)(64, 56).orR,
                        "decoded PMP active bounds must remain in the 56-bit physical domain")
                    assert(state.regionLow(i)(1, 0) === 0.U && state.regionEnd(i)(1, 0) === 3.U,
                        "decoded PMP active bounds must contain complete four-byte granules")
                    assert(state.regionLow(i) <= state.regionEnd(i),
                        "decoded PMP active bounds must be ordered")
                }
            }
        }
        result
    }
}

/** Exact natural 1/2/4/8-byte PMP against a typed decoded state.
  * Combinational latency, II=1; no storage, credits or backpressure. Every caller
  * retains its own permission boundary, original address and misalignment fault.
  * Full address high bits cause no hit, NOT unconditional denial: M-mode's
  * original no-hit policy remains authoritative. An eight-byte access can
  * partially overlap a four-byte region and must still fail whole-byte coverage.
  */
class DecodedNaturalPmpChecker(val entries: Int = 16, val exportDecision: Boolean = false) extends Module {
    require(Set(0, 8, 16).contains(entries))
    val io = IO(new Bundle {
        val state = Input(new DecodedPmpGranuleState)
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val privilege = Input(UInt(2.W))
        val access = Input(UInt(2.W))
        val denied = Output(Bool())
    })
    val decision = if (exportDecision) Some(IO(Output(new PmpDecisionSummary(entries)))) else None
    val alignmentMask = MuxLookup(io.size, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    assert(io.size <= 3.U && (io.address(2, 0) & alignmentMask) === 0.U,
        "decoded natural PMP requires an aligned access of at most eight bytes")

    if (entries == 0) {
        io.denied := false.B
        decision.foreach { d => d.hit := 0.U; d.deny := 0.U; d.defaultDeny := false.B }
    } else {
        val physical = !io.address(63, 56).orR
        val beat = io.address(55, 3)
        val firstGranule = io.address(2)
        val lastGranule = firstGranule || io.size === 3.U
        val overlap = Wire(Vec(entries, Bool()))
        val deny = Wire(Vec(entries, Bool()))
        for (i <- 0 until entries) {
            val lower = io.state.lowWord(i)
            val upper = io.state.endWord(i)
            val lowerEqual = beat === lower(53, 1)
            val upperEqual = beat === upper(53, 1)
            val between = beat >= lower(53, 1) && beat <= upper(53, 1)
            val lastAboveLower = !lowerEqual || lastGranule || !lower(0)
            val firstBelowUpper = !upperEqual || !firstGranule || upper(0)
            val firstAboveLower = !lowerEqual || firstGranule || !lower(0)
            val lastBelowUpper = !upperEqual || !lastGranule || upper(0)
            overlap(i) := io.state.active(i) && physical && between && lastAboveLower && firstBelowUpper
            val covers = physical && between && firstAboveLower && lastBelowUpper
            val cfg = io.state.cfg(i)
            val permission = MuxLookup(io.access, false.B)(Seq(
                PmpAccess.read -> cfg(0),
                PmpAccess.write -> cfg(1),
                PmpAccess.execute -> cfg(2),
                PmpAccess.readWrite -> (cfg(0) && cfg(1))))
            val allowed = io.privilege === 3.U && !cfg(7) || permission
            deny(i) := overlap(i) && (!covers || !allowed)
        }
        val summary = Wire(new PmpDecisionSummary(entries))
        summary.hit := overlap.asUInt
        summary.deny := deny.asUInt
        summary.defaultDeny := io.privilege =/= 3.U
        io.denied := PmpDecisionSummary.denied(summary)
        decision.foreach(_ := summary)
    }
}

/** Caller-local selection: disabled callers still instantiate the old checker.
  * The bridge only projects already-decoded fields; it adds no PMP state.
  */
object NaturalPmpEvaluation {
    def denied(entries: Int, decoded: Boolean, sharedBounds: Boolean, state: PmpState,
        address: UInt, size: UInt, privilege: UInt, access: UInt): Bool = {
        if (decoded) {
            val pmp = Module(new DecodedNaturalPmpChecker(entries))
            pmp.io.state := DecodedPmpGranuleState.fromDecoded(state, entries)
            pmp.io.address := address
            pmp.io.size := size
            pmp.io.privilege := privilege
            pmp.io.access := access
            pmp.io.denied
        } else {
            val pmp = Module(new PmpChecker(entries, naturalAlignedAccess = true, sharedAlignedBounds = sharedBounds))
            pmp.io.state := state
            pmp.io.address := address
            pmp.io.size := size
            pmp.io.privilege := privilege
            pmp.io.access := access
            pmp.io.denied
        }
    }
}
