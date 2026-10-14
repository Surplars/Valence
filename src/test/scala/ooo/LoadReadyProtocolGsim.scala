package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** P1 protocol-level sink, deliberately not ROB completion acceptance. No forced production state. */
class LoadReadyProtocolGsim(enabled: Boolean) extends Module {
    val p = LoadReadyP1Params(enabled)
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new MemoryOperation(p)))
        val destination = Input(Valid(UInt(p.physBits.W)))
        val parallel = Input(Bool())
        val memory = new DataPort
        val sinkReady = Input(Bool())
        val cancel = Input(UInt(4.W))
        val complete = Output(Valid(new BackendCompletion(p)))
        val completedDestination = Output(Valid(UInt(p.physBits.W)))
        val active = Input(UInt(16.W))
        val execution = Input(UInt(16.W))
        val sources10 = Input(UInt(6.W))
        val sources11 = Input(UInt(6.W))
        val sources12 = Input(UInt(6.W))
        val sources13 = Input(UInt(6.W))
        val sources14 = Input(UInt(6.W))
        val sources15 = Input(UInt(6.W))
        val sources16 = Input(UInt(6.W))
        val sources17 = Input(UInt(6.W))
        val sources18 = Input(UInt(6.W))
        val sources19 = Input(UInt(6.W))
        val sources110 = Input(UInt(6.W))
        val sources111 = Input(UInt(6.W))
        val sources112 = Input(UInt(6.W))
        val sources113 = Input(UInt(6.W))
        val sources114 = Input(UInt(6.W))
        val sources115 = Input(UInt(6.W))
        val sources20 = Input(UInt(6.W))
        val sources21 = Input(UInt(6.W))
        val sources22 = Input(UInt(6.W))
        val sources23 = Input(UInt(6.W))
        val sources24 = Input(UInt(6.W))
        val sources25 = Input(UInt(6.W))
        val sources26 = Input(UInt(6.W))
        val sources27 = Input(UInt(6.W))
        val sources28 = Input(UInt(6.W))
        val sources29 = Input(UInt(6.W))
        val sources210 = Input(UInt(6.W))
        val sources211 = Input(UInt(6.W))
        val sources212 = Input(UInt(6.W))
        val sources213 = Input(UInt(6.W))
        val sources214 = Input(UInt(6.W))
        val sources215 = Input(UInt(6.W))
        val allocate0 = Input(Valid(UInt(4.W)))
        val allocate1 = Input(Valid(UInt(4.W)))
        val incomingExecution = Input(UInt(2.W))
        val candidate00 = Input(new RenameSourcePair(p))
        val candidate01 = Input(new RenameSourcePair(p))
        val candidate10 = Input(new RenameSourcePair(p))
        val candidate11 = Input(new RenameSourcePair(p))
        val faults = Input(UInt(2.W))
        val reserve0 = Input(Valid(UInt(6.W)))
        val reserve1 = Input(Valid(UInt(6.W)))
        val externalWrite = Input(Valid(new Bundle { val address = UInt(6.W); val data = UInt(64.W) }))
        val readAddress0 = Input(UInt(6.W))
        val readAddress1 = Input(UInt(6.W))
        val readAddress2 = Input(UInt(6.W))
        val readAddress3 = Input(UInt(6.W))
        val readData0 = Output(UInt(64.W))
        val readData1 = Output(UInt(64.W))
        val readData2 = Output(UInt(64.W))
        val readData3 = Output(UInt(64.W))
        val physical = Output(UInt(48.W))
        val ready1 = Output(UInt(16.W))
        val ready2 = Output(UInt(16.W))
        val directReady1 = Output(UInt(16.W))
        val directReady2 = Output(UInt(16.W))
        val allocationReady1 = Output(UInt(2.W))
        val allocationReady2 = Output(UInt(2.W))
        val publish = Output(UInt(4.W))
        val publishDestination0 = Output(UInt(6.W))
        val publishDestination1 = Output(UInt(6.W))
        val publishDestination2 = Output(UInt(6.W))
        val publishDestination3 = Output(UInt(6.W))
        val held = Output(UInt(4.W))
        val heldDestination0 = Output(UInt(6.W))
        val heldDestination1 = Output(UInt(6.W))
        val heldDestination2 = Output(UInt(6.W))
        val heldDestination3 = Output(UInt(6.W))
        val heldData0 = Output(UInt(64.W))
        val heldData1 = Output(UInt(64.W))
        val heldData2 = Output(UInt(64.W))
        val heldData3 = Output(UInt(64.W))
        val phase0 = Output(UInt(2.W))
        val phase1 = Output(UInt(2.W))
        val phase2 = Output(UInt(2.W))
        val phase3 = Output(UInt(2.W))
        val owner0 = Output(new RobToken(p))
        val owner1 = Output(new RobToken(p))
        val owner2 = Output(new RobToken(p))
        val owner3 = Output(new RobToken(p))
        val slotStart = Output(UInt(4.W))
        val slotRequest = Output(UInt(4.W))
        val slotResponse = Output(UInt(4.W))
        val slotComplete = Output(UInt(4.W))
        val slotValid = Output(UInt(4.W))
        val slotCapture = Output(UInt(4.W))
        val slotResult0 = Output(new BackendCompletion(p))
        val slotResult1 = Output(new BackendCompletion(p))
        val slotResult2 = Output(new BackendCompletion(p))
        val slotResult3 = Output(new BackendCompletion(p))
        val write = Output(Valid(new Bundle { val address = UInt(6.W); val data = UInt(64.W) }))
    })
    val sources1 = VecInit(Seq(io.sources10, io.sources11, io.sources12, io.sources13, io.sources14, io.sources15, io.sources16, io.sources17, io.sources18, io.sources19, io.sources110, io.sources111, io.sources112, io.sources113, io.sources114, io.sources115))
    val sources2 = VecInit(Seq(io.sources20, io.sources21, io.sources22, io.sources23, io.sources24, io.sources25, io.sources26, io.sources27, io.sources28, io.sources29, io.sources210, io.sources211, io.sources212, io.sources213, io.sources214, io.sources215))
    val allocate = VecInit(Seq(io.allocate0, io.allocate1))
    val reserve = VecInit(Seq(io.reserve0, io.reserve1))
    val readAddress = VecInit(Seq(io.readAddress0, io.readAddress1, io.readAddress2, io.readAddress3))
    val readData = Wire(Vec(4, UInt(64.W)))
    io.readData0 := readData(0)
    io.readData1 := readData(1)
    io.readData2 := readData(2)
    io.readData3 := readData(3)
    val publishDestination = Wire(Vec(4, UInt(6.W)))
    io.publishDestination0 := publishDestination(0)
    io.publishDestination1 := publishDestination(1)
    io.publishDestination2 := publishDestination(2)
    io.publishDestination3 := publishDestination(3)
    val heldDestination = Wire(Vec(4, UInt(6.W)))
    io.heldDestination0 := heldDestination(0)
    io.heldDestination1 := heldDestination(1)
    io.heldDestination2 := heldDestination(2)
    io.heldDestination3 := heldDestination(3)
    val heldData = Wire(Vec(4, UInt(64.W)))
    io.heldData0 := heldData(0)
    io.heldData1 := heldData(1)
    io.heldData2 := heldData(2)
    io.heldData3 := heldData(3)
    val phase = Wire(Vec(4, UInt(2.W)))
    io.phase0 := phase(0)
    io.phase1 := phase(1)
    io.phase2 := phase(2)
    io.phase3 := phase(3)
    val owner = Wire(Vec(4, new RobToken(p)))
    io.owner0 := owner(0)
    io.owner1 := owner(1)
    io.owner2 := owner(2)
    io.owner3 := owner(3)
    val slotResult = Wire(Vec(4, new BackendCompletion(p)))
    io.slotResult0 := slotResult(0)
    io.slotResult1 := slotResult(1)
    io.slotResult2 := slotResult(2)
    io.slotResult3 := slotResult(3)
    val candidates = VecInit(Seq(VecInit(Seq(io.candidate00, io.candidate01)), VecInit(Seq(io.candidate10, io.candidate11))))
    val lsu = Module(new ParallelLoadStoreUnit(p))
    lsu.io.start <> io.start
    lsu.io.issueDestination.get := io.destination
    lsu.io.parallel := io.parallel
    lsu.io.memory <> io.memory
    lsu.io.complete.ready := io.sinkReady
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    for (i <- 0 until 4) lsu.io.cancel(i) := io.cancel(i)
    io.complete.valid := lsu.io.complete.valid
    io.complete.bits := lsu.io.complete.bits
    io.completedDestination := lsu.io.completedIssueDestination.get
    phase := lsu.io.phase
    owner := lsu.io.owner
    io.slotStart := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.start.valid) && BoringUtils.bore(s.io.start.ready)))).asUInt
    io.slotRequest := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.memory.request.valid) && BoringUtils.bore(s.io.memory.request.ready)))).asUInt
    io.slotResponse := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.memory.response.valid) && BoringUtils.bore(s.io.memory.response.ready)))).asUInt
    io.slotComplete := VecInit(lsu.slots.map(s => (BoringUtils.bore(s.io.complete.valid) && BoringUtils.bore(s.io.complete.ready)))).asUInt
    io.slotValid := VecInit(lsu.slots.map(s => BoringUtils.bore(s.io.complete.valid))).asUInt
    io.slotCapture := VecInit(lsu.slots.map(s => s.io.successfulLoadResultCapture.map(BoringUtils.bore(_)).getOrElse(false.B))).asUInt
    for (i <- 0 until 4) slotResult(i) := BoringUtils.bore(lsu.slots(i).io.complete.bits)
    val held = Wire(Vec(4, Valid(UInt(6.W))))
    val publish = Wire(Vec(4, Valid(UInt(6.W))))
    for (i <- 0 until 4) {
        held(i).valid := lsu.io.heldLoadValue.map(_(i).valid).getOrElse(false.B)
        held(i).bits := lsu.io.heldLoadValue.map(_(i).bits.destination).getOrElse(0.U)
        publish(i) := lsu.io.loadResultPublish.map(_(i)).getOrElse(0.U.asTypeOf(Valid(UInt(6.W))))
        heldDestination(i) := held(i).bits
        heldData(i) := lsu.io.heldLoadValue.map(_(i).bits.data).getOrElse(0.U)
        publishDestination(i) := publish(i).bits
    }
    io.held := VecInit(held.map(_.valid)).asUInt
    io.publish := VecInit(publish.map(_.valid)).asUInt
    val physical = RegInit(1.U(48.W))
    val physicalUpdate = Module(new PhysicalReadyUpdate(48, 3, 2))
    val prf = Module(new OwnerBankedPhysicalRegisterFile(48, 4, 2))
    val wake = Wire(Vec(3, Valid(UInt(6.W))))
    io.write.valid := lsu.io.complete.fire && !lsu.io.complete.bits.exception &&
        lsu.io.completedIssueDestination.get.valid
    io.write.bits.address := lsu.io.completedIssueDestination.get.bits
    io.write.bits.data := lsu.io.complete.bits.data
    prf.io.write(0) := io.write
    prf.io.write(1) := io.externalWrite
    prf.io.address := readAddress
    readData := prf.io.data
    wake(0).valid := io.write.valid
    wake(0).bits := io.write.bits.address
    wake(1).valid := io.externalWrite.valid
    wake(1).bits := io.externalWrite.bits.address
    wake(2) := 0.U.asTypeOf(Valid(UInt(6.W)))
    physicalUpdate.io.current := physical
    physicalUpdate.io.wake := wake
    physicalUpdate.io.reserve := reserve
    physical := physicalUpdate.io.next
    io.physical := physical
    val faultReady = Module(new FaultAwareAllocationReady(p))
    faultReady.io.sources := candidates
    faultReady.io.faults := io.faults
    faultReady.io.physical := physical
    faultReady.io.wake := wake
    faultReady.io.reserve := reserve
    faultReady.io.allocationExecutionClass.foreach(_ := VecInit(io.incomingExecution.asBools))
    faultReady.io.heldLoads.foreach(_ := held)
    faultReady.io.publishedLoads.foreach(_ := publish)
    io.allocationReady1 := faultReady.io.ready1.asUInt
    io.allocationReady2 := faultReady.io.ready2.asUInt
    val ready = Module(new OwnerOperandReady(p, precomputedAllocationReady = true))
    val direct = Module(new OwnerOperandReady(p))
    for (r <- Seq(ready, direct)) {
        r.io.physical := physical
        r.io.active := io.active
        r.io.source1 := sources1
        r.io.source2 := sources2
        r.io.wake := wake
        r.io.reserve := reserve
        r.io.executionClass.foreach(_ := VecInit(io.execution.asBools))
        r.io.allocationExecutionClass.foreach(_ := VecInit(io.incomingExecution.asBools))
        r.io.heldLoads.foreach(_ := held)
        r.io.publishedLoads.foreach(_ := publish)
        for (lane <- 0 until 2) {
            val fault = io.faults(lane)
            val alternate = if (lane == 1) io.faults(0) else false.B
            r.io.allocate(lane).valid := allocate(lane).valid
            r.io.allocate(lane).bits.index := allocate(lane).bits
            r.io.allocate(lane).bits.source1 := Mux(fault, 0.U, Mux(alternate,
                candidates(lane)(1).source1, candidates(lane)(0).source1))
            r.io.allocate(lane).bits.source2 := Mux(fault, 0.U, Mux(alternate,
                candidates(lane)(1).source2, candidates(lane)(0).source2))
        }
    }
    ready.io.allocationReady1.get := faultReady.io.ready1
    ready.io.allocationReady2.get := faultReady.io.ready2
    io.ready1 := ready.io.ready1.asUInt
    io.ready2 := ready.io.ready2.asUInt
    io.directReady1 := direct.io.ready1.asUInt
    io.directReady2 := direct.io.ready2.asUInt
}
object LoadReadyProtocolGsimMain extends App {
    val target = args(0)
    val enabled = args(1) == "1"
    LoadReadyP1Params.write(target, enabled)
    ChiselStage.emitCHIRRTLFile(new LoadReadyProtocolGsim(enabled), Array("--target-dir", target))
}
