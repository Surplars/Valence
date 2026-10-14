package ooo
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
class PmpSharedBoundsGsim extends Module {
 val io = IO(new Bundle {
  val address = Input(UInt(64.W)); val size = Input(UInt(3.W))
  val lineAddress = Input(UInt(64.W)); val rawAddress = Input(UInt(64.W)); val rawSize = Input(UInt(3.W))
  val privilege = Input(UInt(2.W)); val access = Input(UInt(2.W)); val mutation = Input(UInt(3.W))
  val low0 = Input(UInt(64.W)); val lowHigh0 = Input(Bool()); val end0 = Input(UInt(64.W)); val endHigh0 = Input(Bool()); val cfg0 = Input(UInt(8.W)); val active0 = Input(Bool())
  val low1 = Input(UInt(64.W)); val lowHigh1 = Input(Bool()); val end1 = Input(UInt(64.W)); val endHigh1 = Input(Bool()); val cfg1 = Input(UInt(8.W)); val active1 = Input(Bool())
  val low2 = Input(UInt(64.W)); val lowHigh2 = Input(Bool()); val end2 = Input(UInt(64.W)); val endHigh2 = Input(Bool()); val cfg2 = Input(UInt(8.W)); val active2 = Input(Bool())
  val low3 = Input(UInt(64.W)); val lowHigh3 = Input(Bool()); val end3 = Input(UInt(64.W)); val endHigh3 = Input(Bool()); val cfg3 = Input(UInt(8.W)); val active3 = Input(Bool())
  val low4 = Input(UInt(64.W)); val lowHigh4 = Input(Bool()); val end4 = Input(UInt(64.W)); val endHigh4 = Input(Bool()); val cfg4 = Input(UInt(8.W)); val active4 = Input(Bool())
  val low5 = Input(UInt(64.W)); val lowHigh5 = Input(Bool()); val end5 = Input(UInt(64.W)); val endHigh5 = Input(Bool()); val cfg5 = Input(UInt(8.W)); val active5 = Input(Bool())
  val low6 = Input(UInt(64.W)); val lowHigh6 = Input(Bool()); val end6 = Input(UInt(64.W)); val endHigh6 = Input(Bool()); val cfg6 = Input(UInt(8.W)); val active6 = Input(Bool())
  val low7 = Input(UInt(64.W)); val lowHigh7 = Input(Bool()); val end7 = Input(UInt(64.W)); val endHigh7 = Input(Bool()); val cfg7 = Input(UInt(8.W)); val active7 = Input(Bool())
  val low8 = Input(UInt(64.W)); val lowHigh8 = Input(Bool()); val end8 = Input(UInt(64.W)); val endHigh8 = Input(Bool()); val cfg8 = Input(UInt(8.W)); val active8 = Input(Bool())
  val low9 = Input(UInt(64.W)); val lowHigh9 = Input(Bool()); val end9 = Input(UInt(64.W)); val endHigh9 = Input(Bool()); val cfg9 = Input(UInt(8.W)); val active9 = Input(Bool())
  val low10 = Input(UInt(64.W)); val lowHigh10 = Input(Bool()); val end10 = Input(UInt(64.W)); val endHigh10 = Input(Bool()); val cfg10 = Input(UInt(8.W)); val active10 = Input(Bool())
  val low11 = Input(UInt(64.W)); val lowHigh11 = Input(Bool()); val end11 = Input(UInt(64.W)); val endHigh11 = Input(Bool()); val cfg11 = Input(UInt(8.W)); val active11 = Input(Bool())
  val low12 = Input(UInt(64.W)); val lowHigh12 = Input(Bool()); val end12 = Input(UInt(64.W)); val endHigh12 = Input(Bool()); val cfg12 = Input(UInt(8.W)); val active12 = Input(Bool())
  val low13 = Input(UInt(64.W)); val lowHigh13 = Input(Bool()); val end13 = Input(UInt(64.W)); val endHigh13 = Input(Bool()); val cfg13 = Input(UInt(8.W)); val active13 = Input(Bool())
  val low14 = Input(UInt(64.W)); val lowHigh14 = Input(Bool()); val end14 = Input(UInt(64.W)); val endHigh14 = Input(Bool()); val cfg14 = Input(UInt(8.W)); val active14 = Input(Bool())
  val low15 = Input(UInt(64.W)); val lowHigh15 = Input(Bool()); val end15 = Input(UInt(64.W)); val endHigh15 = Input(Bool()); val cfg15 = Input(UInt(8.W)); val active15 = Input(Bool())
  val natural0 = Output(Bool()); val line0 = Output(Bool())
  val natural8 = Output(Bool()); val line8 = Output(Bool())
  val natural16 = Output(Bool()); val line16 = Output(Bool())
  val generic = Output(Bool())
 })
 val state = Wire(new PmpState)
 state.addr := VecInit(Seq.fill(16)(0.U(54.W)))
 state.cfg(0) := io.cfg0; state.regionLow(0) := Cat(io.lowHigh0,io.low0); state.regionEnd(0) := Cat(io.endHigh0,io.end0); state.regionActive(0) := io.active0
 state.cfg(1) := io.cfg1; state.regionLow(1) := Cat(io.lowHigh1,io.low1); state.regionEnd(1) := Cat(io.endHigh1,io.end1); state.regionActive(1) := io.active1
 state.cfg(2) := io.cfg2; state.regionLow(2) := Cat(io.lowHigh2,io.low2); state.regionEnd(2) := Cat(io.endHigh2,io.end2); state.regionActive(2) := io.active2
 state.cfg(3) := io.cfg3; state.regionLow(3) := Cat(io.lowHigh3,io.low3); state.regionEnd(3) := Cat(io.endHigh3,io.end3); state.regionActive(3) := io.active3
 state.cfg(4) := io.cfg4; state.regionLow(4) := Cat(io.lowHigh4,io.low4); state.regionEnd(4) := Cat(io.endHigh4,io.end4); state.regionActive(4) := io.active4
 state.cfg(5) := io.cfg5; state.regionLow(5) := Cat(io.lowHigh5,io.low5); state.regionEnd(5) := Cat(io.endHigh5,io.end5); state.regionActive(5) := io.active5
 state.cfg(6) := io.cfg6; state.regionLow(6) := Cat(io.lowHigh6,io.low6); state.regionEnd(6) := Cat(io.endHigh6,io.end6); state.regionActive(6) := io.active6
 state.cfg(7) := io.cfg7; state.regionLow(7) := Cat(io.lowHigh7,io.low7); state.regionEnd(7) := Cat(io.endHigh7,io.end7); state.regionActive(7) := io.active7
 state.cfg(8) := io.cfg8; state.regionLow(8) := Cat(io.lowHigh8,io.low8); state.regionEnd(8) := Cat(io.endHigh8,io.end8); state.regionActive(8) := io.active8
 state.cfg(9) := io.cfg9; state.regionLow(9) := Cat(io.lowHigh9,io.low9); state.regionEnd(9) := Cat(io.endHigh9,io.end9); state.regionActive(9) := io.active9
 state.cfg(10) := io.cfg10; state.regionLow(10) := Cat(io.lowHigh10,io.low10); state.regionEnd(10) := Cat(io.endHigh10,io.end10); state.regionActive(10) := io.active10
 state.cfg(11) := io.cfg11; state.regionLow(11) := Cat(io.lowHigh11,io.low11); state.regionEnd(11) := Cat(io.endHigh11,io.end11); state.regionActive(11) := io.active11
 state.cfg(12) := io.cfg12; state.regionLow(12) := Cat(io.lowHigh12,io.low12); state.regionEnd(12) := Cat(io.endHigh12,io.end12); state.regionActive(12) := io.active12
 state.cfg(13) := io.cfg13; state.regionLow(13) := Cat(io.lowHigh13,io.low13); state.regionEnd(13) := Cat(io.endHigh13,io.end13); state.regionActive(13) := io.active13
 state.cfg(14) := io.cfg14; state.regionLow(14) := Cat(io.lowHigh14,io.low14); state.regionEnd(14) := Cat(io.endHigh14,io.end14); state.regionActive(14) := io.active14
 state.cfg(15) := io.cfg15; state.regionLow(15) := Cat(io.lowHigh15,io.low15); state.regionEnd(15) := Cat(io.endHigh15,io.end15); state.regionActive(15) := io.active15
 val natural0_candidate = Module(new PmpChecker(0,naturalAlignedAccess=true,sharedAlignedBounds=true))
 natural0_candidate.io.state := state; natural0_candidate.io.address := io.address; natural0_candidate.io.size := io.size
 natural0_candidate.io.privilege := io.privilege; natural0_candidate.io.access := io.access
 val natural0_reference = Module(new R6PmpCheckerReference(0))
 natural0_reference.io.state := state; natural0_reference.io.address := io.address; natural0_reference.io.size := io.size
 natural0_reference.io.privilege := io.privilege; natural0_reference.io.access := io.access
 val natural0_off = Module(new PmpChecker(0,naturalAlignedAccess=true))
 natural0_off.io.state := state; natural0_off.io.address := io.address; natural0_off.io.size := io.size
 natural0_off.io.privilege := io.privilege; natural0_off.io.access := io.access
 assert(natural0_candidate.io.denied === natural0_reference.io.denied,"shared bounds differs from frozen bytes")
 assert(natural0_off.io.denied === natural0_reference.io.denied,"OFF mode differs from frozen bytes")
 io.natural0 := natural0_candidate.io.denied
 val natural8_candidate = Module(new PmpChecker(8,naturalAlignedAccess=true,sharedAlignedBounds=true))
 natural8_candidate.io.state := state; natural8_candidate.io.address := io.address; natural8_candidate.io.size := io.size
 natural8_candidate.io.privilege := io.privilege; natural8_candidate.io.access := io.access
 val natural8_reference = Module(new R6PmpCheckerReference(8))
 natural8_reference.io.state := state; natural8_reference.io.address := io.address; natural8_reference.io.size := io.size
 natural8_reference.io.privilege := io.privilege; natural8_reference.io.access := io.access
 val natural8_off = Module(new PmpChecker(8,naturalAlignedAccess=true))
 natural8_off.io.state := state; natural8_off.io.address := io.address; natural8_off.io.size := io.size
 natural8_off.io.privilege := io.privilege; natural8_off.io.access := io.access
 assert(natural8_candidate.io.denied === natural8_reference.io.denied,"shared bounds differs from frozen bytes")
 assert(natural8_off.io.denied === natural8_reference.io.denied,"OFF mode differs from frozen bytes")
 io.natural8 := natural8_candidate.io.denied
 val natural16_candidate = Module(new PmpChecker(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 natural16_candidate.io.state := state; natural16_candidate.io.address := io.address; natural16_candidate.io.size := io.size
 natural16_candidate.io.privilege := io.privilege; natural16_candidate.io.access := io.access
 val natural16_reference = Module(new R6PmpCheckerReference(16))
 natural16_reference.io.state := state; natural16_reference.io.address := io.address; natural16_reference.io.size := io.size
 natural16_reference.io.privilege := io.privilege; natural16_reference.io.access := io.access
 val natural16_off = Module(new PmpChecker(16,naturalAlignedAccess=true))
 natural16_off.io.state := state; natural16_off.io.address := io.address; natural16_off.io.size := io.size
 natural16_off.io.privilege := io.privilege; natural16_off.io.access := io.access
 assert(natural16_candidate.io.denied === natural16_reference.io.denied,"shared bounds differs from frozen bytes")
 assert(natural16_off.io.denied === natural16_reference.io.denied,"OFF mode differs from frozen bytes")
 io.natural16 := natural16_candidate.io.denied
 val naturalMutant1 = Module(new PmpSharedBoundMutant1(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 naturalMutant1.io.state := state; naturalMutant1.io.address := io.address; naturalMutant1.io.size := io.size
 naturalMutant1.io.privilege := io.privilege; naturalMutant1.io.access := io.access
 when(io.mutation === 1.U) { io.natural16 := naturalMutant1.io.denied }
 val naturalMutant2 = Module(new PmpSharedBoundMutant2(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 naturalMutant2.io.state := state; naturalMutant2.io.address := io.address; naturalMutant2.io.size := io.size
 naturalMutant2.io.privilege := io.privilege; naturalMutant2.io.access := io.access
 when(io.mutation === 2.U) { io.natural16 := naturalMutant2.io.denied }
 val naturalMutant3 = Module(new PmpSharedBoundMutant3(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 naturalMutant3.io.state := state; naturalMutant3.io.address := io.address; naturalMutant3.io.size := io.size
 naturalMutant3.io.privilege := io.privilege; naturalMutant3.io.access := io.access
 when(io.mutation === 3.U) { io.natural16 := naturalMutant3.io.denied }
 val naturalMutant4 = Module(new PmpSharedBoundMutant4(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 naturalMutant4.io.state := state; naturalMutant4.io.address := io.address; naturalMutant4.io.size := io.size
 naturalMutant4.io.privilege := io.privilege; naturalMutant4.io.access := io.access
 when(io.mutation === 4.U) { io.natural16 := naturalMutant4.io.denied }
 val naturalMutant5 = Module(new PmpSharedBoundMutant5(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 naturalMutant5.io.state := state; naturalMutant5.io.address := io.address; naturalMutant5.io.size := io.size
 naturalMutant5.io.privilege := io.privilege; naturalMutant5.io.access := io.access
 when(io.mutation === 5.U) { io.natural16 := naturalMutant5.io.denied }
 val naturalMutant6 = Module(new PmpSharedBoundMutant6(16,naturalAlignedAccess=true,sharedAlignedBounds=true))
 naturalMutant6.io.state := state; naturalMutant6.io.address := io.address; naturalMutant6.io.size := io.size
 naturalMutant6.io.privilege := io.privilege; naturalMutant6.io.access := io.access
 when(io.mutation === 6.U) { io.natural16 := naturalMutant6.io.denied }
 val line0_candidate = Module(new PmpChecker(0,alignedLineAccess=true,sharedAlignedBounds=true))
 line0_candidate.io.state := state; line0_candidate.io.address := io.lineAddress; line0_candidate.io.size := 6.U
 line0_candidate.io.privilege := io.privilege; line0_candidate.io.access := io.access
 val line0_reference = Module(new R6PmpCheckerReference(0))
 line0_reference.io.state := state; line0_reference.io.address := io.lineAddress; line0_reference.io.size := 6.U
 line0_reference.io.privilege := io.privilege; line0_reference.io.access := io.access
 val line0_off = Module(new PmpChecker(0,alignedLineAccess=true))
 line0_off.io.state := state; line0_off.io.address := io.lineAddress; line0_off.io.size := 6.U
 line0_off.io.privilege := io.privilege; line0_off.io.access := io.access
 assert(line0_candidate.io.denied === line0_reference.io.denied,"shared bounds differs from frozen bytes")
 assert(line0_off.io.denied === line0_reference.io.denied,"OFF mode differs from frozen bytes")
 io.line0 := line0_candidate.io.denied
 val line8_candidate = Module(new PmpChecker(8,alignedLineAccess=true,sharedAlignedBounds=true))
 line8_candidate.io.state := state; line8_candidate.io.address := io.lineAddress; line8_candidate.io.size := 6.U
 line8_candidate.io.privilege := io.privilege; line8_candidate.io.access := io.access
 val line8_reference = Module(new R6PmpCheckerReference(8))
 line8_reference.io.state := state; line8_reference.io.address := io.lineAddress; line8_reference.io.size := 6.U
 line8_reference.io.privilege := io.privilege; line8_reference.io.access := io.access
 val line8_off = Module(new PmpChecker(8,alignedLineAccess=true))
 line8_off.io.state := state; line8_off.io.address := io.lineAddress; line8_off.io.size := 6.U
 line8_off.io.privilege := io.privilege; line8_off.io.access := io.access
 assert(line8_candidate.io.denied === line8_reference.io.denied,"shared bounds differs from frozen bytes")
 assert(line8_off.io.denied === line8_reference.io.denied,"OFF mode differs from frozen bytes")
 io.line8 := line8_candidate.io.denied
 val line16_candidate = Module(new PmpChecker(16,alignedLineAccess=true,sharedAlignedBounds=true))
 line16_candidate.io.state := state; line16_candidate.io.address := io.lineAddress; line16_candidate.io.size := 6.U
 line16_candidate.io.privilege := io.privilege; line16_candidate.io.access := io.access
 val line16_reference = Module(new R6PmpCheckerReference(16))
 line16_reference.io.state := state; line16_reference.io.address := io.lineAddress; line16_reference.io.size := 6.U
 line16_reference.io.privilege := io.privilege; line16_reference.io.access := io.access
 val line16_off = Module(new PmpChecker(16,alignedLineAccess=true))
 line16_off.io.state := state; line16_off.io.address := io.lineAddress; line16_off.io.size := 6.U
 line16_off.io.privilege := io.privilege; line16_off.io.access := io.access
 assert(line16_candidate.io.denied === line16_reference.io.denied,"shared bounds differs from frozen bytes")
 assert(line16_off.io.denied === line16_reference.io.denied,"OFF mode differs from frozen bytes")
 io.line16 := line16_candidate.io.denied
 val lineMutant1 = Module(new PmpSharedBoundMutant1(16,alignedLineAccess=true,sharedAlignedBounds=true))
 lineMutant1.io.state := state; lineMutant1.io.address := io.lineAddress; lineMutant1.io.size := 6.U
 lineMutant1.io.privilege := io.privilege; lineMutant1.io.access := io.access
 when(io.mutation === 1.U) { io.line16 := lineMutant1.io.denied }
 val lineMutant2 = Module(new PmpSharedBoundMutant2(16,alignedLineAccess=true,sharedAlignedBounds=true))
 lineMutant2.io.state := state; lineMutant2.io.address := io.lineAddress; lineMutant2.io.size := 6.U
 lineMutant2.io.privilege := io.privilege; lineMutant2.io.access := io.access
 when(io.mutation === 2.U) { io.line16 := lineMutant2.io.denied }
 val lineMutant3 = Module(new PmpSharedBoundMutant3(16,alignedLineAccess=true,sharedAlignedBounds=true))
 lineMutant3.io.state := state; lineMutant3.io.address := io.lineAddress; lineMutant3.io.size := 6.U
 lineMutant3.io.privilege := io.privilege; lineMutant3.io.access := io.access
 when(io.mutation === 3.U) { io.line16 := lineMutant3.io.denied }
 val lineMutant4 = Module(new PmpSharedBoundMutant4(16,alignedLineAccess=true,sharedAlignedBounds=true))
 lineMutant4.io.state := state; lineMutant4.io.address := io.lineAddress; lineMutant4.io.size := 6.U
 lineMutant4.io.privilege := io.privilege; lineMutant4.io.access := io.access
 when(io.mutation === 4.U) { io.line16 := lineMutant4.io.denied }
 val lineMutant5 = Module(new PmpSharedBoundMutant5(16,alignedLineAccess=true,sharedAlignedBounds=true))
 lineMutant5.io.state := state; lineMutant5.io.address := io.lineAddress; lineMutant5.io.size := 6.U
 lineMutant5.io.privilege := io.privilege; lineMutant5.io.access := io.access
 when(io.mutation === 5.U) { io.line16 := lineMutant5.io.denied }
 val lineMutant6 = Module(new PmpSharedBoundMutant6(16,alignedLineAccess=true,sharedAlignedBounds=true))
 lineMutant6.io.state := state; lineMutant6.io.address := io.lineAddress; lineMutant6.io.size := 6.U
 lineMutant6.io.privilege := io.privilege; lineMutant6.io.access := io.access
 when(io.mutation === 6.U) { io.line16 := lineMutant6.io.denied }
 val generic = Module(new PmpChecker(16))
 generic.io.state := state; generic.io.address := io.rawAddress; generic.io.size := io.rawSize
 generic.io.privilege := io.privilege; generic.io.access := io.access
 val genericReference = Module(new R6PmpCheckerReference(16))
 genericReference.io.state := state; genericReference.io.address := io.rawAddress; genericReference.io.size := io.rawSize
 genericReference.io.privilege := io.privilege; genericReference.io.access := io.access
 io.generic := generic.io.denied
 assert(generic.io.denied === genericReference.io.denied,"generic fallback differs from frozen bytes")
}
object PmpSharedBoundsGsimMain extends App {
 ChiselStage.emitCHIRRTLFile(new PmpSharedBoundsGsim,Array("--target-dir",args.head))
}
object PmpSharedBoundsNativeMain extends App {
 ChiselStage.emitCHIRRTLFile(new PmpChecker(args(3).toInt,naturalAlignedAccess=args(1)=="natural",alignedLineAccess=args(1)=="line",sharedAlignedBounds=args(2).toBoolean),Array("--target-dir",args.head))
}
object PmpSharedBoundsConfigMain extends App {
 require(args.length==1)
 ChiselStage.emitCHIRRTL(new PmpChecker(16,sharedAlignedBounds=true))
}
