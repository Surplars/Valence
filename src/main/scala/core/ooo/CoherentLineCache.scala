package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams, TLPermissions}
import soc.ip.tilelink.TileLinkLineAcquireEngine

class CoherentCacheProfile extends Bundle {
    val emptySlotMiss = Bool()
    val replacementMiss = Bool()
    val readMiss = Bool()
    val writeMiss = Bool()
    val dirtyEviction = Bool()
    val missBlocked = Bool()
    val bypassBlocked = Bool()
    val probeBlocked = Bool()
    val evictionCycle = Bool()
    val refillCycle = Bool()
}

/** Single-client, write-back 64-byte L1. Resident lines own T permission; dirty data reaches
  * the home through ReleaseData on eviction or ProbeAckData on an external access.
  */
class CoherentLineCache(
    base: BigInt = BigInt("80010000", 16), bytes: Int = 8192, lines: Int = 128,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
) extends Module {
    require(lines >= 2 && lines <= 256 && isPow2(lines))
    require(bytes >= 64 && bytes % 64 == 0 && base % 64 == 0)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val tl = new TLBundle(params)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
        val profile = Output(new CoherentCacheProfile)
    })
    private val indexBits = log2Ceil(lines)
    private val Seq(idle, evictCapture, evictSend, evictAck, acquire, fill, missResponse,
        bypassSend, bypassResponse, probeCapture, probeSend, flushScan) = Enum(12)
    private val state = RegInit(idle)
    private val valid = RegInit(VecInit(Seq.fill(lines)(false.B)))
    private val dirty = RegInit(VecInit(Seq.fill(lines)(false.B)))
    private val tags = Reg(Vec(lines, UInt((64 - 6 - indexBits).W)))
    private val data = Seq.fill(8)(SyncReadMem(lines, Vec(8, UInt(8.W))))
    private val pending = Reg(new DataRequest)
    private val pendingBypass = Reg(Bool())
    private val missResult = Reg(new DataResponse)
    private val victimAddress = Reg(UInt(64.W))
    private val victimDirty = Reg(Bool())
    private val victimWords = Reg(Vec(8, UInt(64.W)))
    private val releaseBeat = RegInit(0.U(3.W))
    private val probeAddress = Reg(UInt(params.addrWidth.W))
    private val probeSource = Reg(UInt(params.sourceBits.W))
    private val probeHit = Reg(Bool())
    private val probeDirty = Reg(Bool())
    private val probeWords = Reg(Vec(8, UInt(64.W)))
    private val probeBeat = RegInit(0.U(3.W))
    private val probeResume = Reg(UInt(state.getWidth.W))
    private val flushActive = RegInit(false.B)
    private val flushFinished = RegInit(false.B)
    private val flushIndex = RegInit(0.U(indexBits.W))
    private val hitBank = Reg(UInt(3.W))
    private val readPending = RegInit(false.B)
    private val storePending = RegInit(false.B)
    private val readResponses = Module(new Queue(new DataResponse, 2, pipe = false, flow = true))

    private def lineIndex(address: UInt): UInt = address(5 + indexBits, 6)
    private def lineTag(address: UInt): UInt = address(63, 6 + indexBits)
    private val request = io.upstream.request.bits
    private val index = lineIndex(request.address)
    private val found = valid(index) && tags(index) === lineTag(request.address)
    private val cacheable = request.address >= base.U(65.W) &&
        (request.address +& (1.U(64.W) << request.size)) <= (base + bytes).U(65.W)
    private val ordinary = cacheable && !request.atomic && !request.virtualized && !request.uncached
    private val bypass = !ordinary
    private val needsEviction = cacheable && valid(index) && (!found || bypass)
    private val readHit = ordinary && found && !request.write
    private val writeHit = ordinary && found && request.write
    private val readCapacity = readResponses.io.count +& readPending.asUInt < 2.U
    private val noReadOutstanding = readResponses.io.count === 0.U && !readPending
    private val cpuFire = io.upstream.request.fire
    private val cpuRead = cpuFire && ordinary && found
    private val evictRead = cpuFire && needsEviction
    private val probeRead = io.tl.b.fire
    private val flushRead = state === flushScan && !io.tl.b.valid && valid(flushIndex) && dirty(flushIndex)
    private val readWords = VecInit((0 until 8).map { i =>
        val enabled = probeRead || evictRead || flushRead || (cpuRead && request.address(5, 3) === i.U)
        data(i).read(Mux(probeRead, lineIndex(io.tl.b.bits.address),
            Mux(flushRead, flushIndex, index)), enabled).asUInt
    })
    private def merge(oldWord: UInt, write: DataRequest): UInt = Cat((7 to 0 by -1).map { i =>
        Mux(write.mask(i), write.data(8 * i + 7, 8 * i), oldWord(8 * i + 7, 8 * i))
    })

    // B wins arbitration over a new CPU request. Read hits use the synchronous SRAM
    // output; masked write hits update the byte lanes directly. Both return through
    // the same ordered response queue. Independent read hits may be captured while one
    // line is being acquired, but their responses remain behind the older miss.
    io.flushDone := flushFinished
    io.tl.b.ready := state === idle || state === acquire || state === fill ||
        state === bypassSend || state === flushScan
    val hitUnderMiss = (state === acquire || state === fill) && readHit &&
        index =/= lineIndex(pending.address) && readCapacity
    io.upstream.request.ready := !io.tl.b.valid && !io.flushRequest &&
        Mux(state === idle, Mux(readHit || writeHit, readCapacity,
            noReadOutstanding && Mux(bypass && !needsEviction, io.downstream.request.ready, true.B)),
            hitUnderMiss)
    io.downstream.request.valid := (state === bypassSend && !io.tl.b.valid) ||
        (state === idle && noReadOutstanding && io.upstream.request.valid && bypass && !io.flushRequest &&
            !needsEviction && !io.tl.b.valid)
    io.downstream.request.bits := Mux(state === bypassSend, pending, request)
    io.downstream.response.ready := state === bypassResponse && io.upstream.response.ready
    readResponses.io.enq.valid := readPending
    readResponses.io.enq.bits.data := Mux(storePending, 0.U,
        Mux1H(UIntToOH(hitBank, 8), readWords))
    readResponses.io.enq.bits.error := false.B
    readResponses.io.enq.bits.pageFault := false.B
    readResponses.io.deq.ready := io.upstream.response.ready && state === idle
    assert(!readPending || readResponses.io.enq.ready, "cache hit response queue overflow")
    io.upstream.response.valid := (state === idle && readResponses.io.deq.valid) || state === missResponse ||
        (state === bypassResponse && io.downstream.response.valid)
    io.upstream.response.bits := Mux(state === missResponse, missResult,
        Mux(state === bypassResponse, io.downstream.response.bits, readResponses.io.deq.bits))
    io.hit := cpuFire && ordinary && found
    io.miss := cpuFire && ordinary && !found
    io.profile.emptySlotMiss := io.miss && !valid(index)
    io.profile.replacementMiss := io.miss && valid(index)
    io.profile.readMiss := io.miss && !request.write
    io.profile.writeMiss := io.miss && request.write
    io.profile.dirtyEviction := cpuFire && needsEviction && dirty(index)
    io.profile.missBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (state === evictCapture || state === evictSend || state === evictAck ||
            state === acquire || state === fill || state === missResponse)
    io.profile.bypassBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (state === bypassSend || state === bypassResponse)
    io.profile.probeBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (state === probeCapture || state === probeSend || (state === idle && io.tl.b.valid))
    io.profile.evictionCycle := state === evictCapture || state === evictSend || state === evictAck
    io.profile.refillCycle := state === acquire || state === fill
    readPending := false.B
    storePending := false.B
    when(!io.flushRequest) { flushFinished := false.B }
    when(state === idle && io.flushRequest && !flushFinished && noReadOutstanding && !io.tl.b.valid) {
        flushActive := true.B
        flushIndex := 0.U
        state := flushScan
    }
    when(state === flushScan && !io.tl.b.valid) {
        when(valid(flushIndex) && dirty(flushIndex)) {
            victimAddress := Cat(tags(flushIndex), flushIndex, 0.U(6.W))
            victimDirty := dirty(flushIndex)
            valid(flushIndex) := false.B
            dirty(flushIndex) := false.B
            state := evictCapture
        }.otherwise {
            when(flushIndex === (lines - 1).U) {
                flushFinished := true.B
                flushActive := false.B
                state := idle
            }.otherwise { flushIndex := flushIndex + 1.U }
        }
    }
    when(cpuFire) {
        when(state === idle) {
            pending := request
            pendingBypass := bypass
        }.otherwise {
            assert(hitUnderMiss, "only independent read hits may pass an outstanding cache miss")
        }
        when(needsEviction) {
            victimAddress := Cat(tags(index), index, 0.U(6.W))
            victimDirty := dirty(index)
            valid(index) := false.B
            dirty(index) := false.B
            state := evictCapture
        }.elsewhen(bypass) {
            state := bypassResponse
        }.elsewhen(writeHit) {
            dirty(index) := true.B
            readPending := true.B
            storePending := true.B
        }.elsewhen(readHit) {
            hitBank := request.address(5, 3)
            readPending := true.B
        }.otherwise { state := acquire }
    }
    when(state === evictCapture) {
        for (i <- 0 until 8) { victimWords(i) := readWords(i) }
        releaseBeat := 0.U
        state := evictSend
    }
    io.tl.c.valid := state === evictSend || state === probeSend
    io.tl.c.bits := 0.U.asTypeOf(io.tl.c.bits)
    io.tl.c.bits.opcode := Mux(state === evictSend,
        Mux(victimDirty, TLOpcode.ReleaseData, TLOpcode.Release),
        Mux(probeDirty, TLOpcode.ProbeAckData, TLOpcode.ProbeAck))
    io.tl.c.bits.param := Mux(state === evictSend, TLPermissions.tToN,
        Mux(probeHit, TLPermissions.tToN, 5.U))
    io.tl.c.bits.size := 6.U
    io.tl.c.bits.source := Mux(state === evictSend, 0.U, probeSource)
    io.tl.c.bits.address := Mux(state === evictSend, victimAddress, probeAddress)
    io.tl.c.bits.data := Mux(state === evictSend, victimWords(releaseBeat), probeWords(probeBeat))
    when(io.tl.c.fire && state === evictSend) {
        when(!victimDirty || releaseBeat === 7.U) { state := evictAck }
            .otherwise { releaseBeat := releaseBeat + 1.U }
    }
    when(io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck) {
        assert(state === evictAck && io.tl.d.bits.source === 0.U &&
            !io.tl.d.bits.denied && !io.tl.d.bits.corrupt, "cache ReleaseAck invalid")
        when(flushActive) {
            when(flushIndex === (lines - 1).U) {
                flushFinished := true.B
                flushActive := false.B
                state := idle
            }.otherwise {
                flushIndex := flushIndex + 1.U
                state := flushScan
            }
        }.otherwise { state := Mux(pendingBypass, bypassSend, acquire) }
    }
    when(state === bypassSend && io.downstream.request.fire) { state := bypassResponse }
    when(state === bypassResponse && io.upstream.response.fire) { state := idle }

    private val engine = Module(new TileLinkLineAcquireEngine(params, entries = 4))
    engine.io.request.valid := state === acquire && !io.tl.b.valid
    engine.io.request.bits.address := Cat(pending.address(63, 6), 0.U(6.W))
    engine.io.request.bits.tag := 0.U
    engine.io.request.bits.grow := TLPermissions.nToT
    engine.io.request.bits.permissionOnly := false.B
    when(engine.io.request.fire) { state := fill }
    engine.io.response.ready := state === fill
    val fillIndex = lineIndex(pending.address)
    val selected = pending.address(5, 3)
    val writeHitFire = cpuFire && state === idle && !needsEviction && !bypass && writeHit
    for (i <- 0 until 8) {
        val original = engine.io.response.bits.data(64 * i + 63, 64 * i)
        val filled = Mux(pending.write && selected === i.U && !engine.io.response.bits.error,
            merge(original, pending), original)
        val hitBankWrite = writeHitFire && request.address(5, 3) === i.U
        when(engine.io.response.fire || hitBankWrite) {
            data(i).write(Mux(engine.io.response.fire, fillIndex, index),
                Mux(engine.io.response.fire, filled, request.data).asTypeOf(Vec(8, UInt(8.W))),
                Mux(engine.io.response.fire, 255.U(8.W), request.mask).asBools)
        }
    }
    when(engine.io.response.fire) {
        assert(engine.io.response.bits.cap === TLPermissions.toT || engine.io.response.bits.error,
            "write-back L1 requires T permission")
        val word = (engine.io.response.bits.data >> (selected << 6))(63, 0)
        when(!engine.io.response.bits.error) {
            tags(fillIndex) := lineTag(pending.address)
            valid(fillIndex) := true.B
            dirty(fillIndex) := pending.write
        }
        missResult.data := Mux(pending.write, 0.U, word)
        missResult.error := engine.io.response.bits.error
        missResult.pageFault := false.B
        state := missResponse
    }
    when(state === missResponse && io.upstream.response.fire) { state := idle }
    io.tl.a <> engine.io.a
    engine.io.d.valid := io.tl.d.valid && io.tl.d.bits.opcode =/= TLOpcode.ReleaseAck
    engine.io.d.bits := io.tl.d.bits
    io.tl.d.ready := Mux(io.tl.d.bits.opcode === TLOpcode.ReleaseAck, state === evictAck, engine.io.d.ready)
    io.tl.e <> engine.io.e

    when(io.tl.b.fire) {
        assert(io.tl.b.bits.opcode === TLOpcode.ProbeBlock && io.tl.b.bits.size === 6.U &&
            io.tl.b.bits.param === TLPermissions.toN, "private cache expects an invalidation probe")
        val probeIndex = lineIndex(io.tl.b.bits.address)
        probeAddress := io.tl.b.bits.address
        probeSource := io.tl.b.bits.source
        probeResume := state
        probeHit := valid(probeIndex) && tags(probeIndex) === lineTag(io.tl.b.bits.address)
        probeDirty := valid(probeIndex) && tags(probeIndex) === lineTag(io.tl.b.bits.address) &&
            dirty(probeIndex)
        when(valid(probeIndex) && tags(probeIndex) === lineTag(io.tl.b.bits.address)) {
            valid(probeIndex) := false.B
            dirty(probeIndex) := false.B
        }
        state := probeCapture
    }
    when(state === probeCapture) {
        for (i <- 0 until 8) { probeWords(i) := readWords(i) }
        probeBeat := 0.U
        state := probeSend
    }
    when(io.tl.c.fire && state === probeSend) {
        when(!probeDirty || probeBeat === 7.U) { state := probeResume }
            .otherwise { probeBeat := probeBeat + 1.U }
    }
}
