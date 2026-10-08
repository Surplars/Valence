package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** GSIM's public Vec ABI is not supported: scalarize only the test boundary. */
class ScalarFloatingPointCommand(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val instruction = UInt(32.W)
    val sources_0 = UInt(5.W)
    val sources_1 = UInt(5.W)
    val sources_2 = UInt(5.W)
    val checkSingleBox_0 = Bool()
    val checkSingleBox_1 = Bool()
    val checkSingleBox_2 = Bool()
    val integerSource = UInt(64.W)
    val destination = UInt(5.W)
    val singleResult = Bool()
    val writesFp = Bool()
    val writesFlags = Bool()
    val usesRounding = Bool()
    val rounding = UInt(3.W)
    def sourcePorts: Seq[UInt] = Seq(sources_0, sources_1, sources_2)
    def boxPorts: Seq[Bool] = Seq(checkSingleBox_0, checkSingleBox_1, checkSingleBox_2)
}

class FloatingPointStateGsim(withArithmetic: Boolean = false,
    resources: FloatingPointResourceConfig = FloatingPointResourceConfig.baseline) extends Module {
    private val p = OooParams(robEntries = 16, tagBits = 64, machineSystem = true,
        floatingPoint = FloatingPointConfig.fullFD.copy(resources = resources))
    val io = IO(new Bundle {
        val headAuthorized = Input(Bool())
        val flush = Input(Bool())
        val issue = Flipped(Decoupled(new ScalarFloatingPointCommand(p)))
        val execute = Decoupled(new Bundle {
            val command = new ScalarFloatingPointCommand(p)
            val operands_0 = UInt(64.W)
            val operands_1 = UInt(64.W)
            val operands_2 = UInt(64.W)
            val rounding = UInt(3.W)
        })
        val result = Flipped(Decoupled(new FloatingPointResult(p)))
        val complete = Output(Valid(new FloatingPointResult(p)))
        val retire = Input(Valid(new RobToken(p)))
        val retireAccepted = Output(Bool())
        val csr = Flipped(Decoupled(new FloatingPointCsr))
        val csrRead = Output(UInt(64.W))
        val csrIllegal = Output(Bool())
        val setFs = Flipped(Decoupled(UInt(2.W)))
        val fs = Output(UInt(2.W))
        val sd = Output(Bool())
        val fcsr = Output(UInt(8.W))
        val busy = Output(Bool())
    })
    val state = Module(new FloatingPointState(p))
    state.io.headAuthorized := io.headAuthorized
    state.io.flush := io.flush
    state.io.issue.valid := io.issue.valid
    io.issue.ready := state.io.issue.ready
    io.execute.valid := state.io.execute.valid
    if (!withArithmetic) { state.io.execute.ready := io.execute.ready }
    private val issue = state.io.issue.bits
    private val in = io.issue.bits
    issue.token := in.token
    issue.instruction := in.instruction
    issue.sources := VecInit(in.sourcePorts)
    issue.checkSingleBox := VecInit(in.boxPorts)
    issue.integerSource := in.integerSource
    issue.destination := in.destination
    issue.singleResult := in.singleResult
    issue.writesFp := in.writesFp
    issue.writesFlags := in.writesFlags
    issue.usesRounding := in.usesRounding
    issue.rounding := in.rounding
    private val command = state.io.execute.bits.command
    private val out = io.execute.bits.command
    out.token := command.token
    out.instruction := command.instruction
    out.sourcePorts.zipWithIndex.foreach { case (port, i) => port := command.sources(i) }
    out.boxPorts.zipWithIndex.foreach { case (port, i) => port := command.checkSingleBox(i) }
    out.integerSource := command.integerSource
    out.destination := command.destination
    out.singleResult := command.singleResult
    out.writesFp := command.writesFp
    out.writesFlags := command.writesFlags
    out.usesRounding := command.usesRounding
    out.rounding := command.rounding
    io.execute.bits.operands_0 := state.io.execute.bits.operands(0)
    io.execute.bits.operands_1 := state.io.execute.bits.operands(1)
    io.execute.bits.operands_2 := state.io.execute.bits.operands(2)
    io.execute.bits.rounding := state.io.execute.bits.rounding
    if (withArithmetic) {
        // Test-only raw register setup uses opcode 0x7b and the external result.
        // All real arithmetic flows through the production HardFloat producer.
        val add = Module(new FloatingPointAdd(p))
        val setup = state.io.execute.bits.command.instruction(6, 0) === "h7b".U
        add.io.flush := io.flush
        add.io.request.bits := state.io.execute.bits
        add.io.request.valid := state.io.execute.valid && !setup && io.execute.ready
        state.io.execute.ready := io.execute.ready && (setup || add.io.request.ready)
        state.io.result.valid := add.io.result.valid || io.result.valid
        state.io.result.bits := Mux(add.io.result.valid, add.io.result.bits, io.result.bits)
        add.io.result.ready := state.io.result.ready
        io.result.ready := state.io.result.ready && !add.io.result.valid
    } else {
        state.io.result <> io.result
    }
    io.complete := state.io.complete
    state.io.retire := io.retire
    io.retireAccepted := state.io.retireAccepted
    state.io.csr <> io.csr
    io.csrRead := state.io.csrRead
    io.csrIllegal := state.io.csrIllegal
    state.io.setFs <> io.setFs
    io.fs := state.io.fs
    io.sd := state.io.sd
    io.fcsr := state.io.fcsr
    io.busy := state.io.busy
}

class FloatingPointAddStateGsim extends FloatingPointStateGsim(withArithmetic = true)

object FloatingPointStateGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointStateGsim(resources =
        FloatingPointResourceConfig.named(args.lift(1).getOrElse("baseline"))), Array("--target-dir", args.head))
}
