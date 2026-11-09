package soc.core.ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

/** Test-only RTL mutant: equality at a newly selected boundary is wrongly retained. */
class BoundaryLeQueriedRecoveryAdmission(p: OooParams) extends QueriedRecoveryAdmission(p) {
    override def desiredName: String = "BoundaryLeQueriedRecoveryAdmission"
    for (lane <- 0 until p.completionWidth) {
        queries.survives(lane) := Mux(accepted,
            Mux(externalWins, queries.age(lane) <= externalKeep, queries.age(lane) <= localKeep),
            !io.recovering || queries.age(lane) < io.keepCount)
    }
}

class RecoveryQueryFormal(p: OooParams, negative: Boolean) extends Module {
    val old = Module(new ParallelRecoveryAdmission(p))
    val candidate = Module(if (negative) new BoundaryLeQueriedRecoveryAdmission(p)
        else new QueriedRecoveryAdmission(p))
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val count = Input(UInt(p.countBits.W))
        val tags = Input(Vec(p.robEntries, UInt(p.tagBits.W)))
        val recovering = Input(Bool())
        val keepCount = Input(UInt(p.countBits.W))
        val external = Input(Valid(new RecoveryRequest(p)))
        val local = Input(Valid(new RecoveryRequest(p)))
        val queryIndex = Input(Vec(p.completionWidth, UInt(p.robBits.W)))
        val ordinaryEqual = Output(Bool())
        val queriesEqual = Output(Bool())
        val equal = Output(Bool())
        val oldQuery = Output(UInt(p.completionWidth.W))
        val newQuery = Output(UInt(p.completionWidth.W))
        val queryAge = Output(Vec(p.completionWidth, UInt(p.robBits.W)))
        val accepted = Output(Bool())
        val externalWins = Output(Bool())
        val externalKeep = Output(UInt(p.countBits.W))
        val localKeep = Output(UInt(p.countBits.W))
        val activeKeep = Output(UInt(p.countBits.W))
    })
    for (dut <- Seq(old, candidate)) {
        dut.io.head := io.head
        dut.io.count := io.count
        dut.io.tags := io.tags
        dut.io.recovering := io.recovering
        dut.io.keepCount := io.keepCount
        dut.io.external := io.external
        dut.io.local := io.local
    }
    val indexed = Wire(Vec(p.completionWidth, Bool()))
    for (lane <- 0 until p.completionWidth) {
        val age = (io.queryIndex(lane) - io.head)(p.robBits - 1, 0)
        candidate.queries.age(lane) := age
        io.queryAge(lane) := age
        indexed(lane) := old.io.survives(io.queryIndex(lane))
    }
    // Includes every ordinary output, selected.bits even when selected.valid is false.
    // Input fields are also equal by wiring; none is constrained by an assumption.
    io.ordinaryEqual := old.io.asUInt === candidate.io.asUInt
    io.oldQuery := indexed.asUInt
    io.newQuery := candidate.queries.survives.asUInt
    io.queriesEqual := io.oldQuery === io.newQuery
    io.equal := io.ordinaryEqual && io.queriesEqual
    io.accepted := candidate.io.accepted
    io.externalWins := candidate.io.externalWins
    io.externalKeep := (io.external.bits.token.index - io.head)(p.robBits - 1, 0).pad(p.countBits) + !io.external.bits.inclusive
    io.localKeep := (io.local.bits.token.index - io.head)(p.robBits - 1, 0).pad(p.countBits) + !io.local.bits.inclusive
    io.activeKeep := candidate.io.activeKeep
}
object RecoveryQueryFormalMain extends App {
    require(args.length == 3, "output-directory rows normal|negative")
    val rows = args(1).toInt
    require(Set(16, 32).contains(rows))
    require(Set("normal", "negative").contains(args(2)))
    val p = OooParams(robEntries = rows, physicalRegs = if (rows == 16) 48 else 64)
    ChiselStage.emitSystemVerilogFile(new RecoveryQueryFormal(p, args(2) == "negative"),
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}
