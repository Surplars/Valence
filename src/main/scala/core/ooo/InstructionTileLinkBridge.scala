package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** One instruction packet in flight, with one immutable ROM beat retained across packets. */
class InstructionTileLinkBridge(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    immutableBase: BigInt = BigInt("80000000", 16),
    immutableBytes: Int = 8192,
    parallelAddresses: Boolean = false
) extends Module {
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 2 && params.sizeBits >= 2)
    require(immutableBase >= 0 && immutableBase % 8 == 0 && immutableBytes >= 8 && immutableBytes % 8 == 0)
    require(immutableBase + immutableBytes <= (BigInt(1) << 64))
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort)
        val tl = new TLBundle(params)
    })
    TLBundle.tieoffMasterCoherence(io.tl)
    io.tl.b.ready := false.B
    when(io.tl.b.valid) { assert(false.B, "instruction TileLink bridge cannot accept probes") }

    val active = RegInit(false.B)
    val heldResponse = RegInit(false.B)
    val heldData = Reg(UInt(64.W))
    val heldErrors = Reg(UInt(2.W))
    val alignedPc = Reg(UInt(64.W))
    val odd = Reg(Bool())
    val packetPc = Reg(UInt(64.W))
    val packetMask = Reg(UInt(2.W))
    val fullPacket = Reg(Bool())
    val packetGroup = RegInit(false.B)
    val nextGroup = RegInit(false.B)
    val sent = RegInit(VecInit(Seq.fill(2)(false.B)))
    val received = RegInit(VecInit(Seq.fill(2)(false.B)))
    val beats = Reg(Vec(2, UInt(64.W)))
    val beatGood = Reg(Vec(2, Bool()))
    val cacheValid = RegInit(false.B)
    val cacheAddress = Reg(UInt(64.W))
    val cacheData = Reg(UInt(64.W))
    val startLocked = RegInit(false.B)
    val lockedHit = Reg(Bool())
    val lockedData = Reg(UInt(64.W))
    val startAligned = Cat(io.fetch.request.bits(63, 3), 0.U(3.W))
    val startOdd = io.fetch.request.bits(2)
    val startMask = io.fetch.requestMask
    val startFull = startMask === 3.U
    def alignedInRom(address: UInt): Bool = {
        val lastByte = if (parallelAddresses) Cat(0.U(1.W), address(63, 3), 7.U(3.W))
            else address +& 7.U
        address >= immutableBase.U && lastByte < (immutableBase + immutableBytes).U(65.W)
    }
    val startInRom = alignedInRom(startAligned)
    val startCacheHit = Wire(Bool())
    val startCacheData = Wire(UInt(64.W))

    val issueOld = active && (!sent(0) || (odd && !sent(1)))
    val issueSecond = sent(0)
    io.tl.a.bits.opcode := TLOpcode.Get
    io.tl.a.bits.param := 0.U
    io.tl.a.bits.size := Mux(issueOld || startFull, 3.U, 2.U)
    io.tl.a.bits.source := Cat(Mux(issueOld, packetGroup, nextGroup),
        Mux(issueOld, issueSecond, Mux(startFull, startCacheHit, startMask(1))))
    if (parallelAddresses) {
        // Return/cache-hit qualification selects an already computed address;
        // it must not launch a new XLEN carry after the last D beat arrives.
        val oldNextAddress = alignedPc + 8.U
        val startNextAddress = startAligned + 8.U
        val partialNextAddress = io.fetch.request.bits + 4.U
        io.tl.a.bits.address := Mux(issueOld, Mux(issueSecond, oldNextAddress, alignedPc),
            Mux(startFull, Mux(startCacheHit, startNextAddress, startAligned),
                Mux(startMask(1), partialNextAddress, io.fetch.request.bits)))
    } else {
        io.tl.a.bits.address := Mux(issueOld, alignedPc + Mux(issueSecond, 8.U, 0.U),
            Mux(startFull, startAligned + Mux(startCacheHit, 8.U, 0.U),
                io.fetch.request.bits + Mux(startMask(1), 4.U, 0.U)))
    }
    io.tl.a.bits.mask := Mux(io.tl.a.bits.size === 3.U, 255.U,
        Mux(io.tl.a.bits.address(2), "hf0".U, "h0f".U))
    io.tl.a.bits.data := 0.U
    io.tl.a.bits.corrupt := false.B
    when(io.tl.a.fire && issueOld) { sent(issueSecond.asUInt) := true.B }

    val dSource = io.tl.d.bits.source
    val dIndex = dSource(0)
    val dInRange = dSource <= 3.U && dSource(1) === packetGroup
    io.tl.d.ready := active && dInRange && sent(dIndex) && !received(dIndex)
    when(io.tl.d.valid) {
        assert(active && dInRange && sent(dIndex) && !received(dIndex),
            "instruction TileLink response has no matching Get")
        assert(io.tl.d.bits.opcode === TLOpcode.AccessAckData && io.tl.d.bits.param === 0.U &&
            io.tl.d.bits.size === Mux(fullPacket, 3.U, 2.U),
            "instruction TileLink response opcode or size mismatch")
    }
    val d0Fire = io.tl.d.fire && dIndex === 0.U
    val d1Fire = io.tl.d.fire && dIndex === 1.U
    val dError = io.tl.d.bits.denied || io.tl.d.bits.corrupt
    val next0 = Mux(d0Fire, Mux(dError, 0.U, io.tl.d.bits.data), beats(0))
    val next1 = Mux(d1Fire, Mux(dError, 0.U, io.tl.d.bits.data), beats(1))
    val lastD = io.tl.d.fire && (received(0) || d0Fire) && (received(1) || d1Fire)
    val firstPartial = Mux(packetPc(2), next0(63, 32), next0(31, 0))
    val secondPartial = Mux(packetPc(2), next1(31, 0), next1(63, 32))
    val assembled = Mux(fullPacket, Mux(odd, Cat(next1(31, 0), next0(63, 32)), next0),
        Cat(Mux(packetMask(1), secondPartial, 0.U), Mux(packetMask(0), firstPartial, 0.U)))
    val firstError = Mux(d0Fire, dError, !beatGood(0))
    val secondError = Mux(d1Fire, dError, !beatGood(1))
    val assembledErrors = Mux(fullPacket, Cat(Mux(odd, secondError, firstError), firstError),
        Cat(!packetMask(1) || secondError, !packetMask(0) || firstError))
    val completedAddress = if (parallelAddresses) Mux(odd, alignedPc + 8.U, alignedPc)
        else alignedPc + Mux(odd, 8.U, 0.U)
    val completedData = Mux(odd, next1, next0)
    val completedGood = Mux(odd, Mux(d1Fire, !dError, beatGood(1)), Mux(d0Fire, !dError, beatGood(0)))
    val completedInRom = alignedInRom(completedAddress)
    val bypassHit = lastD && completedGood && completedInRom && completedAddress === startAligned
    val rawCacheHit = startFull && startOdd && startInRom &&
        (bypassHit || (cacheValid && cacheAddress === startAligned))
    startCacheHit := Mux(startLocked, lockedHit, rawCacheHit)
    startCacheData := Mux(startLocked, lockedData, Mux(bypassHit, completedData, cacheData))
    io.fetch.response.valid := heldResponse || lastD
    io.fetch.response.bits := Mux(heldResponse, heldData, assembled)
    io.fetch.responseError := Mux(heldResponse, heldErrors, assembledErrors)
    io.fetch.responsePageFault := 0.U
    val canStart = (!active || lastD) && (!heldResponse || io.fetch.response.ready) &&
        (!lastD || io.fetch.response.ready)
    io.tl.a.valid := issueOld || (canStart && io.fetch.request.valid && startMask.orR)
    io.fetch.request.ready := canStart && !issueOld && (!startMask.orR || io.tl.a.ready)
    when(!issueOld && io.tl.a.valid && !io.tl.a.ready) {
        startLocked := true.B
        lockedHit := startCacheHit
        lockedData := startCacheData
    }
    when(io.fetch.response.fire && heldResponse) { heldResponse := false.B }
    when(io.tl.d.fire) {
        beats(dIndex) := Mux(dError, 0.U, io.tl.d.bits.data)
        beatGood(dIndex) := !dError
        received(dIndex) := true.B
        when(lastD) {
            when(fullPacket) {
                cacheValid := completedGood && completedInRom
                cacheAddress := completedAddress
                cacheData := completedData
            }
            when(!io.fetch.response.ready) {
                heldResponse := true.B
                heldData := assembled
                heldErrors := assembledErrors
            }
            active := false.B
        }
    }
    when(io.fetch.request.fire) {
        assert(io.fetch.request.bits(1, 0) === 0.U, "instruction fetch PC must be 32-bit aligned")
        when(!startMask.orR) {
            heldResponse := true.B
            heldData := 0.U
            heldErrors := 3.U
        }.otherwise {
            alignedPc := startAligned
            odd := startOdd
            packetPc := io.fetch.request.bits
            packetMask := startMask
            fullPacket := startFull
            sent(0) := true.B
            sent(1) := !startFull || !startOdd || startCacheHit
            received(0) := Mux(startFull, startCacheHit, !startMask(0))
            received(1) := Mux(startFull, !startOdd, !startMask(1))
            beats(0) := startCacheData
            beats(1) := 0.U
            beatGood(0) := startFull && startCacheHit
            beatGood(1) := false.B
            startLocked := false.B
            packetGroup := nextGroup
            nextGroup := !nextGroup
            active := true.B
        }
    }
}

