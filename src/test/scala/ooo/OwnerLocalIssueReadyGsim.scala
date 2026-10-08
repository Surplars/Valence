package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Standalone unclocked cone used for a production-logic structural ablation. */
class IssueReadyCone(local: Boolean) extends Module {
    val io = IO(new Bundle {
        val physical = Input(UInt(48.W))
        val active = Input(UInt(16.W))
        val source1 = Input(Vec(16, UInt(6.W)))
        val source2 = Input(Vec(16, UInt(6.W)))
        val saved1 = Input(UInt(16.W))
        val saved2 = Input(UInt(16.W))
        val load = Input(Valid(UInt(6.W)))
        val alu = Input(Vec(2, Valid(UInt(6.W))))
        val ready1 = Output(UInt(16.W))
        val ready2 = Output(UInt(16.W))
    })
    def read(source: Vec[UInt], saved: UInt): UInt = VecInit((0 until 16).map { slot =>
        val index = Mux(io.active(slot), source(slot), 0.U)
        val registered = if (local) saved(slot) else io.physical(index)
        io.active(slot) && IssueOperandReadiness(index, registered, io.load, io.alu.toSeq)
    }).asUInt
    io.ready1 := read(io.source1, io.saved1)
    io.ready2 := read(io.source2, io.saved2)
}

/** The independent host owns the physical scoreboard and accepted update events. */
class OwnerLocalIssueReadyGsim extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48)
    val io = IO(new Bundle {
        val physical = Input(UInt(64.W))
        val active = Input(UInt(16.W))
        val source1 = Input(new OperandScalarPorts(8, 16))
        val source2 = Input(new OperandScalarPorts(8, 16))
        val allocate0 = Input(Valid(new OwnerOperandAllocation(p)))
        val allocate1 = Input(Valid(new OwnerOperandAllocation(p)))
        val wake0 = Input(Valid(UInt(6.W)))
        val wake1 = Input(Valid(UInt(6.W)))
        val wake2 = Input(Valid(UInt(6.W)))
        val reserve0 = Input(Valid(UInt(6.W)))
        val reserve1 = Input(Valid(UInt(6.W)))
        val loadPromise = Input(Valid(UInt(6.W)))
        val aluPromise0 = Input(Valid(UInt(6.W)))
        val aluPromise1 = Input(Valid(UInt(6.W)))
        val global1 = Output(UInt(16.W))
        val global2 = Output(UInt(16.W))
        val local1 = Output(UInt(16.W))
        val local2 = Output(UInt(16.W))
    })
    val mirror = Module(new OwnerOperandReady(p))
    mirror.io.physical := io.physical(47, 0)
    mirror.io.active := io.active
    mirror.io.source1 := VecInit((0 until 16).map(i => io.source1.at(i)(5, 0)))
    mirror.io.source2 := VecInit((0 until 16).map(i => io.source2.at(i)(5, 0)))
    mirror.io.allocate := VecInit(Seq(io.allocate0, io.allocate1))
    mirror.io.wake := VecInit(Seq(io.wake0, io.wake1, io.wake2))
    mirror.io.reserve := VecInit(Seq(io.reserve0, io.reserve1))
    val cones = Seq(false, true).map { local =>
        val cone = Module(new IssueReadyCone(local))
        cone.io.physical := io.physical(47, 0)
        cone.io.active := io.active
        cone.io.source1 := mirror.io.source1
        cone.io.source2 := mirror.io.source2
        cone.io.saved1 := mirror.io.ready1.asUInt
        cone.io.saved2 := mirror.io.ready2.asUInt
        cone.io.load := io.loadPromise
        cone.io.alu := VecInit(Seq(io.aluPromise0, io.aluPromise1))
        cone
    }
    io.global1 := cones(0).io.ready1; io.global2 := cones(0).io.ready2
    io.local1 := cones(1).io.ready1; io.local2 := cones(1).io.ready2
}
object OwnerLocalIssueReadyGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new OwnerLocalIssueReadyGsim, Array("--target-dir", args.head))
}
object IssueReadyConeMain extends App {
    ChiselStage.emitCHIRRTLFile(new IssueReadyCone(args.contains("local")), Array("--target-dir", args.head))
}
