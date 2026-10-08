package ooo

import chisel3._
import chisel3.util._
import soc.core.ooo._
import _root_.circt.stage.ChiselStage

/** Real backend system/trap arbitration, without cache/fabric or a firmware boot. */
class PrefetchBarrierGsim(enabled: Boolean = true) extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48, machineSystem = true,
        pmpEntries = 8, virtualMemoryLevels = 3, dataNextLinePrefetch = enabled,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 8192)
    val io = IO(new Bundle {
        val instruction = Flipped(Valid(UInt(32.W)))
        val instruction1 = Flipped(Valid(UInt(32.W)))
        val memory = new DataPort
        val busy = Input(Bool())
        val commitEnable = Input(Bool())
        val fenceReady = Input(Bool())
        val timerInterrupt = Input(Bool())
        val bypassBusy = Input(Bool()) // independent negative-control fixture
        val accepted = Output(Bool())
        val accepted1 = Output(Bool())
        val fetchPc = Output(UInt(64.W))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Bool())
        val trapCause = Output(UInt(64.W))
        val trapPc = Output(UInt(64.W))
        val memoryBusy = Output(Bool())
        val pmpCfg0 = Output(UInt(8.W))
        val satp = Output(UInt(64.W))
        val privilege = Output(UInt(2.W))
        val dataPrivilege = Output(UInt(2.W))
        val redirect = Output(Bool())
        val vmFlush = Output(Bool())
        val fenceFlush = Output(Bool())
    })
    val core = Module(new MachineCore(p))
    core.io.instructions(0) := io.instruction
    core.io.instructions(1) := io.instruction1
    core.io.instructionFaults := VecInit(Seq.fill(2)(false.B))
    core.io.instructionPageFaults := VecInit(Seq.fill(2)(false.B))
    core.io.externalPrefetchBusy.foreach(_ := io.busy && !io.bypassBusy)
    core.io.timerInterrupt := io.timerInterrupt
    core.io.timeValue := 0.U
    core.io.fetchQuiescent.get := true.B
    core.io.vmFlushReady.get := true.B
    core.io.fenceIFlushReady := io.fenceReady
    core.io.commitEnable := io.commitEnable
    core.io.inspectRegister := 0.U
    core.io.msi.request.valid := false.B
    core.io.msi.request.bits := 0.U.asTypeOf(core.io.msi.request.bits)
    core.io.msi.response.ready := true.B
    io.memory <> core.io.memory
    io.accepted := core.io.accepted(0)
    io.accepted1 := core.io.accepted(1)
    io.fetchPc := core.io.fetchPc
    io.commit0 := core.io.commit(0)
    io.commit1 := core.io.commit(1)
    io.trap := core.io.trap.valid
    io.trapCause := core.io.trap.bits.cause
    io.trapPc := core.io.trap.bits.pc
    io.memoryBusy := core.io.memoryBusy
    io.pmpCfg0 := core.io.pmpState.get.cfg(0)
    io.satp := core.io.vmState.get.satp
    io.privilege := core.io.fetchPrivilege.get
    io.dataPrivilege := core.io.vmState.get.dataPrivilege
    io.redirect := core.io.redirect.valid
    io.vmFlush := core.io.vmFlush.get
    io.fenceFlush := core.io.fenceIFlush
}
object PrefetchBarrierGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PrefetchBarrierGsim(!args.lift(1).contains("0")), Array("--target-dir", args.head))
}
