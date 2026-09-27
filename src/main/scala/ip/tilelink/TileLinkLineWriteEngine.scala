package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams}

class LineWriteRequest(addressBits: Int, tagBits: Int) extends Bundle {
    val address = UInt(addressBits.W)
    val data    = UInt(512.W)
    val tag     = UInt(tagBits.W)
}

class LineWriteResponse(tagBits: Int) extends Bundle {
    val tag   = UInt(tagBits.W)
    val error = Bool()
}

/** Four independent 64-byte TL-UH PutFullData transactions by default. Each A burst holds the
  * channel until all eight beats are accepted, while D acknowledgements may return out of order.
  * This writes backing memory; a TL-C cache eviction requires ReleaseData and a coherent home.
  */
class TileLinkLineWriteEngine(params: TLParams = TLParams(), entries: Int = 4, tagBits: Int = 8) extends Module {
    require(params.dataWidth == 64 && params.addrWidth >= 7 && params.sizeBits >= 3)
    require(entries >= 2 && entries <= 8 && isPow2(entries))
    require(params.sourceBits >= log2Ceil(entries) && tagBits >= 1)

    val io = IO(new Bundle {
        val request  = Flipped(Decoupled(new LineWriteRequest(params.addrWidth, tagBits)))
        val response = Decoupled(new LineWriteResponse(tagBits))
        val tl       = new TLBundle(params)
    })

    private val free :: send :: receive :: complete :: Nil = Enum(4)
    private val slotBits = log2Ceil(entries)
    private val phase = RegInit(VecInit(Seq.fill(entries)(free)))
    private val address = Reg(Vec(entries, UInt(params.addrWidth.W)))
    private val tag = Reg(Vec(entries, UInt(tagBits.W)))
    private val words = Reg(Vec(entries, Vec(8, UInt(64.W))))
    private val errors = RegInit(VecInit(Seq.fill(entries)(false.B)))
    private val beat = RegInit(0.U(3.W))
    private val sendQueue = Module(new Queue(UInt(slotBits.W), entries, pipe = false, flow = false))

    val freeMask = VecInit((0 until entries).map(i => phase(i) === free))
    val freeSlot = PriorityEncoder(freeMask)
    sendQueue.io.enq.valid := io.request.valid && freeMask.asUInt.orR
    sendQueue.io.enq.bits := freeSlot
    io.request.ready := freeMask.asUInt.orR && sendQueue.io.enq.ready
    when(io.request.fire) {
        assert(io.request.bits.address(5, 0) === 0.U, "line write address must be 64-byte aligned")
        phase(freeSlot) := send
        address(freeSlot) := io.request.bits.address
        tag(freeSlot) := io.request.bits.tag
        errors(freeSlot) := false.B
        for (i <- 0 until 8) {
            words(freeSlot)(i) := io.request.bits.data(64 * i + 63, 64 * i)
        }
    }

    val sendSlot = Mux(sendQueue.io.deq.valid, sendQueue.io.deq.bits, 0.U)
    io.tl.a.valid := sendQueue.io.deq.valid
    io.tl.a.bits := 0.U.asTypeOf(io.tl.a.bits)
    io.tl.a.bits.opcode := TLOpcode.PutFullData
    io.tl.a.bits.size := 6.U
    io.tl.a.bits.source := sendSlot
    io.tl.a.bits.address := address(sendSlot)
    io.tl.a.bits.mask := "hff".U
    io.tl.a.bits.data := words(sendSlot)(beat)
    sendQueue.io.deq.ready := io.tl.a.ready && beat === 7.U
    when(sendQueue.io.deq.valid) {
        assert(phase(sendSlot) === send, "line write send queue contains a non-pending slot")
    }
    when(io.tl.a.fire) {
        beat := beat + 1.U
        when(beat === 7.U) { phase(sendSlot) := receive }
    }

    val source = io.tl.d.bits.source(slotBits - 1, 0)
    val finalBeat = io.tl.a.fire && beat === 7.U && sendSlot === source
    // Ready must not depend on the last A beat's ready signal: a fabric may have
    // an A-ready/D-ready path through a manager and otherwise form a combinational loop.
    // The assertion below still rejects an acknowledgement before the final beat.
    io.tl.d.ready := io.tl.d.valid && (phase(source) === receive || phase(source) === send)
    when(io.tl.d.valid) {
        assert(io.tl.d.bits.source < entries.U, "line write returned an unknown source")
        assert(phase(source) === receive || finalBeat, "line write response has no outstanding request")
        assert(io.tl.d.bits.opcode === TLOpcode.AccessAck && io.tl.d.bits.size === 6.U,
            "line write response must be one AccessAck")
    }
    when(io.tl.d.fire) {
        errors(source) := io.tl.d.bits.denied || io.tl.d.bits.corrupt
        phase(source) := complete
    }

    val doneMask = VecInit((0 until entries).map(i => phase(i) === complete))
    val doneSlot = PriorityEncoder(doneMask)
    io.response.valid := doneMask.asUInt.orR
    io.response.bits.tag := tag(doneSlot)
    io.response.bits.error := errors(doneSlot)
    when(io.response.fire) { phase(doneSlot) := free }

    TLBundle.tieoffMasterCoherence(io.tl)
}
