package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** Ordered DataPort RAM manager. Small TL-UL requests retain the pipelined metadata queue; optional
  * 16/32/64-byte line transfers drain that queue and use a separate non-interleaved burst path.
  */
class TileLinkDataRamAdapter(
    entries: Int = 8,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    burstEnabled: Boolean = false,
    burstBase: BigInt = BigInt("80010000", 16),
    burstBytes: Int = 4096
) extends Module {
    require(entries >= 2 && entries <= 16 && isPow2(entries))
    require(params.dataWidth == 64 && params.addrWidth >= 32 && params.addrWidth <= 64)
    require(params.sourceBits >= log2Ceil(entries) && params.sizeBits >= 2)
    require(!burstEnabled || params.sizeBits >= 3)
    require(burstBase >= 0 && burstBase % 8 == 0 && burstBytes >= 64 && isPow2(burstBytes) &&
        burstBase + burstBytes <= (BigInt(1) << params.addrWidth))
    val io = IO(new Bundle {
        val tl     = Flipped(new TLBundle(params))
        val memory = new DataPort
    })
    io.tl.b.valid := false.B
    io.tl.b.bits  := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    when(io.tl.c.valid || io.tl.e.valid) {
        assert(false.B, "TileLink RAM adapter does not accept coherence messages")
    }

    class Metadata extends Bundle {
        val source = UInt(params.sourceBits.W)
        val size   = UInt(params.sizeBits.W)
        val write  = Bool()
    }
    val pending = Module(new Queue(new Metadata, entries, pipe = false, flow = false))
    val sSingles :: sRead :: sDeniedRead :: sWrite :: sWriteAck :: Nil = Enum(5)
    val state = RegInit(sSingles)
    val burstSource = Reg(UInt(params.sourceBits.W))
    val burstSize = Reg(UInt(params.sizeBits.W))
    val burstAddress = Reg(UInt(params.addrWidth.W))
    val burstTotal = Reg(UInt(5.W))
    val sent = RegInit(0.U(5.W))
    val returned = RegInit(0.U(5.W))
    val burstInvalid = RegInit(false.B)
    val writeError = RegInit(false.B)
    val queuedRead = RegInit(false.B)
    val queuedSource = Reg(UInt(params.sourceBits.W))
    val queuedSize = Reg(UInt(params.sizeBits.W))
    val queuedAddress = Reg(UInt(params.addrWidth.W))
    val queuedLegal = Reg(Bool())
    val a = io.tl.a.bits
    val large = burstEnabled.B && a.size > 3.U
    val small = state === sSingles && !large
    val canStartBurst = state === sSingles && large && !pending.io.deq.valid
    val end = Cat(0.U(1.W), a.address) + (1.U(65.W) << a.size)
    val burstLegal = a.size <= 6.U &&
        (a.address & ((1.U(params.addrWidth.W) << a.size) - 1.U)) === 0.U &&
        a.address >= burstBase.U && end <= (burstBase + burstBytes).U(65.W)
    val startWrite = canStartBurst && a.opcode === TLOpcode.PutFullData
    val activeWrite = state === sWrite && sent < burstTotal
    val activeRead = state === sRead || state === sDeniedRead
    val queueRead = activeRead && !queuedRead && large && a.opcode === TLOpcode.Get

    io.tl.a.ready := Mux(state === sSingles,
        Mux(large, canStartBurst && Mux(a.opcode === TLOpcode.PutFullData && burstLegal,
            io.memory.request.ready, true.B), pending.io.enq.ready && io.memory.request.ready),
        Mux(activeRead, queueRead,
            Mux(state === sWrite && sent < burstTotal,
                Mux(burstInvalid, true.B, io.memory.request.ready), false.B)))

    io.memory.request.valid := (small && io.tl.a.valid && pending.io.enq.ready) ||
        (startWrite && burstLegal && io.tl.a.valid) ||
        (state === sRead && sent < burstTotal) ||
        (activeWrite && !burstInvalid && io.tl.a.valid)
    io.memory.request.bits := 0.U.asTypeOf(new DataRequest)
    when(small) {
        io.memory.request.bits.address := a.address
        io.memory.request.bits.write := a.opcode === TLOpcode.PutPartialData ||
            a.opcode === TLOpcode.PutFullData
        io.memory.request.bits.size := a.size
        io.memory.request.bits.data := a.data
        io.memory.request.bits.mask := a.mask
    }.elsewhen(startWrite) {
        io.memory.request.bits.address := a.address
        io.memory.request.bits.write := true.B
        io.memory.request.bits.size := 3.U
        io.memory.request.bits.data := a.data
        io.memory.request.bits.mask := 255.U
    }.elsewhen(state === sRead) {
        io.memory.request.bits.address := burstAddress + (sent << 3)
        io.memory.request.bits.size := 3.U
        io.memory.request.bits.mask := 255.U
    }.elsewhen(state === sWrite) {
        io.memory.request.bits.address := burstAddress + (sent << 3)
        io.memory.request.bits.write := true.B
        io.memory.request.bits.size := 3.U
        io.memory.request.bits.data := a.data
        io.memory.request.bits.mask := 255.U
    }

    pending.io.enq.valid := small && io.tl.a.fire
    pending.io.enq.bits.source := a.source
    pending.io.enq.bits.size := a.size
    pending.io.enq.bits.write := a.opcode =/= TLOpcode.Get
    when(io.tl.a.fire && state === sSingles) {
        assert(a.param === 0.U && !a.corrupt, "TileLink RAM request param or corruption invalid")
        when(large) {
            assert(a.opcode === TLOpcode.Get || a.opcode === TLOpcode.PutFullData,
                "burst RAM accepts Get and PutFullData only")
            assert(a.size <= 6.U && a.mask === 255.U,
                "burst RAM accepts only 16/32/64-byte full-mask messages")
            burstSource := a.source
            burstSize := a.size
            burstAddress := a.address
            burstTotal := TLBurst.beats(a.size, params)
            sent := Mux(a.opcode === TLOpcode.Get, 0.U, 1.U)
            returned := 0.U
            burstInvalid := !burstLegal
            writeError := !burstLegal
            state := Mux(a.opcode === TLOpcode.Get,
                Mux(burstLegal, sRead, sDeniedRead), sWrite)
        }.otherwise {
            assert(a.opcode === TLOpcode.Get || a.opcode === TLOpcode.PutPartialData ||
                a.opcode === TLOpcode.PutFullData, "single-beat RAM accepts Get and Put only")
            assert(a.size <= 3.U, "single-beat TileLink RAM request too large")
        }
    }
    when(io.tl.a.fire && activeRead) {
        assert(queueRead && a.param === 0.U && !a.corrupt && a.mask === 255.U && a.size <= 6.U,
            "queued RAM burst must be a complete Get")
        queuedRead := true.B
        queuedSource := a.source
        queuedSize := a.size
        queuedAddress := a.address
        queuedLegal := burstLegal
    }
    when(state === sRead && io.memory.request.fire) { sent := sent + 1.U }
    when(state === sRead && io.memory.response.fire) {
        assert(!io.memory.response.bits.error, "prevalidated RAM burst read must succeed")
    }
    when(state === sWrite) {
        when(io.tl.a.fire) {
            assert(a.opcode === TLOpcode.PutFullData && a.param === 0.U && a.size === burstSize &&
                a.source === burstSource && a.address === burstAddress && a.mask === 255.U && !a.corrupt,
                "PutFullData burst changed control, source or mask")
            sent := sent + 1.U
        }
        when(io.memory.response.fire && !burstInvalid) {
            assert(!io.memory.response.bits.error, "prevalidated RAM burst write must succeed")
            returned := returned + 1.U
            when(io.memory.response.bits.error) { writeError := true.B }
        }
        when(sent === burstTotal && (burstInvalid || returned === burstTotal)) { state := sWriteAck }
    }

    val head = pending.io.deq.bits
    io.tl.d.valid := Mux(state === sSingles, pending.io.deq.valid && io.memory.response.valid,
        Mux(state === sRead, io.memory.response.valid,
            state === sDeniedRead || state === sWriteAck))
    io.tl.d.bits := 0.U.asTypeOf(io.tl.d.bits)
    io.tl.d.bits.opcode := Mux(state === sSingles,
        Mux(head.write, TLOpcode.AccessAck, TLOpcode.AccessAckData),
        Mux(state === sWriteAck, TLOpcode.AccessAck, TLOpcode.AccessAckData))
    io.tl.d.bits.size := Mux(state === sSingles, head.size, burstSize)
    io.tl.d.bits.source := Mux(state === sSingles, head.source, burstSource)
    io.tl.d.bits.denied := Mux(state === sSingles, io.memory.response.bits.error,
        Mux(state === sWriteAck, writeError,
            Mux(state === sDeniedRead, true.B, io.memory.response.bits.error)))
    io.tl.d.bits.data := Mux(state === sSingles,
        Mux(head.write, 0.U, io.memory.response.bits.data),
        Mux(state === sRead && !io.memory.response.bits.error, io.memory.response.bits.data, 0.U))
    io.tl.d.bits.corrupt := io.tl.d.bits.denied && io.tl.d.bits.opcode === TLOpcode.AccessAckData
    io.memory.response.ready := Mux(state === sSingles, pending.io.deq.valid && io.tl.d.ready,
        Mux(state === sRead, io.tl.d.ready, state === sWrite && !burstInvalid))
    pending.io.deq.ready := state === sSingles && io.tl.d.fire
    when(state === sRead || state === sDeniedRead) {
        when(io.tl.d.fire) {
            returned := returned + 1.U
            when(returned === burstTotal - 1.U) {
                val nextRead = queuedRead || io.tl.a.fire
                when(nextRead) {
                    burstSource := Mux(queuedRead, queuedSource, a.source)
                    burstSize := Mux(queuedRead, queuedSize, a.size)
                    burstAddress := Mux(queuedRead, queuedAddress, a.address)
                    burstTotal := TLBurst.beats(Mux(queuedRead, queuedSize, a.size), params)
                    burstInvalid := !Mux(queuedRead, queuedLegal, burstLegal)
                    sent := 0.U
                    returned := 0.U
                    state := Mux(Mux(queuedRead, queuedLegal, burstLegal), sRead, sDeniedRead)
                    queuedRead := false.B
                }.otherwise { state := sSingles }
            }
        }
    }
    when(state === sWriteAck && io.tl.d.fire) { state := sSingles }
    when(io.memory.response.valid && state === sSingles) {
        assert(pending.io.deq.valid, "TileLink RAM returned a response without source metadata")
    }
}