/** Read-only TL-UL manager backed by the synchronous two-bank instruction ROM. */
class TileLinkInstructionRomAdapter(
    words: Int,
    base: BigInt = BigInt("80000000", 16),
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4),
    bufferedReplies: Boolean = false
) extends Module {
    require(words >= 4 && isPow2(words) && base >= 0 && base % 8 == 0)
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 1 && params.sizeBits >= 2)
    require(base + BigInt(words) * 4 <= (BigInt(1) << 64))
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
        val rom = new InstructionPort
    })
    TLBundle.tieoffSlaveCoherence(io.tl)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    when(io.tl.c.valid || io.tl.e.valid) { assert(false.B, "instruction ROM manager only supports TL-UL") }

    class Metadata extends Bundle {
        val source = UInt(params.sourceBits.W)
        val size = UInt(params.sizeBits.W)
        val highWord = Bool()
        val denied = Bool()
    }
    val metadata = Module(new Queue(new Metadata, 4, pipe = false, flow = false))
    val a = io.tl.a.bits
    io.rom.request.valid := io.tl.a.valid && metadata.io.enq.ready
    io.rom.request.bits := Cat(a.address(63, 3), 0.U(3.W))
    io.rom.requestMask := Mux(a.size === 3.U, 3.U, Mux(a.address(2), 2.U, 1.U))
    io.tl.a.ready := metadata.io.enq.ready && io.rom.request.ready
    metadata.io.enq.valid := io.tl.a.fire
    metadata.io.enq.bits.source := a.source
    metadata.io.enq.bits.size := a.size
    metadata.io.enq.bits.highWord := a.address(2)
    val lastByteOffset = ((1.U(4.W) << a.size(1, 0)) - 1.U)(2, 0)
    metadata.io.enq.bits.denied := a.address < base.U ||
        (a.address +& lastByteOffset) >= (base + BigInt(words) * 4).U(65.W)
    when(io.tl.a.fire) {
        // Idle FIFO payload need not be normalized, even though GSIM evaluates
        // assertion expressions outside their enable. Use fixed legal-size
        // decodes instead of native dynamic shifts of an undefined size byte.
        val bytes = MuxLookup(a.size, 0.U(4.W))(Seq(0.U -> 1.U, 1.U -> 2.U, 2.U -> 4.U, 3.U -> 8.U))
        val lowMask = MuxLookup(a.size, 0.U(8.W))(
            Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U, 3.U -> 255.U))
        val expectedMask = lowMask << a.address(2, 0)
        assert(a.opcode === TLOpcode.Get && a.param === 0.U && a.size <= 3.U &&
            (a.address & (bytes - 1.U)) === 0.U && a.mask === expectedMask && !a.corrupt,
            "instruction ROM manager accepts aligned 1/2/4/8-byte Get only")
    }

    // Empty bypass preserves the native one-cycle ROM latency/II=1. Occupancy-
    // only enqueue ready (pipe=false) cuts external D.ready from ROM request
    // credits. Capture data and its metadata together; source is released by
    // upstream routing only on the final externally consumed D, never here.
    val produced = if (bufferedReplies) {
        val replies = Module(new Queue(new TLBundleD(params), 2, pipe = false, flow = true)).suggestName("replies")
        io.tl.d <> replies.io.deq
        replies.io.enq
    } else io.tl.d
    produced.valid := metadata.io.deq.valid && io.rom.response.valid
    produced.bits.opcode := TLOpcode.AccessAckData
    produced.bits.param := 0.U
    produced.bits.size := metadata.io.deq.bits.size
    produced.bits.source := metadata.io.deq.bits.source
    produced.bits.sink := 0.U
    val responseError = Mux(metadata.io.deq.bits.size === 3.U, io.rom.responseError.orR,
        Mux(metadata.io.deq.bits.highWord, io.rom.responseError(1), io.rom.responseError(0)))
    produced.bits.denied := metadata.io.deq.bits.denied || responseError
    produced.bits.data := Mux(metadata.io.deq.bits.denied, 0.U, io.rom.response.bits)
    produced.bits.corrupt := false.B
    io.rom.response.ready := metadata.io.deq.valid && produced.ready
    metadata.io.deq.ready := produced.fire
    when(io.rom.response.valid) { assert(metadata.io.deq.valid, "ROM reply has no TileLink metadata") }
}
