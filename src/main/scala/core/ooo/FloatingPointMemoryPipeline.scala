package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.TwoEntryRegisterQueue

/** ROB-head FP memory pipeline; one irrevocable owner, no speculative issue credit.
  * Execute envelope -> registered AGU payload -> live PMP/LSU capture ->
  * registered request -> registered response -> registered completion.
  * The execute handshake is the LSU permission/capture handshake, not the AGU
  * preparation. Privilege/PMP/virtualization remain live until that handshake.
  * Drain all accepted accesses and buffered completions before a precise trap.
  */
class FloatingPointMemoryPipeline(p: OooParams) extends Module {
    require(p.fpConfig.memory)
    val io = IO(new Bundle {
        val execute = Flipped(Decoupled(new FloatingPointExecution(p)))
        val pc = Input(UInt(64.W))
        val trap = Input(Bool())
        val complete = Decoupled(new BackendCompletion(p))
        val memory = new DataPort
        val busy = Output(Bool())
        val pmpState = Input(new PmpState)
        val dataPrivilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
    })
    val lsu = Module(new LoadStoreUnit(p, registerStart = true))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true))
    responses.io.upstream <> lsu.io.memory
    io.memory <> responses.io.downstream
    lsu.io.cancel := false.B
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B

    val completions = Module(new TwoEntryRegisterQueue(new BackendCompletion(p)))
    completions.io.enq <> lsu.io.complete
    io.complete <> completions.io.deq

    val prepared = Reg(new MemoryOperation(p))
    val preparedValid = RegInit(false.B)
    val inst = io.execute.bits.command.instruction
    val store = FloatingPointSubset.store(inst)
    val offset = Mux(store,
        Cat(Fill(52, inst(31)), inst(31, 25), inst(11, 7)),
        Cat(Fill(52, inst(31)), inst(31, 20)))
    val payload = WireDefault(0.U.asTypeOf(new MemoryOperation(p)))
    payload.token := io.execute.bits.command.token
    payload.pc := io.pc
    payload.address := io.execute.bits.command.integerSource + offset
    payload.data := io.execute.bits.operands(1) // FSW preserves raw, unboxed bits.
    payload.store := store
    payload.size := inst(13, 12)
    payload.unsigned := true.B
    when(io.execute.valid && !preparedValid) {
        assert(FloatingPointSubset.memory(inst), "non-memory command entered FP memory pipeline")
        assert(inst(13, 12) === 2.U || inst(13, 12) === 3.U, "FP memory width must be 4/8 bytes")
        prepared := payload
        preparedValid := true.B
    }

    // A misaligned instruction faults in the LSU using its ORIGINAL address.
    // Its PMP result cannot override the higher-priority misalignment fault.
    // Align only the checker's address so naturally aligned accesses use exact
    // end = start | (length-1), without a 65-bit carry chain or XLEN wrap.
    val alignmentMask = Mux(prepared.size === 2.U, 3.U(3.W), 7.U(3.W))
    val pmp = Module(new PmpChecker(p.pmpEntries, naturalAlignedAccess = true))
    pmp.io.state := io.pmpState
    pmp.io.address := Cat(prepared.address(63, 3), prepared.address(2, 0) & ~alignmentMask)
    // Valid/cancel never select size or any address bits. Idle contents do not
    // authorize an access; the checker sees a stable, aligned old payload.
    pmp.io.size := prepared.size
    pmp.io.privilege := io.dataPrivilege
    pmp.io.access := Mux(prepared.store, PmpAccess.write, PmpAccess.read)
    lsu.io.start.valid := io.execute.valid && preparedValid && !io.trap
    lsu.io.start.bits := prepared
    lsu.io.start.bits.accessDenied := pmp.io.denied && !io.virtualized
    lsu.io.start.bits.virtualized := io.virtualized
    io.execute.ready := preparedValid && lsu.io.start.ready && !io.trap
    when(lsu.io.start.fire || io.trap) { preparedValid := false.B }

    io.busy := preparedValid || lsu.io.busy || !responses.io.idle || completions.io.count =/= 0.U
    when(io.trap) {
        assert(!lsu.io.busy && responses.io.idle && completions.io.count === 0.U,
            "precise FP trap requires accepted memory and completions to drain")
    }
}
