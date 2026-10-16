package soc.core.ooo
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.ip.bus.TwoEntryRegisterQueue
import _root_.circt.stage.ChiselStage

/** The exact native checked-record shape, same two-entry helper and fault factoring. */
class ClassifiedNextLineQueue(classified: Boolean) extends Module {
    val p = _root_.ooo.CombinedTimingR1Profile.config(true).coreParams
    val storedWidth = (new CheckedDataRequest(p, classified)).getWidth
    val io = IO(new Bundle {
        val enq = Flipped(Decoupled(new CheckedDataRequest(p)))
        val deq = Decoupled(new CheckedDataRequest(p))
        val privilege = Input(UInt(2.W)); val state = Input(new PmpState)
        val corrupt = Input(Bool())
        val count = Output(UInt(2.W))
        val headStored = Output(UInt(storedWidth.W)); val tailStored = Output(UInt(storedWidth.W))
    })
    val authorize = Module(new NextLineAuthorization(p, alignedLinePmp = true, exportDecision = classified))
    CpuReturnTransport.requestPayload(authorize.io.request, io.enq.bits.request)
    authorize.io.privilege := io.privilege; authorize.io.pmpState := io.state
    authorize.io.fault := (if (p.factorCheckedNextAllowed) false.B else io.enq.bits.fault)
    val queue = Module(new TwoEntryRegisterQueue(new CheckedDataRequest(p, classified)))
    queue.io.enq.valid := io.enq.valid; io.enq.ready := queue.io.enq.ready
    queue.io.enq.bits.request := io.enq.bits.request
    queue.io.enq.bits.fault := io.enq.bits.fault; queue.io.enq.bits.pageFault := io.enq.bits.pageFault
    queue.io.enq.bits.postedProof.foreach(_ := io.enq.bits.postedProof.get)
    if (classified) {
        queue.io.enq.bits.request.prefetchNextAllowed := authorize.eligible.get
        queue.io.enq.bits.nextLineDecision.get := authorize.decision.get
        queue.io.enq.bits.nextLineDecision.get.deny := authorize.decision.get.deny ^ io.corrupt.asUInt
    } else queue.io.enq.bits.request.prefetchNextAllowed := authorize.io.allowed
    io.deq.valid := queue.io.deq.valid; queue.io.deq.ready := io.deq.ready; io.count := queue.io.count
    io.deq.bits.request := queue.io.deq.bits.request
    io.deq.bits.fault := queue.io.deq.bits.fault; io.deq.bits.pageFault := queue.io.deq.bits.pageFault
    io.deq.bits.postedProof.foreach(_ := queue.io.deq.bits.postedProof.get)
    val base = queue.io.deq.bits.request.prefetchNextAllowed
    val grant = if (classified) base && !PmpDecisionSummary.denied(queue.io.deq.bits.nextLineDecision.get) else base
    io.deq.bits.request.prefetchNextAllowed := (if (p.factorCheckedNextAllowed) grant && !queue.io.deq.bits.fault else grant)
    io.headStored := BoringUtils.bore(queue.head).asUInt
    io.tailStored := BoringUtils.bore(queue.tail).asUInt
}
class ClassifiedNextLineQueueGsim extends Module {
    val p = _root_.ooo.CombinedTimingR1Profile.config(true).coreParams
    val io = IO(new Bundle {
        val push = Input(Bool()); val pop = Input(Bool()); val seed = Input(UInt(64.W))
        val address = Input(UInt(64.W)); val boundary = Input(UInt(64.W))
        val privilege = Input(UInt(2.W)); val mode = Input(UInt(3.W))
        val fault = Input(Bool()); val corrupt = Input(Bool())
        val ready = Output(Bool()); val valid = Output(Bool()); val count = Output(UInt(2.W))
        val owner = Output(UInt(64.W)); val hint = Output(Bool())
    })
    val state = WireDefault(0.U.asTypeOf(new PmpState))
    val all = ((BigInt(1) << 54) - 1).U(54.W)
    state.cfg(0) := MuxLookup(io.mode, 0.U)(Seq(1.U -> 0x1f.U, 2.U -> 0x18.U,
        3.U -> 0x98.U, 4.U -> 0x11.U, 5.U -> 0x09.U, 6.U -> 0.U))
    state.addr(0) := Mux(io.mode <= 3.U, all, io.boundary(55,2))
    state.cfg(1) := Mux(io.mode === 4.U, 0x1f.U, Mux(io.mode === 6.U, 0x09.U, 0.U))
    state.addr(1) := Mux(io.mode === 6.U, 0.U, all)
    PmpState.decodeRegions(state)
    val a = Module(new ClassifiedNextLineQueue(true)); val b = Module(new ClassifiedNextLineQueue(false))
    val width = (new CheckedDataRequest(p)).getWidth
    val payload = Cat((0 until ((width+63)/64)).reverse.map(i => io.seed ^ (BigInt(i)<<32).U(64.W)))(width-1,0)
    for (m <- Seq(a,b)) {
        m.io.enq.valid := io.push; m.io.deq.ready := io.pop
        m.io.enq.bits := payload.asTypeOf(new CheckedDataRequest(p))
        m.io.enq.bits.request.address := io.address; m.io.enq.bits.request.data := io.seed
        m.io.enq.bits.request.write := false.B; m.io.enq.bits.request.atomic := false.B
        m.io.enq.bits.request.virtualized := false.B; m.io.enq.bits.request.uncached := false.B
        m.io.enq.bits.request.size := 3.U; m.io.enq.bits.request.mask := 255.U
        m.io.enq.bits.fault := io.fault
        m.io.privilege := io.privilege; m.io.state := state; m.io.corrupt := io.corrupt
    }
    assert(a.io.enq.ready === b.io.enq.ready && a.io.deq.valid === b.io.deq.valid && a.io.count === b.io.count,
        "classified queue cycle/credit parity")
    when(a.io.deq.valid) { assert(a.io.deq.bits.asUInt === b.io.deq.bits.asUInt, "classified queue complete authority parity") }
    io.ready := a.io.enq.ready; io.valid := a.io.deq.valid; io.count := a.io.count
    io.owner := a.io.deq.bits.request.data; io.hint := a.io.deq.bits.request.prefetchNextAllowed
    println(s"CLASSIFIED_NATIVE_RECORD=${width} CLASSIFIED=${a.storedWidth} BASE=${p.speculativeRamBase} BYTES=${p.speculativeRamBytes}")
}
class ClassifiedNextLineMiter extends Module {
    val p = _root_.ooo.CombinedTimingR1Profile.config(true).coreParams
    val io = IO(new Bundle {
        val request = Input(new DataRequest); val privilege = Input(UInt(2.W)); val state = Input(new PmpState)
        val fault = Input(Bool()); val equal = Output(Bool())
    })
    val a = Module(new NextLineAuthorization(p, alignedLinePmp = true, exportDecision = true))
    val b = Module(new NextLineAuthorization(p, alignedLinePmp = true))
    for (m <- Seq(a,b)) { m.io.request := io.request; m.io.privilege := io.privilege
        m.io.pmpState := io.state; m.io.fault := io.fault }
    io.equal := (a.eligible.get && !PmpDecisionSummary.denied(a.decision.get)) === b.io.allowed
}
object ClassifiedNextLineQueueGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ClassifiedNextLineQueueGsim, Array("--target-dir", args.head))
}
object ClassifiedNextLineQueueMapMain extends App {
    ChiselStage.emitCHIRRTLFile(new ClassifiedNextLineQueue(args(1)=="1"), Array("--target-dir", args.head))
}
object ClassifiedNextLineMiterMain extends App {
    ChiselStage.emitCHIRRTLFile(new ClassifiedNextLineMiter, Array("--target-dir", args.head))
}
