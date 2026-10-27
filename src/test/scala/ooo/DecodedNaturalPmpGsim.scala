package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Test-only RTL mutations of the frozen typed relation implementation.
  * Mode zero is an additional peer, never the independent expected-value oracle.
  * Each nonzero mode changes exactly the named relation or permission premise.
  */
class DecodedNaturalPmpRtlMutant extends Module {
    val io = IO(new Bundle {
        val state = Input(new DecodedPmpGranuleState)
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val privilege = Input(UInt(2.W))
        val access = Input(UInt(2.W))
        val mutation = Input(UInt(4.W))
        val denied = Output(Bool())
        val summary = Output(new PmpDecisionSummary(16))
    })
    val physical = !io.address(63, 56).orR || io.mutation === 1.U
    val beat = io.address(55, 3)
    val firstGranule = io.address(2)
    val lastGranule = firstGranule || io.size === 3.U
    val overlap = Wire(Vec(16, Bool()))
    val deny = Wire(Vec(16, Bool()))
    for (i <- 0 until 16) {
        val lower = if (i == 1) Mux(io.mutation === 12.U, 0.U(54.W), io.state.lowWord(i))
            else io.state.lowWord(i)
        val upper = io.state.endWord(i)
        val lowerEqual = beat === lower(53, 1)
        val upperEqual = beat === upper(53, 1)
        val between = beat >= lower(53, 1) && beat <= upper(53, 1)
        val lastAboveLower = !lowerEqual || lastGranule || !lower(0)
        val firstBelowUpper = !upperEqual || !firstGranule || upper(0)
        val firstAboveLower = Mux(io.mutation === 10.U, lastAboveLower,
            !lowerEqual || firstGranule || !lower(0))
        val lastBelowUpper = Mux(io.mutation === 11.U, firstBelowUpper,
            !upperEqual || !lastGranule || upper(0))
        overlap(i) := (io.state.active(i) || io.mutation === 9.U) && physical && between &&
            lastAboveLower && firstBelowUpper
        val covers = (physical && between && firstAboveLower && lastBelowUpper) || io.mutation === 3.U
        val cfg = io.state.cfg(i)
        val permission = MuxLookup(io.access, false.B)(Seq(
            PmpAccess.read -> (cfg(0) || io.mutation === 6.U),
            PmpAccess.write -> (cfg(1) || io.mutation === 7.U),
            PmpAccess.execute -> (cfg(2) || io.mutation === 13.U),
            PmpAccess.readWrite -> Mux(io.mutation === 8.U, cfg(0) || cfg(1), cfg(0) && cfg(1))))
        val allowed = io.privilege === 3.U && (!cfg(7) || io.mutation === 5.U) || permission
        deny(i) := overlap(i) && (!covers || !allowed)
    }
    io.summary.hit := overlap.asUInt
    io.summary.deny := deny.asUInt
    io.summary.defaultDeny := io.privilege =/= 3.U || io.mutation === 2.U
    val lastDenied = (0 until 16).map { i =>
        val later = if (i == 15) false.B else VecInit(overlap.drop(i + 1)).asUInt.orR
        overlap(i) && !later && deny(i)
    }.reduce(_ || _)
    io.denied := Mux(io.mutation === 4.U,
        lastDenied || (!overlap.asUInt.orR && io.summary.defaultDeny),
        PmpDecisionSummary.denied(io.summary))
}

/** Raw CSR-domain fixture, preserving generic arbitrary-65-bit checker behavior.
  * contract=1/2/3 corrupts an ACTIVE bridge input; contract=4 deliberately gives
  * an inactive entry arbitrary high, reversed and non-granule bounds.
  * Raw W-only cfg is a synthetic checker input, not reachable production CSR.
  */
