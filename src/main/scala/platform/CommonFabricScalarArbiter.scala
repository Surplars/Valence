package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.memory.NativeMemoryPort

/** Two physical lanes, fair locked arbitration, sixteen real response owners.
  * Ordinary requests and replies sustain one per cycle after pipeline fill.
  * Ownership is allocated only on the downstream native handshake and retired
  * only when the matching tagged response is consumed. A reservation clear is
  * an ordered barrier: all older physical replies retire before the pulse;
  * later requests wait for the tagged clear completion to be consumed.
  */
class CommonFabricScalarArbiter(p: CommonCpuTilePortParams = CommonCpuTilePortParams(), capacity: Int = 16)
    extends Module {
    require(capacity >= 8 && capacity <= (1 << p.scalarOwnerBits))
    val io = IO(new Bundle {
        val lanes = Vec(p.scalarPorts, Flipped(new CommonTileScalarPort(p)))
        val memory = new NativeMemoryPort
        val needsCoherenceLookup = Output(Bool())
        val clearReservation = Output(Bool())
        val stop = Input(Bool())
        val idle = Output(Bool())
        val outstanding = Output(UInt(log2Ceil(capacity + 1).W))
    })
    require(p.scalarPorts == 2)
    class Owner extends Bundle {
        val lane = Bool()
        val owner = UInt(p.scalarOwnerBits.W)
        val clear = Bool()
    }
    val owners = Module(new Queue(new Owner, capacity, pipe = false, flow = false))
    val turn = RegInit(false.B)
    val locked = RegInit(false.B)
    val lockedLane = Reg(Bool())
    val selected = Mux(locked, lockedLane,
        Mux(io.lanes(0).request.valid && io.lanes(1).request.valid, turn, io.lanes(1).request.valid))
    val request = Mux(selected, io.lanes(1).request.bits, io.lanes(0).request.bits)
    val valid = Mux(selected, io.lanes(1).request.valid, io.lanes(0).request.valid)
    val clearing = owners.io.deq.valid && owners.io.deq.bits.clear
    val admission = (!io.stop || locked) && !clearing && owners.io.enq.ready
    val clearReady = owners.io.count === 0.U
    io.memory.request.valid := valid && admission && !request.clearReservation
    io.memory.request.bits := request.memory
    io.needsCoherenceLookup := request.needsCoherenceLookup
    val ready = admission && Mux(request.clearReservation, clearReady, io.memory.request.ready)
    for (lane <- 0 until 2) {
        io.lanes(lane).request.ready := selected === lane.U && ready
        io.lanes(lane).response.valid := owners.io.deq.valid && owners.io.deq.bits.lane === lane.U &&
            (clearing || io.memory.response.valid)
        io.lanes(lane).response.bits.owner := owners.io.deq.bits.owner
        io.lanes(lane).response.bits.clearReservation := clearing
        io.lanes(lane).response.bits.memory := Mux(clearing,
            0.U.asTypeOf(io.lanes(lane).response.bits.memory), io.memory.response.bits)
    }
    val accepted = valid && ready
    owners.io.enq.valid := accepted
    owners.io.enq.bits.lane := selected
    owners.io.enq.bits.owner := request.owner
    owners.io.enq.bits.clear := request.clearReservation
    val responseReady = Mux(owners.io.deq.bits.lane, io.lanes(1).response.ready, io.lanes(0).response.ready)
    io.memory.response.ready := owners.io.deq.valid && !clearing && responseReady
    owners.io.deq.ready := responseReady && (clearing || io.memory.response.valid)
    io.clearReservation := accepted && request.clearReservation
    when(valid && admission && !ready) { locked := true.B; lockedLane := selected }
    when(accepted) { locked := false.B; turn := !selected }
    when(locked) { assert(valid, "held common scalar request was withdrawn") }
    when(io.memory.request.fire) {
        assert(!request.memory.virtualized, "virtual scalar request crossed the CPU/fabric boundary")
    }
    when(io.clearReservation) {
        assert(owners.io.count === 0.U && !io.memory.request.fire && !io.memory.response.valid,
            "reservation clear passed an older real native response")
    }
    when(clearing) {
        assert(owners.io.count === 1.U && !io.memory.request.valid,
            "new native work passed a pending clear completion")
    }
    io.outstanding := owners.io.count
    io.idle := owners.io.count === 0.U && !locked && !io.memory.request.valid && !io.memory.response.valid
}
