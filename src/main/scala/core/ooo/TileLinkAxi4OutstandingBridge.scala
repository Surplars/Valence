package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.axi._

/** Shared bounded transaction slots with FIFO TL D completion by default.
  * maxOutstandingWrites=0 preserves the original exclusive-write fence.
  * A positive write limit enables ordinary-RAM reads and writes to disjoint
  * eight-byte-rounded physical intervals. RAW/WAR/WAW overlaps wait for full
  * TL retirement. Each slot retains AXI ID and TL source until its final D.
  * AW and complete W bursts follow one bounded write-order FIFO (AXI4 W has
  * no ID); B can complete in any ID order. AW/W progress independently.
  * Complete R bursts are buffered before D so late errors remain aggregate.
  * This is not MMIO/AMO reordering and does not relax upstream barriers.
  * Optional unorderedResponses fairly selects completed slots and locks whole D messages.
  * Target: one R/W/D beat per cycle on independent channels. Timing unverified.
  */
class TileLinkAxi4OutstandingBridge(
    tlParams: TLParams,
    axiAddressWidth: Int,
    axiIdWidth: Int,
    maxBurstBeats: Int,
    axiCache: Int,
    axiProt: Int,
    axiQos: Int,
    axiAddressBase: BigInt,
    axiWindowBytes: BigInt,
    maxOutstanding: Int,
    maxOutstandingWrites: Int = 0,
    unorderedResponses: Boolean = false
) extends Module {
    require(maxOutstanding >= 2 && isPow2(maxOutstanding))
    require(maxOutstanding <= (1 << axiIdWidth) && maxOutstanding <= (1 << tlParams.sourceBits))
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
    })
    require(maxOutstandingWrites >= 0 && maxOutstandingWrites <= maxOutstanding)
    require(maxOutstandingWrites == 0 || axiWindowBytes > 0)
    val slots = Seq.fill(maxOutstanding)(Module(new TileLinkAxi4BurstBridge(tlParams,
        axiAddressWidth, axiIdWidth, maxBurstBeats, axiCache, axiProt, axiQos,
        axiAddressBase, axiWindowBytes)))
    val slotWidth = log2Ceil(maxOutstanding)
    val head = RegInit(0.U(slotWidth.W))
    val tail = RegInit(0.U(slotWidth.W))
    val active = RegInit(VecInit(Seq.fill(maxOutstanding)(false.B)))
    val allocationSlot = if (unorderedResponses) {
        val free = VecInit(active.map(!_))
        val afterTail = VecInit((0 until maxOutstanding).map(i => free(i) && i.U >= tail))
        Mux(afterTail.asUInt.orR, PriorityEncoder(afterTail), PriorityEncoder(free))
    } else tail
    val exclusiveWriteSlot = if (unorderedResponses && maxOutstandingWrites == 0) Some(RegInit(0.U(slotWidth.W))) else None
    val sources = Reg(Vec(maxOutstanding, UInt(tlParams.sourceBits.W)))
    val writeActive = RegInit(false.B)
    val collecting = RegInit(false.B)
    val collectSlot = Reg(UInt(slotWidth.W))
    val beatWidth = TileLinkTransferBeatCount.width(tlParams)
    val collectRemaining = Reg(UInt(beatWidth.W))
    val replyRemaining = Reg(Vec(maxOutstanding, UInt(beatWidth.W)))
    val a = io.tl.a.bits
    val isWrite = a.opcode =/= TLOpcode.Get
    val requestBeats = TileLinkTransferBeatCount(a.size, tlParams)
    val sourceBusy = VecInit((0 until maxOutstanding).map(i => active(i) && sources(i) === a.source)).asUInt.orR
    // These ranges use full physical addresses, including the carry bit. A
    // rejected/misaligned request is conservative too: it cannot hide a hazard.
    val writes = RegInit(VecInit(Seq.fill(maxOutstanding)(false.B)))
    val starts = Reg(Vec(maxOutstanding, UInt(tlParams.addrWidth.W)))
    val ends = Reg(Vec(maxOutstanding, UInt((tlParams.addrWidth + 1).W)))
    val requestStart = Cat(a.address(tlParams.addrWidth - 1, 3), 0.U(3.W))
    val requestBytes = (1.U((tlParams.addrWidth + 1).W) << Mux(a.size < 3.U, 3.U, a.size))(tlParams.addrWidth, 0)
    val requestEnd = Cat(0.U(1.W), requestStart) + requestBytes
    val overlaps = VecInit((0 until maxOutstanding).map(i => active(i) &&
        (writes(i) || isWrite) && Cat(0.U(1.W), requestStart) < ends(i) &&
        Cat(0.U(1.W), starts(i)) < requestEnd)).asUInt.orR
    val writeCount = PopCount(VecInit((0 until maxOutstanding).map(i => active(i) && writes(i))))
    val writeOrder = if (maxOutstandingWrites > 0)
        Some(Module(new Queue(UInt(slotWidth.W), maxOutstanding, pipe = false, flow = false))) else None
    val canAllocate = !active(allocationSlot) && !sourceBusy && (if (maxOutstandingWrites == 0)
        !writeActive && (!isWrite || !active.asUInt.orR)
        else !overlaps && (!isWrite || (writeCount < maxOutstandingWrites.U && writeOrder.get.io.enq.ready)))
    writeOrder.foreach { q =>
        q.io.enq.valid := io.tl.a.fire && !collecting && isWrite
        q.io.enq.bits := allocationSlot
    }
    val selected = Mux(collecting, collectSlot, allocationSlot)
    val allowA = collecting || canAllocate
    io.tl.a.ready := allowA && VecInit(slots.map(_.io.tl.a.ready))(selected)
    io.tl.b.valid := false.B
    io.tl.b.bits := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    assert(!io.tl.c.valid && !io.tl.e.valid, "TL-AXI boundary does not support coherence")

    val replySlot = if (unorderedResponses) {
        val readyMask = VecInit((0 until maxOutstanding).map(i => active(i) && slots(i).io.tl.d.valid))
        val turn = RegInit(0.U(slotWidth.W))
        val afterTurn = VecInit((0 until maxOutstanding).map(i => readyMask(i) && i.U >= turn))
        val chosen = Mux(afterTurn.asUInt.orR, PriorityEncoder(afterTurn), PriorityEncoder(readyMask))
        val locked = RegInit(false.B)
        val held = Reg(UInt(slotWidth.W))
        val selectedReply = Mux(locked, held, chosen)
        // Lock at the first offer, including a stalled first beat. Never
        // interleave beats or withdraw a selected complete transaction.
        when(io.tl.d.valid && !locked) { locked := true.B; held := selectedReply }
        when(io.tl.d.fire && replyRemaining(selectedReply) === 1.U) {
            locked := false.B
            turn := selectedReply + 1.U
        }
        selectedReply
    } else head
    io.tl.d.valid := active(replySlot) && VecInit(slots.map(_.io.tl.d.valid))(replySlot)
    io.tl.d.bits := VecInit(slots.map(_.io.tl.d.bits))(replySlot)
    when(io.tl.d.fire) {
        replyRemaining(replySlot) := replyRemaining(replySlot) - 1.U
        when(replyRemaining(replySlot) === 1.U) {
            active(replySlot) := false.B
            if (!unorderedResponses) head := head + 1.U
            writeActive := false.B
        }
    }
    when(io.tl.a.fire) {
        when(collecting) {
            collectRemaining := collectRemaining - 1.U
            when(collectRemaining === 1.U) { collecting := false.B }
        }.otherwise {
            active(allocationSlot) := true.B
            sources(allocationSlot) := a.source
            writes(allocationSlot) := isWrite
            starts(allocationSlot) := requestStart
            ends(allocationSlot) := requestEnd
            replyRemaining(allocationSlot) := Mux(isWrite, 1.U, requestBeats)
            if (unorderedResponses) tail := allocationSlot + 1.U else tail := tail + 1.U
            when(isWrite) {
                writeActive := true.B
                exclusiveWriteSlot.foreach(_ := allocationSlot)
                collecting := requestBeats > 1.U
                collectSlot := allocationSlot
                collectRemaining := requestBeats - 1.U
            }
        }
    }

    val arArb = Module(new RRArbiter(new Axi4Address(axiAddressWidth, axiIdWidth), maxOutstanding))
    val awOffer = Wire(Decoupled(new Axi4Address(axiAddressWidth, axiIdWidth)))
    // Registered skid queues prevent arbitration changes from changing a stalled AXI payload.
    io.axi.ar <> Queue(arArb.io.out, 2)
    io.axi.aw <> Queue(awOffer, 2)
    val arIssued = RegInit(VecInit(Seq.fill(maxOutstanding)(false.B)))
    when(io.axi.ar.fire) { arIssued(io.axi.ar.bits.id(slotWidth - 1, 0)) := true.B }
    when(io.axi.r.fire && io.axi.r.bits.last) {
        arIssued(io.axi.r.bits.id(slotWidth - 1, 0)) := false.B
    }
    val rInRange = io.axi.r.bits.id < maxOutstanding.U
    val bInRange = io.axi.b.bits.id < maxOutstanding.U
    val rSlot = io.axi.r.bits.id(slotWidth - 1, 0)
    val bSlot = io.axi.b.bits.id(slotWidth - 1, 0)
    val readIssued = arIssued(rSlot) || (io.axi.ar.fire && io.axi.ar.bits.id === io.axi.r.bits.id)
    io.axi.r.ready := rInRange && active(rSlot) && readIssued && VecInit(slots.map(_.io.axi.r.ready))(rSlot)
    io.axi.b.ready := bInRange && active(bSlot) && VecInit(slots.map(_.io.axi.b.ready))(bSlot)
    when(io.axi.r.valid) {
        assert(rInRange && active(rSlot) && readIssued && VecInit(slots.map(_.io.axi.r.ready))(rSlot),
            "AXI R response has no live read owner")
    }
    when(io.axi.b.valid) {
        assert(bInRange && active(bSlot) && VecInit(slots.map(_.io.axi.b.ready))(bSlot),
            "AXI B response has no live write owner")
    }
    // AXI4 W has no ID. AW enqueue order and complete W burst order must agree,
    // even when W is accepted before AW. B completion does not occupy this lane.
    val writeOwner = WireDefault(exclusiveWriteSlot.getOrElse(head))
    val writeOffer = WireDefault(writeActive)
    if (unorderedResponses && maxOutstandingWrites == 0) {
        when(writeOffer) { assert(active(writeOwner) && writes(writeOwner), "exclusive write lost its allocated owner") }
    }
    writeOrder.foreach { q =>
        writeOwner := Mux(q.io.deq.valid, q.io.deq.bits, 0.U)
        writeOffer := q.io.deq.valid
        val addressSent = RegInit(false.B)
        val dataSent = RegInit(false.B)
        val addressFire = awOffer.fire
        val dataFire = io.axi.w.fire && io.axi.w.bits.last
        val localDone = VecInit(slots.map(_.io.tl.d.valid))(writeOwner)
        q.io.deq.ready := ((addressSent || addressFire) && (dataSent || dataFire)) || localDone
        when(addressFire) { addressSent := true.B }
        when(dataFire) { dataSent := true.B }
        when(q.io.deq.fire) { addressSent := false.B; dataSent := false.B }
        when(q.io.deq.valid) { assert(active(writeOwner) && writes(writeOwner), "write FIFO lost its live owner") }
    }
    // The write-order FIFO (or exclusive-write owner) has already selected the
    // only legal AW/W lane. A second round-robin arbiter duplicates selection
    // and state without providing any concurrency. Share this static decode
    // between the address and data channels; their handshakes stay independent.
    val writeOwnerOH = VecInit((0 until maxOutstanding).map(i => writeOffer && writeOwner === i.U))
    awOffer.valid := VecInit((0 until maxOutstanding).map(i =>
        writeOwnerOH(i) && slots(i).io.axi.aw.valid)).asUInt.orR
    awOffer.bits := Mux1H(writeOwnerOH, slots.map(_.io.axi.aw.bits))
    awOffer.bits.id := writeOwner
    io.axi.w.valid := writeOffer && VecInit(slots.map(_.io.axi.w.valid))(writeOwner)
    io.axi.w.bits := VecInit(slots.map(_.io.axi.w.bits))(writeOwner)
    for ((slot, i) <- slots.zipWithIndex) {
        slot.io.tl.a.valid := io.tl.a.valid && allowA && selected === i.U
        slot.io.tl.a.bits := io.tl.a.bits
        slot.io.tl.b.ready := false.B
        slot.io.tl.c.valid := false.B
        slot.io.tl.c.bits := 0.U.asTypeOf(slot.io.tl.c.bits)
        slot.io.tl.e.valid := false.B
        slot.io.tl.e.bits := 0.U.asTypeOf(slot.io.tl.e.bits)
        slot.io.tl.d.ready := io.tl.d.ready && active(i) && replySlot === i.U
        arArb.io.in(i) <> slot.io.axi.ar
        arArb.io.in(i).bits.id := i.U
        slot.io.axi.aw.ready := awOffer.ready && writeOwnerOH(i)
        slot.io.axi.w.ready := io.axi.w.ready && writeOwnerOH(i)
        slot.io.axi.r.valid := io.axi.r.valid && rInRange && rSlot === i.U && active(i) && readIssued
        slot.io.axi.r.bits := io.axi.r.bits
        slot.io.axi.r.bits.id := 0.U // lane engine's local ID; external ID owns routing
        slot.io.axi.b.valid := io.axi.b.valid && bInRange && bSlot === i.U && active(i)
        slot.io.axi.b.bits := io.axi.b.bits
        slot.io.axi.b.bits.id := 0.U
    }
}
