package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** Ordered DataPort to TL-UL-style A/D bridge.
  * Read responses can return by source in any order; completion to DataPort remains in request order.
  * orderedWrites requires a manager that executes accepted Put requests in A-channel order.
  * orderedWriteBankBytes permits a write cohort within one ordered bank, draining before a bank switch.
  * allowWriteErrors requires the upstream to protect any stores retired before their physical response.
  */
class OrderedTileLinkBridge(
    entries: Int = 8,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    orderedWrites: Boolean = false,
    orderedMixedAccesses: Boolean = false,
    orderedWriteBankBase: BigInt = BigInt("80010000", 16),
    orderedWriteBankBytes: Int = 0,
    allowWriteErrors: Boolean = false,
    flowHeadResponse: Boolean = false
) extends Module {
    require(entries >= 2 && entries <= 16 && isPow2(entries))
    require(params.dataWidth == 64 && params.addrWidth >= 32 && params.addrWidth <= 64)
    require(params.sourceBits >= log2Ceil(entries))
    require(params.sizeBits >= 2)
    require(!orderedMixedAccesses || orderedWrites)
    require(orderedWriteBankBytes == 0 ||
        (orderedWriteBankBytes >= 16 && isPow2(orderedWriteBankBytes) && !orderedWrites))
    require(orderedWriteBankBase >= 0 &&
        (orderedWriteBankBytes == 0 || (orderedWriteBankBase % orderedWriteBankBytes == 0 &&
            orderedWriteBankBase + 2 * orderedWriteBankBytes <= (BigInt(1) << 64))))
    val io = IO(new Bundle {
        val data = Flipped(new DataPort)
        val tl   = new TLBundle(params)
    })
    TLBundle.tieoffMasterCoherence(io.tl)
    io.tl.b.ready := false.B
    when(io.tl.b.valid) { assert(false.B, "TileLink memory bridge cannot accept coherence probes") }

    val occupied = RegInit(VecInit(Seq.fill(entries)(false.B)))
    val done     = RegInit(VecInit(Seq.fill(entries)(false.B)))
    val writes   = RegInit(VecInit(Seq.fill(entries)(false.B)))
    val sizes    = Reg(Vec(entries, UInt(2.W)))
    val results  = Reg(Vec(entries, new DataResponse))
    val readCount  = RegInit(0.U(log2Ceil(entries + 1).W))
    val writeCount = RegInit(0.U(log2Ceil(entries + 1).W))
    val free = VecInit(occupied.map(x => !x)).asUInt
    val lockedSourceValid = RegInit(false.B)
    val lockedSource = Reg(UInt(log2Ceil(entries).W))
    val chosen = Mux(lockedSourceValid, lockedSource, PriorityEncoder(free))
    val order = Module(new Queue(UInt(log2Ceil(entries).W), entries, pipe = false, flow = false))
    val request = io.data.request.bits
    val writeDomain = Reg(UInt(2.W))
    val bankPipeline = if (orderedWriteBankBytes == 0) false.B else {
        val inBanks = request.address >= orderedWriteBankBase.U &&
            request.address < (orderedWriteBankBase + 2 * orderedWriteBankBytes).U
        val bank = Mux(request.address < (orderedWriteBankBase + orderedWriteBankBytes).U,
            0.U(2.W), 1.U(2.W))
        when(io.data.request.fire && request.write && writeCount === 0.U) {
            writeDomain := Mux(inBanks, bank, 2.U)
        }
        when(io.data.request.fire && request.write && writeCount =/= 0.U) {
            assert(inBanks && bank === writeDomain, "pipelined writes crossed TileLink RAM banks")
        }
        inBanks && bank === writeDomain
    }
    // A manager that executes every accepted A in order (including mixed reads/writes)
    // can overlap response latency without moving a younger access ahead of an older one.
    val canRead = (orderedMixedAccesses.B || writeCount === 0.U) && readCount < entries.U
    val canWrite = (orderedMixedAccesses.B || readCount === 0.U) && writeCount < entries.U &&
        (writeCount === 0.U || orderedWrites.B || bankPipeline)
    val issue = free.orR && order.io.enq.ready && Mux(request.write, canWrite, canRead)

    io.tl.a.valid := io.data.request.valid && issue
    io.tl.a.bits.opcode  := Mux(request.write, TLOpcode.PutPartialData, TLOpcode.Get)
    io.tl.a.bits.param   := 0.U
    io.tl.a.bits.size    := request.size
    io.tl.a.bits.source  := chosen
    io.tl.a.bits.address := request.address(params.addrWidth - 1, 0)
    io.tl.a.bits.mask    := request.mask
    io.tl.a.bits.data    := request.data
    io.tl.a.bits.corrupt := false.B
    io.data.request.ready := issue && io.tl.a.ready
    order.io.enq.valid := io.data.request.fire
    order.io.enq.bits  := chosen
    // A source freed by an unrelated response must not replace a stalled A-channel source.
    when(io.tl.a.valid && !io.tl.a.ready) {
        lockedSourceValid := true.B
        lockedSource := chosen
    }.elsewhen(io.tl.a.fire) {
        lockedSourceValid := false.B
    }
    when(lockedSourceValid) {
        assert(free(lockedSource), "backpressured TileLink A source must remain free")
    }
    when(io.data.request.fire) {
        assert(!request.atomic, "TileLink memory bridge accepts ordinary requests only")
        val bytes = 1.U(4.W) << request.size
        val lanes = ((255.U(8.W) >> (8.U - bytes)) << request.address(2, 0))(7, 0)
        assert((request.address(2, 0) & (bytes - 1.U)) === 0.U && request.mask === lanes,
            "TileLink memory request must be aligned and have exact byte strobes")
        if (params.addrWidth < 64) {
            assert(request.address(63, params.addrWidth) === 0.U, "TileLink address truncation")
        }
        occupied(chosen) := true.B
        done(chosen)     := false.B
        writes(chosen)   := request.write
        sizes(chosen)    := request.size
    }

    val dSource = Mux(io.tl.d.valid, io.tl.d.bits.source, 0.U)
    val dInRange = dSource < entries.U
    val dIndex = dSource(log2Ceil(entries) - 1, 0)
    val justIssued = io.data.request.fire && chosen === dIndex
    io.tl.d.ready := dInRange && occupied(dIndex) && !done(dIndex)
    when(io.tl.d.valid) {
        assert(dInRange, "TileLink response source outside bridge capacity")
        assert(!dInRange || justIssued || (occupied(dIndex) && !done(dIndex)),
            "TileLink response source is not awaiting a response")
    }
    when(io.tl.d.fire) {
        assert(io.tl.d.bits.opcode === Mux(writes(dIndex), TLOpcode.AccessAck, TLOpcode.AccessAckData),
            "TileLink response opcode mismatch")
        assert(io.tl.d.bits.param === 0.U && io.tl.d.bits.size === sizes(dIndex),
            "TileLink response parameter or size mismatch")
        if (!allowWriteErrors) {
            assert(!writes(dIndex) || (!io.tl.d.bits.denied && !io.tl.d.bits.corrupt),
                "TileLink RAM window must guarantee successful writes")
        }
        results(dIndex).data  := Mux(writes(dIndex), 0.U, io.tl.d.bits.data)
        results(dIndex).error := io.tl.d.bits.denied || io.tl.d.bits.corrupt
        results(dIndex).pageFault := false.B
        done(dIndex) := true.B
    }

    val head = Mux(order.io.deq.valid, order.io.deq.bits, 0.U)
    val incomingHead = flowHeadResponse.B && io.tl.d.fire && order.io.deq.valid &&
        dSource === head && !done(head)
    val incomingResult = Wire(new DataResponse)
    incomingResult.data := Mux(writes(dIndex), 0.U, io.tl.d.bits.data)
    incomingResult.error := io.tl.d.bits.denied || io.tl.d.bits.corrupt
    incomingResult.pageFault := false.B
    io.data.response.valid := order.io.deq.valid && (done(head) || incomingHead)
    io.data.response.bits  := Mux(done(head), results(head), incomingResult)
    order.io.deq.ready := io.data.response.ready && (done(head) || incomingHead)
    when(io.data.response.fire) {
        occupied(head) := false.B
        done(head)     := false.B
    }
    // Generic TL managers retain separate read/write cohorts; the ordered local RAM
    // may have both in flight while responses still retire in DataPort order.
    val readRequestFire  = io.data.request.fire && !request.write
    val readResponseFire = io.data.response.fire && !writes(head)
    val writeRequestFire = io.data.request.fire && request.write
    val writeResponseFire = io.data.response.fire && writes(head)
    when(readRequestFire =/= readResponseFire) {
        readCount := Mux(readRequestFire, readCount + 1.U, readCount - 1.U)
    }
    when(writeRequestFire =/= writeResponseFire) {
        writeCount := Mux(writeRequestFire, writeCount + 1.U, writeCount - 1.U)
    }
    assert(readCount <= entries.U)
    assert(writeCount <= entries.U)
}