class DecodedNaturalPmpGsim extends Module {
    val io = IO(new Bundle {
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val privilege = Input(UInt(2.W))
        val access = Input(UInt(2.W))
        val mutation = Input(UInt(4.W))
        val contract = Input(UInt(3.W))
        val cfg0 = Input(UInt(8.W)); val addr0 = Input(UInt(54.W))
        val cfg1 = Input(UInt(8.W)); val addr1 = Input(UInt(54.W))
        val cfg2 = Input(UInt(8.W)); val addr2 = Input(UInt(54.W))
        val cfg3 = Input(UInt(8.W)); val addr3 = Input(UInt(54.W))
        val cfg4 = Input(UInt(8.W)); val addr4 = Input(UInt(54.W))
        val cfg5 = Input(UInt(8.W)); val addr5 = Input(UInt(54.W))
        val cfg6 = Input(UInt(8.W)); val addr6 = Input(UInt(54.W))
        val cfg7 = Input(UInt(8.W)); val addr7 = Input(UInt(54.W))
        val cfg8 = Input(UInt(8.W)); val addr8 = Input(UInt(54.W))
        val cfg9 = Input(UInt(8.W)); val addr9 = Input(UInt(54.W))
        val cfg10 = Input(UInt(8.W)); val addr10 = Input(UInt(54.W))
        val cfg11 = Input(UInt(8.W)); val addr11 = Input(UInt(54.W))
        val cfg12 = Input(UInt(8.W)); val addr12 = Input(UInt(54.W))
        val cfg13 = Input(UInt(8.W)); val addr13 = Input(UInt(54.W))
        val cfg14 = Input(UInt(8.W)); val addr14 = Input(UInt(54.W))
        val cfg15 = Input(UInt(8.W)); val addr15 = Input(UInt(54.W))
        val denied0 = Output(Bool())
        val hit0 = Output(UInt(1.W)); val deny0 = Output(UInt(1.W))
        val defaultDeny0 = Output(Bool())
        val denied8 = Output(Bool())
        val hit8 = Output(UInt(8.W)); val deny8 = Output(UInt(8.W))
        val defaultDeny8 = Output(Bool())
        val denied16 = Output(Bool())
        val hit16 = Output(UInt(16.W)); val deny16 = Output(UInt(16.W))
        val defaultDeny16 = Output(Bool())
        val genericDenied = Output(Bool())
        val genericHit = Output(UInt(16.W)); val genericDeny = Output(UInt(16.W))
        val genericDefaultDeny = Output(Bool())
        val mutantDenied = Output(Bool())
        val mutantHit = Output(UInt(16.W)); val mutantDeny = Output(UInt(16.W))
        val mutantDefaultDeny = Output(Bool())
    })
    val raw = Wire(new PmpState)
    raw.cfg(0) := io.cfg0; raw.addr(0) := io.addr0
    raw.cfg(1) := io.cfg1; raw.addr(1) := io.addr1
    raw.cfg(2) := io.cfg2; raw.addr(2) := io.addr2
    raw.cfg(3) := io.cfg3; raw.addr(3) := io.addr3
    raw.cfg(4) := io.cfg4; raw.addr(4) := io.addr4
    raw.cfg(5) := io.cfg5; raw.addr(5) := io.addr5
    raw.cfg(6) := io.cfg6; raw.addr(6) := io.addr6
    raw.cfg(7) := io.cfg7; raw.addr(7) := io.addr7
    raw.cfg(8) := io.cfg8; raw.addr(8) := io.addr8
    raw.cfg(9) := io.cfg9; raw.addr(9) := io.addr9
    raw.cfg(10) := io.cfg10; raw.addr(10) := io.addr10
    raw.cfg(11) := io.cfg11; raw.addr(11) := io.addr11
    raw.cfg(12) := io.cfg12; raw.addr(12) := io.addr12
    raw.cfg(13) := io.cfg13; raw.addr(13) := io.addr13
    raw.cfg(14) := io.cfg14; raw.addr(14) := io.addr14
    raw.cfg(15) := io.cfg15; raw.addr(15) := io.addr15
    PmpState.decodeRegions(raw)
    val state = WireDefault(raw)
    when(io.contract === 1.U) {
        state.regionLow(0) := raw.regionLow(0) | (BigInt(1) << 64).U(65.W)
        state.regionEnd(0) := raw.regionEnd(0) | (BigInt(1) << 64).U(65.W)
    }
    when(io.contract === 2.U) { state.regionLow(0) := raw.regionLow(0) | 1.U }
    when(io.contract === 3.U) {
        state.regionLow(0) := 8.U
        state.regionEnd(0) := 3.U
    }
    when(io.contract === 4.U) {
        state.regionActive(0) := false.B
        state.regionLow(0) := ((BigInt(1) << 65) - 1).U(65.W)
        state.regionEnd(0) := 0.U
    }
    val typed0 = Module(new DecodedNaturalPmpChecker(0, exportDecision = true))
    typed0.io.state := DecodedPmpGranuleState.fromDecoded(state, 0)
    typed0.io.address := io.address; typed0.io.size := io.size
    typed0.io.privilege := io.privilege; typed0.io.access := io.access
    io.denied0 := typed0.io.denied
    io.hit0 := typed0.decision.get.hit; io.deny0 := typed0.decision.get.deny
    io.defaultDeny0 := typed0.decision.get.defaultDeny
    val typed8 = Module(new DecodedNaturalPmpChecker(8, exportDecision = true))
    typed8.io.state := DecodedPmpGranuleState.fromDecoded(state, 8)
    typed8.io.address := io.address; typed8.io.size := io.size
    typed8.io.privilege := io.privilege; typed8.io.access := io.access
    io.denied8 := typed8.io.denied
    io.hit8 := typed8.decision.get.hit; io.deny8 := typed8.decision.get.deny
    io.defaultDeny8 := typed8.decision.get.defaultDeny
    val typed16 = Module(new DecodedNaturalPmpChecker(16, exportDecision = true))
    typed16.io.state := DecodedPmpGranuleState.fromDecoded(state, 16)
    typed16.io.address := io.address; typed16.io.size := io.size
    typed16.io.privilege := io.privilege; typed16.io.access := io.access
    io.denied16 := typed16.io.denied
    io.hit16 := typed16.decision.get.hit; io.deny16 := typed16.decision.get.deny
    io.defaultDeny16 := typed16.decision.get.defaultDeny
    val generic = Module(new PmpChecker(16, exportDecision = true))
    generic.io.state := state; generic.io.address := io.address; generic.io.size := io.size
    generic.io.privilege := io.privilege; generic.io.access := io.access
    io.genericDenied := generic.io.denied
    io.genericHit := generic.decision.get.hit; io.genericDeny := generic.decision.get.deny
    io.genericDefaultDeny := generic.decision.get.defaultDeny
    val mutant = Module(new DecodedNaturalPmpRtlMutant)
    mutant.io.state := DecodedPmpGranuleState.fromDecoded(state, 16)
    mutant.io.address := io.address; mutant.io.size := io.size
    mutant.io.privilege := io.privilege; mutant.io.access := io.access
    mutant.io.mutation := io.mutation
    io.mutantDenied := mutant.io.denied
    io.mutantHit := mutant.io.summary.hit; io.mutantDeny := mutant.io.summary.deny
    io.mutantDefaultDeny := mutant.io.summary.defaultDeny
}

object DecodedNaturalPmpGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new DecodedNaturalPmpGsim, Array("--target-dir", args.head))
}
