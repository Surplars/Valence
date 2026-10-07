package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Combinational three-helper boundary. Software expectations are literal64
  * target arithmetic, architectural encodings, and direct selected-set scans.
  */
class FrontendSelectGsim extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val control = Output(UInt(4.W))
        val baselineControl = Output(UInt(4.W))
        val rd = Output(UInt(5.W))
        val rs1 = Output(UInt(5.W))
        val immediate = Output(UInt(64.W))
        val baselineImmediate = Output(UInt(64.W))
        val pc = Input(UInt(64.W))
        val upperImmediate = Input(UInt(32.W))
        val indirectImmediate = Input(UInt(12.W))
        val priorShort = Input(Bool())
        val shortInstruction = Input(Bool())
        val aligned16 = Output(Bool())
        val aligned32 = Output(Bool())
        val differentSuccessor = Output(Bool())
        val address = Input(UInt(64.W))
        val context = Input(UInt(3.W))
        val base0 = Input(UInt(64.W))
        val base1 = Input(UInt(64.W))
        val base2 = Input(UInt(64.W))
        val base3 = Input(UInt(64.W))
        val base4 = Input(UInt(64.W))
        val base5 = Input(UInt(64.W))
        val base6 = Input(UInt(64.W))
        val base7 = Input(UInt(64.W))
        val base8 = Input(UInt(64.W))
        val base9 = Input(UInt(64.W))
        val base10 = Input(UInt(64.W))
        val base11 = Input(UInt(64.W))
        val base12 = Input(UInt(64.W))
        val base13 = Input(UInt(64.W))
        val base14 = Input(UInt(64.W))
        val base15 = Input(UInt(64.W))
        val base16 = Input(UInt(64.W))
        val base17 = Input(UInt(64.W))
        val base18 = Input(UInt(64.W))
        val base19 = Input(UInt(64.W))
        val base20 = Input(UInt(64.W))
        val base21 = Input(UInt(64.W))
        val base22 = Input(UInt(64.W))
        val base23 = Input(UInt(64.W))
        val base24 = Input(UInt(64.W))
        val base25 = Input(UInt(64.W))
        val base26 = Input(UInt(64.W))
        val base27 = Input(UInt(64.W))
        val base28 = Input(UInt(64.W))
        val base29 = Input(UInt(64.W))
        val base30 = Input(UInt(64.W))
        val base31 = Input(UInt(64.W))
        val context0 = Input(UInt(3.W))
        val context1 = Input(UInt(3.W))
        val context2 = Input(UInt(3.W))
        val context3 = Input(UInt(3.W))
        val context4 = Input(UInt(3.W))
        val context5 = Input(UInt(3.W))
        val context6 = Input(UInt(3.W))
        val context7 = Input(UInt(3.W))
        val context8 = Input(UInt(3.W))
        val context9 = Input(UInt(3.W))
        val context10 = Input(UInt(3.W))
        val context11 = Input(UInt(3.W))
        val context12 = Input(UInt(3.W))
        val context13 = Input(UInt(3.W))
        val context14 = Input(UInt(3.W))
        val context15 = Input(UInt(3.W))
        val context16 = Input(UInt(3.W))
        val context17 = Input(UInt(3.W))
        val context18 = Input(UInt(3.W))
        val context19 = Input(UInt(3.W))
        val context20 = Input(UInt(3.W))
        val context21 = Input(UInt(3.W))
        val context22 = Input(UInt(3.W))
        val context23 = Input(UInt(3.W))
        val context24 = Input(UInt(3.W))
        val context25 = Input(UInt(3.W))
        val context26 = Input(UInt(3.W))
        val context27 = Input(UInt(3.W))
        val context28 = Input(UInt(3.W))
        val context29 = Input(UInt(3.W))
        val context30 = Input(UInt(3.W))
        val context31 = Input(UInt(3.W))
        val valid = Input(UInt(32.W))
        val hits = Output(UInt(2.W))
        val hitsNext = Output(UInt(2.W))
        val hitsNextTwo = Output(UInt(2.W))
        val hitsNextThree = Output(UInt(2.W))
    })
    val control = Module(new FrontendControlDecode)
    control.io.instruction := io.instruction
    io.control := Cat(control.io.indirect, control.io.direct, control.io.conditional, control.io.auipc)
    io.rd := control.io.rd
    io.rs1 := control.io.rs1
    io.immediate := control.io.immediate
    val baseline = Module(new IntegerDecode(enableSystem = true, enableAtomic = true))
    baseline.io.instruction := io.instruction
    baseline.io.pc := io.pc
    io.baselineControl := Cat(baseline.io.decoded.controlFlow === ControlFlow.jalr,
        baseline.io.decoded.controlFlow === ControlFlow.jal,
        baseline.io.decoded.controlFlow >= ControlFlow.beq && baseline.io.decoded.controlFlow <= ControlFlow.bgeu,
        baseline.io.legal && io.instruction(6, 0) === "h17".U)
    io.baselineImmediate := baseline.io.decoded.immediate
    val guard = Module(new AuipcPredictionQualification)
    guard.io.auipcPcLow := io.pc(1, 0)
    guard.io.upperImmediate := io.upperImmediate
    guard.io.indirectImmediate := io.indirectImmediate
    guard.io.priorShort := io.priorShort
    guard.io.shortInstruction := io.shortInstruction
    io.aligned16 := guard.io.aligned16
    io.aligned32 := guard.io.aligned32
    io.differentSuccessor := guard.io.differentSuccessor
    val baseInputs = Seq(io.base0, io.base1, io.base2, io.base3, io.base4, io.base5, io.base6, io.base7,
        io.base8, io.base9, io.base10, io.base11, io.base12, io.base13, io.base14, io.base15,
        io.base16, io.base17, io.base18, io.base19, io.base20, io.base21, io.base22, io.base23,
        io.base24, io.base25, io.base26, io.base27, io.base28, io.base29, io.base30, io.base31)
    val contextInputs = Seq(io.context0, io.context1, io.context2, io.context3,
        io.context4, io.context5, io.context6, io.context7, io.context8, io.context9, io.context10, io.context11,
        io.context12, io.context13, io.context14, io.context15, io.context16, io.context17, io.context18, io.context19,
        io.context20, io.context21, io.context22, io.context23, io.context24, io.context25, io.context26, io.context27,
        io.context28, io.context29, io.context30, io.context31)
    val lookup = Module(new ParallelFetchTagLookup(16))
    lookup.io.address := io.address
    lookup.io.context := io.context
    lookup.io.bases := VecInit(baseInputs)
    lookup.io.contexts := VecInit(contextInputs)
    lookup.io.valid := io.valid
    io.hits := lookup.io.hit.asUInt
    // Production stores these keys at fill time. The software oracle instead
    // queries original full64 bases at address+8*k, without copying this transform.
    val adjacentHits = Seq(io.hitsNext, io.hitsNextTwo, io.hitsNextThree)
    for (offset <- 1 to 3) {
        val adjacent = Module(new ParallelFetchTagLookup(16, offset))
        adjacent.io.address := io.address
        adjacent.io.context := io.context
        adjacent.io.bases := VecInit(baseInputs.map(base => (base - (8 * offset).U)(63, 0)))
        adjacent.io.contexts := VecInit(contextInputs)
        adjacent.io.valid := io.valid
        adjacentHits(offset - 1) := adjacent.io.hit.asUInt
    }
}
object FrontendSelectGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FrontendSelectGsim, Array("--target-dir", args.head))
}
