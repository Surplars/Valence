package ooo
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
class PmpWordGranuleGsim extends Module {
 val io = IO(new Bundle {
  val address0 = Input(UInt(64.W)); val address1 = Input(UInt(64.W))
  val privilege = Input(UInt(2.W)); val access = Input(UInt(2.W)); val size = Input(UInt(3.W))
  val mutation = Input(UInt(3.W)); val corruptGranule = Input(Bool())
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
  val denied0_0 = Output(Bool())
  val denied0_1 = Output(Bool())
  val denied8_0 = Output(Bool())
  val denied8_1 = Output(Bool())
  val denied16_0 = Output(Bool())
  val denied16_1 = Output(Bool())
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
 when(io.corruptGranule) { state.regionLow(0) := raw.regionLow(0) | 1.U }
 val c0_0 = Module(new PmpChecker(0, alignedWordAccess=true, decodedWordGranularity=true))
 val r0_0 = Module(new R6PmpCheckerReference(0))
 val g0_0 = Module(new PmpChecker(0))
 c0_0.io.state := state; r0_0.io.state := state; g0_0.io.state := state
 c0_0.io.address := io.address0; r0_0.io.address := io.address0; g0_0.io.address := io.address0
 c0_0.io.size := io.size; r0_0.io.size := io.size; g0_0.io.size := io.size
 c0_0.io.privilege := io.privilege; r0_0.io.privilege := io.privilege; g0_0.io.privilege := io.privilege
 c0_0.io.access := io.access; r0_0.io.access := io.access; g0_0.io.access := io.access
 assert(g0_0.io.denied === r0_0.io.denied, "generic default changed")
 when(!io.corruptGranule) { assert(c0_0.io.denied === r0_0.io.denied, "word granule differs from frozen byte-range reference") }
 io.denied0_0 := c0_0.io.denied
 val c0_1 = Module(new PmpChecker(0, alignedWordAccess=true, decodedWordGranularity=true))
 val r0_1 = Module(new R6PmpCheckerReference(0))
 val g0_1 = Module(new PmpChecker(0))
 c0_1.io.state := state; r0_1.io.state := state; g0_1.io.state := state
 c0_1.io.address := io.address1; r0_1.io.address := io.address1; g0_1.io.address := io.address1
 c0_1.io.size := io.size; r0_1.io.size := io.size; g0_1.io.size := io.size
 c0_1.io.privilege := io.privilege; r0_1.io.privilege := io.privilege; g0_1.io.privilege := io.privilege
 c0_1.io.access := io.access; r0_1.io.access := io.access; g0_1.io.access := io.access
 assert(g0_1.io.denied === r0_1.io.denied, "generic default changed")
 when(!io.corruptGranule) { assert(c0_1.io.denied === r0_1.io.denied, "word granule differs from frozen byte-range reference") }
 io.denied0_1 := c0_1.io.denied
 val c8_0 = Module(new PmpChecker(8, alignedWordAccess=true, decodedWordGranularity=true))
 val r8_0 = Module(new R6PmpCheckerReference(8))
 val g8_0 = Module(new PmpChecker(8))
 c8_0.io.state := state; r8_0.io.state := state; g8_0.io.state := state
 c8_0.io.address := io.address0; r8_0.io.address := io.address0; g8_0.io.address := io.address0
 c8_0.io.size := io.size; r8_0.io.size := io.size; g8_0.io.size := io.size
 c8_0.io.privilege := io.privilege; r8_0.io.privilege := io.privilege; g8_0.io.privilege := io.privilege
 c8_0.io.access := io.access; r8_0.io.access := io.access; g8_0.io.access := io.access
 assert(g8_0.io.denied === r8_0.io.denied, "generic default changed")
 when(!io.corruptGranule) { assert(c8_0.io.denied === r8_0.io.denied, "word granule differs from frozen byte-range reference") }
 io.denied8_0 := c8_0.io.denied
 val c8_1 = Module(new PmpChecker(8, alignedWordAccess=true, decodedWordGranularity=true))
 val r8_1 = Module(new R6PmpCheckerReference(8))
 val g8_1 = Module(new PmpChecker(8))
 c8_1.io.state := state; r8_1.io.state := state; g8_1.io.state := state
 c8_1.io.address := io.address1; r8_1.io.address := io.address1; g8_1.io.address := io.address1
 c8_1.io.size := io.size; r8_1.io.size := io.size; g8_1.io.size := io.size
 c8_1.io.privilege := io.privilege; r8_1.io.privilege := io.privilege; g8_1.io.privilege := io.privilege
 c8_1.io.access := io.access; r8_1.io.access := io.access; g8_1.io.access := io.access
 assert(g8_1.io.denied === r8_1.io.denied, "generic default changed")
 when(!io.corruptGranule) { assert(c8_1.io.denied === r8_1.io.denied, "word granule differs from frozen byte-range reference") }
 io.denied8_1 := c8_1.io.denied
 val c16_0 = Module(new PmpChecker(16, alignedWordAccess=true, decodedWordGranularity=true))
 val r16_0 = Module(new R6PmpCheckerReference(16))
 val g16_0 = Module(new PmpChecker(16))
 c16_0.io.state := state; r16_0.io.state := state; g16_0.io.state := state
 c16_0.io.address := io.address0; r16_0.io.address := io.address0; g16_0.io.address := io.address0
 c16_0.io.size := io.size; r16_0.io.size := io.size; g16_0.io.size := io.size
 c16_0.io.privilege := io.privilege; r16_0.io.privilege := io.privilege; g16_0.io.privilege := io.privilege
 c16_0.io.access := io.access; r16_0.io.access := io.access; g16_0.io.access := io.access
 assert(g16_0.io.denied === r16_0.io.denied, "generic default changed")
 when(!io.corruptGranule) { assert(c16_0.io.denied === r16_0.io.denied, "word granule differs from frozen byte-range reference") }
 io.denied16_0 := c16_0.io.denied
 val c16_1 = Module(new PmpChecker(16, alignedWordAccess=true, decodedWordGranularity=true))
 val r16_1 = Module(new R6PmpCheckerReference(16))
 val g16_1 = Module(new PmpChecker(16))
 c16_1.io.state := state; r16_1.io.state := state; g16_1.io.state := state
 c16_1.io.address := io.address1; r16_1.io.address := io.address1; g16_1.io.address := io.address1
 c16_1.io.size := io.size; r16_1.io.size := io.size; g16_1.io.size := io.size
 c16_1.io.privilege := io.privilege; r16_1.io.privilege := io.privilege; g16_1.io.privilege := io.privilege
 c16_1.io.access := io.access; r16_1.io.access := io.access; g16_1.io.access := io.access
 assert(g16_1.io.denied === r16_1.io.denied, "generic default changed")
 when(!io.corruptGranule) { assert(c16_1.io.denied === r16_1.io.denied, "word granule differs from frozen byte-range reference") }
 io.denied16_1 := c16_1.io.denied
 val mutant1 = Module(new PmpWordSourceMutant1(16, alignedWordAccess=true, decodedWordGranularity=true))
 mutant1.io.state := state; mutant1.io.address := io.address0; mutant1.io.size := io.size
 mutant1.io.privilege := io.privilege; mutant1.io.access := io.access
 when(io.mutation === 1.U) { io.denied16_0 := mutant1.io.denied }
 val mutant2 = Module(new PmpWordSourceMutant2(16, alignedWordAccess=true, decodedWordGranularity=true))
 mutant2.io.state := state; mutant2.io.address := io.address0; mutant2.io.size := io.size
 mutant2.io.privilege := io.privilege; mutant2.io.access := io.access
 when(io.mutation === 2.U) { io.denied16_0 := mutant2.io.denied }
 val mutant3 = Module(new PmpWordSourceMutant3(16, alignedWordAccess=true, decodedWordGranularity=true))
 mutant3.io.state := state; mutant3.io.address := io.address0; mutant3.io.size := io.size
 mutant3.io.privilege := io.privilege; mutant3.io.access := io.access
 when(io.mutation === 3.U) { io.denied16_0 := mutant3.io.denied }
 val mutant4 = Module(new PmpWordSourceMutant4(16, alignedWordAccess=true, decodedWordGranularity=true))
 mutant4.io.state := state; mutant4.io.address := io.address0; mutant4.io.size := io.size
 mutant4.io.privilege := io.privilege; mutant4.io.access := io.access
 when(io.mutation === 4.U) { io.denied16_0 := mutant4.io.denied }
 val mutant5 = Module(new PmpWordSourceMutant5(16, alignedWordAccess=true, decodedWordGranularity=true))
 mutant5.io.state := state; mutant5.io.address := io.address0; mutant5.io.size := io.size
 mutant5.io.privilege := io.privilege; mutant5.io.access := io.access
 when(io.mutation === 5.U) { io.denied16_0 := mutant5.io.denied }
 val mutant6 = Module(new PmpWordSourceMutant6(16, alignedWordAccess=true, decodedWordGranularity=true))
 mutant6.io.state := state; mutant6.io.address := io.address0; mutant6.io.size := io.size
 mutant6.io.privilege := io.privilege; mutant6.io.access := io.access
 when(io.mutation === 6.U) { io.denied16_0 := mutant6.io.denied }
}
object PmpWordGranuleGsimMain extends App {
 ChiselStage.emitCHIRRTLFile(new PmpWordGranuleGsim, Array("--target-dir",args.head))
}
object PmpWordGranuleNativeMain extends App {
 ChiselStage.emitCHIRRTLFile(new PmpChecker(args(2).toInt, alignedWordAccess=true, decodedWordGranularity=args(1).toBoolean), Array("--target-dir",args.head))
}
object PmpWordGranuleConfigMain extends App {
 require(args.length == 1)
 ChiselStage.emitCHIRRTL(new PmpChecker(16, decodedWordGranularity = true))
}
