package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class PmpCsrObservedEntry extends Bundle {
    val cfg = UInt(8.W)
    val addr = UInt(54.W)
    val low = UInt(64.W)
    val lowHigh = Bool()
    val end = UInt(64.W)
    val endHigh = Bool()
    val active = Bool()
}
class PmpCsrObservedState extends Bundle {
    val entry0 = new PmpCsrObservedEntry
    val entry1 = new PmpCsrObservedEntry
    val entry2 = new PmpCsrObservedEntry
    val entry3 = new PmpCsrObservedEntry
    val entry4 = new PmpCsrObservedEntry
    val entry5 = new PmpCsrObservedEntry
    val entry6 = new PmpCsrObservedEntry
    val entry7 = new PmpCsrObservedEntry
    val entry8 = new PmpCsrObservedEntry
    val entry9 = new PmpCsrObservedEntry
    val entry10 = new PmpCsrObservedEntry
    val entry11 = new PmpCsrObservedEntry
    val entry12 = new PmpCsrObservedEntry
    val entry13 = new PmpCsrObservedEntry
    val entry14 = new PmpCsrObservedEntry
    val entry15 = new PmpCsrObservedEntry
    def entries: Seq[PmpCsrObservedEntry] = Seq(entry0, entry1, entry2, entry3, entry4, entry5, entry6, entry7, entry8, entry9, entry10, entry11, entry12, entry13, entry14, entry15)
}

/** The production CSR unit, driven through its irrevocable SystemRequest port.
  * No replacement CSR decoding, state injection, or system-state peeking.
  */
class PmpCsrPublicationGsim(entries: Int = 16, registered: Boolean = false) extends Module {
    private val p = OooParams(machineSystem = true, pmpEntries = entries,
        registeredPmpRegions = registered, virtualMemoryLevels = if (entries > 0) 3 else 0)
    val io = IO(new Bundle {
        val start = Input(Bool())
        val instruction = Input(UInt(32.W))
        val operand = Input(UInt(64.W))
        val pc = Input(UInt(64.W))
        val token = Input(UInt(64.W))
        val ready = Output(Bool())
        val completeReady = Input(Bool())
        val complete = Output(Bool())
        val result = Output(new SystemResult(p))
        val trap = Input(Bool())
        val trapPc = Input(UInt(64.W))
        val trapCause = Input(UInt(64.W))
        val trapReady = Output(Bool())
        val vmFlushReady = Input(Bool())
        val vmFlush = Output(Bool())
        val fenceIReady = Input(Bool())
        val fenceI = Output(Bool())
        val fetchPrivilege = Output(UInt(2.W))
        val dataPrivilege = Output(UInt(2.W))
        val satp = Output(UInt(64.W))
        val snapshot = Output(new PmpCsrObservedState)
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val access = Input(UInt(2.W))
        val denied = Output(Bool())
        val fetchDenied = Output(Bool())
    })
    val system = Module(new MachineSystemUnit(p))
    system.io.start.valid := io.start
    system.io.start.bits.token.index := 0.U
    system.io.start.bits.token.tag := io.token
    system.io.start.bits.pc := io.pc
    system.io.start.bits.instruction := io.instruction
    system.io.start.bits.operand := io.operand
    io.ready := system.io.start.ready
    system.io.complete.ready := io.completeReady
    io.complete := system.io.complete.valid
    io.result := system.io.complete.bits
    system.io.imsic.request.ready := true.B
    system.io.imsic.response.valid := false.B
    system.io.imsic.response.bits := 0.U.asTypeOf(system.io.imsic.response.bits)
    system.io.trap.valid := io.trap
    system.io.trap.bits := 0.U.asTypeOf(system.io.trap.bits)
    system.io.trap.bits.pc := io.trapPc
    system.io.trap.bits.cause := io.trapCause
    io.trapReady := system.io.trapReady
    system.io.externalInterrupt := false.B
    system.io.supervisorExternalInterrupt := false.B
    system.io.timerInterrupt := false.B
    system.io.timeValue := 0.U
    system.io.vmFlushReady.foreach(_ := io.vmFlushReady)
    io.vmFlush := system.io.vmFlush.getOrElse(false.B)
    io.satp := system.io.vmState.map(_.satp).getOrElse(0.U)
    system.io.fenceIFlushReady := io.fenceIReady
    io.fenceI := system.io.fenceIFlush
    io.fetchPrivilege := system.io.fetchPrivilege
    io.dataPrivilege := system.io.dataPrivilege
    for ((observed, i) <- io.snapshot.entries.zipWithIndex) {
        observed.cfg := system.io.pmpState.cfg(i)
        observed.addr := system.io.pmpState.addr(i)
        observed.low := system.io.pmpState.regionLow(i)(63, 0)
        observed.lowHigh := system.io.pmpState.regionLow(i)(64)
        observed.end := system.io.pmpState.regionEnd(i)(63, 0)
        observed.endHigh := system.io.pmpState.regionEnd(i)(64)
        observed.active := system.io.pmpState.regionActive(i)
    }
    val dataCheck = Module(new PmpChecker(entries))
    dataCheck.io.state := system.io.pmpState
    dataCheck.io.address := io.address
    dataCheck.io.size := io.size
    dataCheck.io.access := io.access
    dataCheck.io.privilege := system.io.dataPrivilege
    io.denied := dataCheck.io.denied
    val fetchCheck = Module(new PmpChecker(entries))
    fetchCheck.io.state := system.io.pmpState
    fetchCheck.io.address := io.address
    fetchCheck.io.size := io.size
    fetchCheck.io.access := PmpAccess.execute
    fetchCheck.io.privilege := system.io.fetchPrivilege
    io.fetchDenied := fetchCheck.io.denied
}

object PmpCsrPublicationGsimMain extends App {
    require(args.nonEmpty)
    val entries = args.find(_.startsWith("entries=")).map(_.stripPrefix("entries=").toInt).getOrElse(16)
    require(args.drop(1).forall(a => a == "registered" || a == s"entries=$entries"))
    ChiselStage.emitCHIRRTLFile(new PmpCsrPublicationGsim(entries, args.contains("registered")),
        Array("--target-dir", args.head))
}
