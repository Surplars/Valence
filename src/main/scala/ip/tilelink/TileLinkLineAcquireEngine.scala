package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundleA, TLBundleD, TLBundleE, TLOpcode, TLParams}

class LineAcquireRequest(addressBits: Int, tagBits: Int) extends Bundle {
    val address        = UInt(addressBits.W)
    val tag            = UInt(tagBits.W)
    val grow           = UInt(2.W)
    val permissionOnly = Bool()
}

class LineAcquireResponse(tagBits: Int) extends Bundle {
    val tag     = UInt(tagBits.W)
    val hasData = Bool()
    val data    = UInt(512.W)
    val cap     = UInt(2.W)
    val error   = Bool()
}

/** Four independent 64-byte TL-C Acquire transactions by default. GrantData is reassembled by
  * source; Grant and GrantData both require an E-channel GrantAck before a result is exposed.
  * A coherent cache must also handle B/C probes and voluntary C Releases outside this engine.
  */
class TileLinkLineAcquireEngine(params: TLParams = TLParams(), entries: Int = 4, tagBits: Int = 8)
    extends Module {
    require(params.dataWidth == 64 && params.addrWidth >= 7 && params.sizeBits >= 3)
    require(entries >= 2 && entries <= 8 && isPow2(entries))
    require(params.sourceBits >= log2Ceil(entries) && params.sinkBits >= 1 && tagBits >= 1)

    val io = IO(new Bundle {
        val request  = Flipped(Decoupled(new LineAcquireRequest(params.addrWidth, tagBits)))
        val response = Decoupled(new LineAcquireResponse(tagBits))
        val a        = Decoupled(new TLBundleA(params))
        val d        = Flipped(Decoupled(new TLBundleD(params)))
        val e        = Decoupled(new TLBundleE(params))
    })

    private val free :: send :: receive :: acknowledge :: complete :: Nil = Enum(5)
    private val slotBits = log2Ceil(entries)
    private val phase = RegInit(VecInit(Seq.fill(entries)(free)))
    private val address = Reg(Vec(entries, UInt(params.addrWidth.W)))
    private val tag = Reg(Vec(entries, UInt(tagBits.W)))
    private val grow = Reg(Vec(entries, UInt(2.W)))
    private val permissionOnly = Reg(Vec(entries, Bool()))
    private val beats = RegInit(VecInit(Seq.fill(entries)(0.U(3.W))))
    private val words = Reg(Vec(entries, Vec(8, UInt(64.W))))
    private val cap = Reg(Vec(entries, UInt(2.W)))
    private val sink = Reg(Vec(entries, UInt(params.sinkBits.W)))
    private val errors = RegInit(VecInit(Seq.fill(entries)(false.B)))
    private val sendQueue = Module(new Queue(UInt(slotBits.W), entries, pipe = false, flow = false))
    private val ackQueue = Module(new Queue(UInt(slotBits.W), entries, pipe = false, flow = false))
    private val dBurst = RegInit(false.B)
    private val dBurstSource = Reg(UInt(params.sourceBits.W))

    val freeMask = VecInit((0 until entries).map(i => phase(i) === free))
    val freeSlot = PriorityEncoder(freeMask)
    sendQueue.io.enq.valid := io.request.valid && freeMask.asUInt.orR
    sendQueue.io.enq.bits := freeSlot
    io.request.ready := freeMask.asUInt.orR && sendQueue.io.enq.ready
    when(io.request.fire) {
        assert(io.request.bits.address(5, 0) === 0.U, "line acquire address must be 64-byte aligned")
        assert(io.request.bits.grow <= 2.U, "line acquire grow permission invalid")
        phase(freeSlot) := send
        address(freeSlot) := io.request.bits.address
        tag(freeSlot) := io.request.bits.tag
        grow(freeSlot) := io.request.bits.grow
        permissionOnly(freeSlot) := io.request.bits.permissionOnly
        beats(freeSlot) := 0.U
        errors(freeSlot) := false.B
    }

    // Queue payload is undefined while empty; keep every slot-array index in range in simulation.
    val sendSlot = Mux(sendQueue.io.deq.valid, sendQueue.io.deq.bits, 0.U)
    io.a.valid := sendQueue.io.deq.valid
    io.a.bits := 0.U.asTypeOf(io.a.bits)
    io.a.bits.opcode := Mux(permissionOnly(sendSlot), TLOpcode.AcquirePerm, TLOpcode.AcquireBlock)
    io.a.bits.param := grow(sendSlot)
    io.a.bits.size := 6.U
    io.a.bits.source := sendSlot
    io.a.bits.address := address(sendSlot)
    io.a.bits.mask := "hff".U
    sendQueue.io.deq.ready := io.a.ready
    when(sendQueue.io.deq.valid) {
        assert(phase(sendSlot) === send, "line acquire send queue contains a non-pending slot")
    }
    when(io.a.fire) { phase(sendSlot) := receive }

    val source = io.d.bits.source(slotBits - 1, 0)
    val immediateGrant = io.a.fire && sendSlot === source
    val lastBeat = permissionOnly(source) || beats(source) === 7.U
    io.d.ready := io.d.valid && (phase(source) === receive || immediateGrant) &&
        (!lastBeat || ackQueue.io.enq.ready)
    ackQueue.io.enq.valid := io.d.fire && lastBeat
    ackQueue.io.enq.bits := source
    when(io.d.valid) {
        assert(io.d.bits.source < entries.U, "line acquire returned an unknown source")
        assert(phase(source) === receive || immediateGrant, "line acquire response has no outstanding request")
        assert(io.d.bits.size === 6.U && io.d.bits.opcode ===
            Mux(permissionOnly(source), TLOpcode.Grant, TLOpcode.GrantData),
            "line acquire Grant opcode or size mismatch")
        assert(io.d.bits.param <= 2.U, "line acquire Grant cap invalid")
        when(dBurst) {
            assert(io.d.bits.source === dBurstSource && io.d.bits.opcode === TLOpcode.GrantData,
                "line acquire D burst interleaved or changed source")
        }
        when(beats(source) =/= 0.U) {
            assert(io.d.bits.sink === sink(source) && io.d.bits.param === cap(source),
                "line acquire GrantData control changed between beats")
        }
        when(permissionOnly(source)) {
            assert(!io.d.bits.corrupt, "line acquire data-free Grant must not be corrupt")
        }
    }
    when(io.d.fire) {
        when(beats(source) === 0.U) {
            sink(source) := io.d.bits.sink
            cap(source) := io.d.bits.param
        }
        errors(source) := errors(source) || io.d.bits.denied || io.d.bits.corrupt
        when(!permissionOnly(source)) { words(source)(beats(source)) := io.d.bits.data }
        when(lastBeat) {
            phase(source) := acknowledge
            dBurst := false.B
        }.otherwise {
            beats(source) := beats(source) + 1.U
            dBurst := true.B
            dBurstSource := io.d.bits.source
        }
    }

    val ackSlot = Mux(ackQueue.io.deq.valid, ackQueue.io.deq.bits, 0.U)
    io.e.valid := ackQueue.io.deq.valid
    io.e.bits.sink := sink(ackSlot)
    ackQueue.io.deq.ready := io.e.ready
    when(ackQueue.io.deq.valid) {
        assert(phase(ackSlot) === acknowledge, "line acquire E queue contains a non-pending slot")
    }
    when(io.e.fire) { phase(ackSlot) := complete }

    val doneMask = VecInit((0 until entries).map(i => phase(i) === complete))
    // Once offered under backpressure, retain the selected complete owner even
    // if a lower-numbered slot completes. No extra latency on an unstalled result.
    val heldComplete = RegInit(false.B)
    val heldCompleteSlot = Reg(UInt(slotBits.W))
    val doneSlot = Mux(heldComplete, heldCompleteSlot, PriorityEncoder(doneMask))
    when(io.response.valid && !io.response.ready && !heldComplete) {
        heldComplete := true.B
        heldCompleteSlot := doneSlot
    }
    when(io.response.fire) { heldComplete := false.B }
    when(heldComplete) { assert(phase(heldCompleteSlot) === complete, "held completion lost its owner") }
    io.response.valid := doneMask.asUInt.orR
    io.response.bits.tag := tag(doneSlot)
    io.response.bits.hasData := !permissionOnly(doneSlot)
    io.response.bits.data := Mux(permissionOnly(doneSlot), 0.U,
        Cat((7 to 0 by -1).map(i => words(doneSlot)(i))))
    io.response.bits.cap := cap(doneSlot)
    io.response.bits.error := errors(doneSlot)
    when(io.response.fire) { phase(doneSlot) := free }
}
