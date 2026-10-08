package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams}

class LineFillRequest(addressBits: Int, tagBits: Int) extends Bundle {
    val address = UInt(addressBits.W)
    val tag     = UInt(tagBits.W)
}

class LineFillResponse(tagBits: Int) extends Bundle {
    val tag   = UInt(tagBits.W)
    val data  = UInt(512.W)
    val error = Bool()
}

/** Four independent 64-byte TL-UH Get transactions by default. A accepts one new line per cycle while a free
  * slot exists; D accepts one 64-bit beat per cycle and may complete source IDs out of order. Whole-line results
  * retain the caller's tag under response backpressure. This is a line-transfer engine, not a TL-C cache client:
  * it holds no coherence permissions and never answers probes.
  */
class TileLinkLineFillEngine(params: TLParams = TLParams(), entries: Int = 4, tagBits: Int = 8) extends Module {
    require(params.dataWidth == 64 && params.addrWidth >= 7 && params.sizeBits >= 3)
    require(entries >= 2 && entries <= 8 && isPow2(entries))
    require(params.sourceBits >= log2Ceil(entries) && tagBits >= 1)

    val io = IO(new Bundle {
        val request  = Flipped(Decoupled(new LineFillRequest(params.addrWidth, tagBits)))
        val response = Decoupled(new LineFillResponse(tagBits))
        val tl       = new TLBundle(params)
    })

    private val free :: send :: receive :: complete :: Nil = Enum(4)
    private val slotBits = log2Ceil(entries)
    private val phase    = RegInit(VecInit(Seq.fill(entries)(free)))
    private val address  = Reg(Vec(entries, UInt(params.addrWidth.W)))
    private val tag      = Reg(Vec(entries, UInt(tagBits.W)))
    private val beats    = RegInit(VecInit(Seq.fill(entries)(0.U(3.W))))
    private val words    = Reg(Vec(entries, Vec(8, UInt(64.W))))
    private val errors   = RegInit(VecInit(Seq.fill(entries)(false.B)))
    private val sendQueue = Module(new Queue(UInt(slotBits.W), entries, pipe = false, flow = false))

    val freeMask = VecInit((0 until entries).map(i => phase(i) === free))
    val freeSlot = PriorityEncoder(freeMask)
    sendQueue.io.enq.valid := io.request.valid && freeMask.asUInt.orR
    sendQueue.io.enq.bits := freeSlot
    io.request.ready := freeMask.asUInt.orR && sendQueue.io.enq.ready
    when(io.request.fire) {
        assert(io.request.bits.address(5, 0) === 0.U, "line fill address must be 64-byte aligned")
        phase(freeSlot)   := send
        address(freeSlot) := io.request.bits.address
        tag(freeSlot)     := io.request.bits.tag
        beats(freeSlot)   := 0.U
        errors(freeSlot)  := false.B
    }

    val sendSlot = Mux(sendQueue.io.deq.valid, sendQueue.io.deq.bits, 0.U)
    io.tl.a.valid        := sendQueue.io.deq.valid
    io.tl.a.bits         := 0.U.asTypeOf(io.tl.a.bits)
    io.tl.a.bits.opcode  := TLOpcode.Get
    io.tl.a.bits.size    := 6.U
    io.tl.a.bits.source  := sendSlot
    io.tl.a.bits.address := address(sendSlot)
    io.tl.a.bits.mask    := "hff".U
    sendQueue.io.deq.ready := io.tl.a.ready
    when(sendQueue.io.deq.valid) {
        assert(phase(sendSlot) === send, "line fill send queue contains a non-pending slot")
    }
    when(io.tl.a.fire) { phase(sendSlot) := receive }

    val source = io.tl.d.bits.source(slotBits - 1, 0)
    io.tl.d.ready := io.tl.d.valid && phase(source) === receive
    when(io.tl.d.valid) {
        assert(io.tl.d.bits.source < entries.U, "line fill returned an unknown source")
        assert(phase(source) === receive, "line fill response has no outstanding request")
        assert(io.tl.d.bits.opcode === TLOpcode.AccessAckData && io.tl.d.bits.size === 6.U,
            "line fill response must contain eight AccessAckData beats")
    }
    when(io.tl.d.fire) {
        words(source)(beats(source)) := io.tl.d.bits.data
        errors(source) := errors(source) || io.tl.d.bits.denied || io.tl.d.bits.corrupt
        when(beats(source) === 7.U) { phase(source) := complete }
            .otherwise { beats(source) := beats(source) + 1.U }
    }

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
    io.response.valid      := doneMask.asUInt.orR
    io.response.bits.tag   := tag(doneSlot)
    io.response.bits.data  := Cat((7 to 0 by -1).map(i => words(doneSlot)(i)))
    io.response.bits.error := errors(doneSlot)
    when(io.response.fire) { phase(doneSlot) := free }

    TLBundle.tieoffMasterCoherence(io.tl)
}
