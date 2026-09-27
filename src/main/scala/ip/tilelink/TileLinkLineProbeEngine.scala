package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundleB, TLBundleC, TLOpcode, TLParams, TLPermissions}

class LineProbeRequest(addressBits: Int, tagBits: Int) extends Bundle {
    val address = UInt(addressBits.W)
    val tag     = UInt(tagBits.W)
}

class LineProbeResponse(tagBits: Int) extends Bundle {
    val tag     = UInt(tagBits.W)
    val hasData = Bool()
    val data    = UInt(512.W)
    val corrupt = Bool()
}

/** Four independent 64-byte ProbeBlock(toN) transactions by default. This is the B/C transaction
  * component of a coherent home: it does not own a directory, route voluntary Releases, or issue Grants.
  */
class TileLinkLineProbeEngine(params: TLParams = TLParams(), entries: Int = 4, tagBits: Int = 8) extends Module {
    require(params.dataWidth == 64 && params.addrWidth >= 7 && params.sizeBits >= 3)
    require(entries >= 2 && entries <= 8 && isPow2(entries))
    require(params.sourceBits >= log2Ceil(entries) && tagBits >= 1)

    val io = IO(new Bundle {
        val request  = Flipped(Decoupled(new LineProbeRequest(params.addrWidth, tagBits)))
        val response = Decoupled(new LineProbeResponse(tagBits))
        val probe    = Decoupled(new TLBundleB(params))
        val ack      = Flipped(Decoupled(new TLBundleC(params)))
    })

    private val free :: send :: receive :: complete :: Nil = Enum(4)
    private val slotBits = log2Ceil(entries)
    private val phase = RegInit(VecInit(Seq.fill(entries)(free)))
    private val address = Reg(Vec(entries, UInt(params.addrWidth.W)))
    private val tag = Reg(Vec(entries, UInt(tagBits.W)))
    private val beats = RegInit(VecInit(Seq.fill(entries)(0.U(3.W))))
    private val hasData = RegInit(VecInit(Seq.fill(entries)(false.B)))
    private val words = Reg(Vec(entries, Vec(8, UInt(64.W))))
    private val corrupt = RegInit(VecInit(Seq.fill(entries)(false.B)))
    private val sendQueue = Module(new Queue(UInt(slotBits.W), entries, pipe = false, flow = false))
    private val cBurst = RegInit(false.B)
    private val cBurstSource = Reg(UInt(params.sourceBits.W))

    val freeMask = VecInit((0 until entries).map(i => phase(i) === free))
    val freeSlot = PriorityEncoder(freeMask)
    val sameLine = VecInit((0 until entries).map(i =>
        phase(i) =/= free && address(i) === io.request.bits.address)).asUInt.orR
    sendQueue.io.enq.valid := io.request.valid && freeMask.asUInt.orR && !sameLine
    sendQueue.io.enq.bits := freeSlot
    io.request.ready := freeMask.asUInt.orR && !sameLine && sendQueue.io.enq.ready
    when(io.request.fire) {
        assert(io.request.bits.address(5, 0) === 0.U, "line probe address must be 64-byte aligned")
        phase(freeSlot) := send
        address(freeSlot) := io.request.bits.address
        tag(freeSlot) := io.request.bits.tag
        beats(freeSlot) := 0.U
        hasData(freeSlot) := false.B
        corrupt(freeSlot) := false.B
    }

    val sendSlot = Mux(sendQueue.io.deq.valid, sendQueue.io.deq.bits, 0.U)
    io.probe.valid := sendQueue.io.deq.valid
    io.probe.bits := 0.U.asTypeOf(io.probe.bits)
    io.probe.bits.opcode := TLOpcode.ProbeBlock
    io.probe.bits.param := TLPermissions.toN
    io.probe.bits.size := 6.U
    io.probe.bits.source := sendSlot
    io.probe.bits.address := address(sendSlot)
    io.probe.bits.mask := "hff".U
    sendQueue.io.deq.ready := io.probe.ready
    when(sendQueue.io.deq.valid) {
        assert(phase(sendSlot) === send, "line probe send queue contains a non-pending slot")
    }
    when(io.probe.fire) { phase(sendSlot) := receive }

    val source = io.ack.bits.source(slotBits - 1, 0)
    val immediateAck = io.probe.fire && sendSlot === source
    io.ack.ready := io.ack.valid && (phase(source) === receive || immediateAck)
    when(io.ack.valid) {
        assert(io.ack.bits.source < entries.U, "line probe returned an unknown source")
        assert(phase(source) === receive || immediateAck, "line probe response has no outstanding request")
        assert(io.ack.bits.address === address(source) && io.ack.bits.size === 6.U,
            "line probe response address or size mismatch")
        assert(io.ack.bits.opcode === TLOpcode.ProbeAck || io.ack.bits.opcode === TLOpcode.ProbeAckData,
            "line probe response opcode mismatch")
        assert(io.ack.bits.param === TLPermissions.tToN || io.ack.bits.param === TLPermissions.bToN ||
            io.ack.bits.param === 5.U, "line probe response must relinquish the line")
        when(cBurst) {
            assert(io.ack.bits.source === cBurstSource && io.ack.bits.opcode === TLOpcode.ProbeAckData,
                "line probe C burst interleaved or changed source")
        }
        when(beats(source) =/= 0.U) {
            assert(io.ack.bits.opcode === TLOpcode.ProbeAckData && hasData(source),
                "line probe data burst changed opcode")
        }
        when(io.ack.bits.opcode === TLOpcode.ProbeAck) {
            assert(beats(source) === 0.U && !io.ack.bits.corrupt,
                "line probe ProbeAck must be a clean single beat")
        }
    }
    when(io.ack.fire) {
        when(io.ack.bits.opcode === TLOpcode.ProbeAck) {
            phase(source) := complete
        }.otherwise {
            hasData(source) := true.B
            words(source)(beats(source)) := io.ack.bits.data
            corrupt(source) := corrupt(source) || io.ack.bits.corrupt
            when(beats(source) === 7.U) {
                phase(source) := complete
                cBurst := false.B
            }.otherwise {
                beats(source) := beats(source) + 1.U
                cBurst := true.B
                cBurstSource := io.ack.bits.source
            }
        }
    }

    val doneMask = VecInit((0 until entries).map(i => phase(i) === complete))
    val doneSlot = PriorityEncoder(doneMask)
    io.response.valid := doneMask.asUInt.orR
    io.response.bits.tag := tag(doneSlot)
    io.response.bits.hasData := hasData(doneSlot)
    io.response.bits.data := Mux(hasData(doneSlot), Cat((7 to 0 by -1).map(i => words(doneSlot)(i))), 0.U)
    io.response.bits.corrupt := corrupt(doneSlot)
    when(io.response.fire) { phase(doneSlot) := free }
}
