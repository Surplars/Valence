package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams, TLPermissions}
import soc.ip.tilelink.{TileLinkLineProbeEngine, TileLinkLineTransfer}

/** Serialized TL-C home for private T owners. A line has at most one owner; a competing
  * client or uncached agent probes that owner before accessing backing RAM. The client
  * count is explicit so source IDs and probe/GrantAck routing remain local to each hart.
  */
class CoherentLineHome(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    base: BigInt = BigInt("80010000", 16),
    bytes: Int = 4096,
    nClients: Int = 1,
    trackedLines: Int = 0
) extends Module {
    require(bytes >= 64 && bytes % 64 == 0 && isPow2(bytes) && base % 64 == 0)
    require(nClients >= 1 && nClients <= 8)
    require(trackedLines == 0 || (nClients == 1 && trackedLines >= 2 &&
        trackedLines <= bytes / 64 && isPow2(trackedLines)))
    require(trackedLines != 0 || base % bytes == 0)
    require(params.sourceBits >= 3, "line transfer needs separate read and write source IDs")
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val clients = Vec(nClients, Flipped(new TLBundle(params)))
        val line = new TLBundle(params)
        val upstreamRequestCpu = Input(Bool())
    })
    private def client(index: UInt): TLBundle = if (nClients == 1) io.clients(0) else io.clients(index)
    private val clientBits = math.max(1, log2Ceil(nClients))
    private val Seq(idle, probeSend, probeWait, accessSend, accessWait, fillSend, fillWait,
        grant, grantAck, releaseReceive, lineWriteSend, lineWriteWait, releaseAck) = Enum(13)
    private val state = RegInit(idle)
    private val resume = Reg(UInt(state.getWidth.W))
    private val reads = RegInit(0.U(4.W))
    private val access = Reg(new DataRequest)
    private val acquireAddress = Reg(UInt(params.addrWidth.W))
    private val acquireSource = Reg(UInt(params.sourceBits.W))
    private val acquireClient = Reg(UInt(clientBits.W))
    private val probeAddress = Reg(UInt(params.addrWidth.W))
    private val probeClient = Reg(UInt(clientBits.W))
    private val probeForAcquire = Reg(Bool())
    private val lineAddress = Reg(UInt(params.addrWidth.W))
    private val lineData = Reg(Vec(8, UInt(64.W)))
    private val lineError = Reg(Bool())
    private val beat = RegInit(0.U(3.W))
    private val releaseSource = Reg(UInt(params.sourceBits.W))
    private val releaseClient = Reg(UInt(clientBits.W))
    private val releaseParam = Reg(UInt(3.W))
    private val releaseOrigin = Reg(Bool())
    private val ownerEntries = if (trackedLines == 0) bytes / 64 else trackedLines
    private val owned = RegInit(VecInit(Seq.fill(ownerEntries)(false.B)))
    private val owner = Reg(Vec(ownerEntries, UInt(clientBits.W)))
    // A single direct-mapped L1 can own at most one physical line per cache index.
    // Tagging those slots bounds directory state by L1 capacity instead of RAM size.
    private val ownedTags = if (trackedLines == 0) None else
        Some(Reg(Vec(ownerEntries, UInt((params.addrWidth - 6).W))))
    private val lineTransfer = Module(new TileLinkLineTransfer(
        params.copy(sourceBits = params.sourceBits - 1), entries = 4))
    private val probeEngine = Module(new TileLinkLineProbeEngine(params, entries = 4))
    io.line <> lineTransfer.io.tl
    for (i <- 0 until nClients) {
        io.clients(i).b.valid := probeEngine.io.probe.valid && probeClient === i.U
        io.clients(i).b.bits := probeEngine.io.probe.bits
    }
    probeEngine.io.probe.ready := client(probeClient).b.ready

    private val aValid = VecInit(io.clients.map(_.a.valid))
    private val aAny = aValid.asUInt.orR
    private val aTurn = RegInit(0.U(clientBits.W))
    private val afterTurn = VecInit((0 until nClients).map(i => aValid(i) && i.U >= aTurn))
    private val aSelect = Wire(UInt(clientBits.W))
    aSelect := Mux(afterTurn.asUInt.orR, PriorityEncoder(afterTurn), PriorityEncoder(aValid))
    private val releaseValid = VecInit(io.clients.map(c =>
        c.c.valid && TLOpcode.isRelease(c.c.bits.opcode)))
    private val releaseAny = releaseValid.asUInt.orR
    private val releaseSelect = Wire(UInt(clientBits.W))
    releaseSelect := PriorityEncoder(releaseValid)
    private val cSelect = Mux(state === releaseReceive, releaseClient,
        Mux(releaseAny, releaseSelect, probeClient))
    private val clientC = client(cSelect).c

    private def lineIndex(address: UInt): UInt = address(5 + log2Ceil(ownerEntries), 6)
    private def lineOwned(address: UInt): Bool = owned(lineIndex(address)) &&
        ownedTags.map(_(lineIndex(address)) === address(params.addrWidth - 1, 6)).getOrElse(true.B)
    private def inRam(address: UInt): Bool =
        address >= base.U(65.W) && address < (base + bytes).U(65.W)
    private val request = io.upstream.request.bits
    private val releaseAllowed = reads === 0.U &&
        (state === idle || state === probeSend || state === probeWait)
    private val needsProbe = !io.upstreamRequestCpu && inRam(request.address) &&
        lineOwned(request.address)
    private val upperWrite = io.upstream.request.valid && request.write
    private val directRead = state === idle && io.upstream.request.valid && !upperWrite &&
        !needsProbe && !aAny && !releaseAny

    io.downstream.request.valid := directRead || state === accessSend
    io.downstream.request.bits := Mux(state === accessSend, access, request)
    io.upstream.request.ready := state === idle && !aAny && !releaseAny &&
        Mux(upperWrite || needsProbe, reads === 0.U, io.downstream.request.ready)
    io.upstream.response.valid := Mux(state === accessWait, io.downstream.response.valid,
        state === idle && reads =/= 0.U && io.downstream.response.valid)
    io.upstream.response.bits := io.downstream.response.bits
    io.downstream.response.ready := io.upstream.response.ready &&
        (state === accessWait || (state === idle && reads =/= 0.U))
    when((io.upstream.request.fire && !upperWrite && !needsProbe) =/=
        (state === idle && io.upstream.response.fire)) {
        reads := Mux(io.upstream.request.fire && !upperWrite && !needsProbe, reads + 1.U, reads - 1.U)
    }
    when(state === idle && io.upstream.request.fire && (upperWrite || needsProbe)) {
        access := request
        when(needsProbe) {
            probeAddress := Cat(request.address(63, 6), 0.U(6.W))
            probeClient := owner(lineIndex(request.address))
            probeForAcquire := false.B
        }
        state := Mux(needsProbe, probeSend, accessSend)
    }
    when(state === accessSend && io.downstream.request.fire) { state := accessWait }
    when(state === accessWait && io.upstream.response.fire) { state := idle }

    for (i <- 0 until nClients) {
        io.clients(i).a.ready := state === idle && reads === 0.U && !releaseAny &&
            aSelect === i.U
    }
    val selectedAcquire = client(aSelect).a.bits
    val acquireFire = aAny && client(aSelect).a.fire
    val immediateFill = acquireFire && !lineOwned(selectedAcquire.address)
    when(acquireFire) {
        val a = selectedAcquire
        aTurn := Mux(aSelect === (nClients - 1).U, 0.U, aSelect + 1.U)
        assert(a.opcode === TLOpcode.AcquireBlock &&
            a.param === TLPermissions.nToT && a.size === 6.U &&
            a.address(5, 0) === 0.U && inRam(a.address) &&
            (!lineOwned(a.address) || owner(lineIndex(a.address)) =/= aSelect),
            "home accepts an aligned nToT AcquireBlock from a non-owner")
        acquireAddress := a.address
        acquireSource := a.source
        acquireClient := aSelect
        when(lineOwned(a.address)) {
            probeAddress := a.address
            probeClient := owner(lineIndex(a.address))
            probeForAcquire := true.B
            state := probeSend
        }.otherwise { state := Mux(lineTransfer.io.readRequest.ready, fillWait, fillSend) }
    }
    // A no-probe Acquire can reserve the line reader in its acceptance cycle.
    // If the reader is full, fillSend keeps the registered address stable until it opens.
    lineTransfer.io.readRequest.valid := state === fillSend || immediateFill
    lineTransfer.io.readRequest.bits.address := Mux(state === fillSend, acquireAddress,
        selectedAcquire.address)
    lineTransfer.io.readRequest.bits.tag := 0.U
    when(lineTransfer.io.readRequest.fire) { state := fillWait }
    lineTransfer.io.readResponse.ready := state === fillWait
    when(lineTransfer.io.readResponse.fire) {
        for (i <- 0 until 8) {
            lineData(i) := lineTransfer.io.readResponse.bits.data(64 * i + 63, 64 * i)
        }
        lineError := lineTransfer.io.readResponse.bits.error
        beat := 0.U
        state := grant
    }
    private val dClient = Mux(state === releaseAck, releaseClient, acquireClient)
    for (i <- 0 until nClients) {
        io.clients(i).d.valid := (state === grant || state === releaseAck) && dClient === i.U
        io.clients(i).d.bits := 0.U.asTypeOf(io.clients(i).d.bits)
        io.clients(i).d.bits.opcode := Mux(state === releaseAck, TLOpcode.ReleaseAck, TLOpcode.GrantData)
        io.clients(i).d.bits.param := Mux(state === releaseAck, 0.U, TLPermissions.toT)
        io.clients(i).d.bits.size := 6.U
        io.clients(i).d.bits.source := Mux(state === releaseAck, releaseSource, acquireSource)
        io.clients(i).d.bits.sink := 0.U
        io.clients(i).d.bits.denied := state === grant && lineError
        io.clients(i).d.bits.data := lineData(beat)
        io.clients(i).d.bits.corrupt := state === grant && lineError
    }
    when(client(dClient).d.fire && state === grant) {
        beat := beat + 1.U
        when(beat === 7.U) { state := grantAck }
    }
    for (i <- 0 until nClients) {
        io.clients(i).e.ready := state === grantAck && acquireClient === i.U
    }
    when(client(acquireClient).e.fire) {
        assert(client(acquireClient).e.bits.sink === 0.U, "line home GrantAck sink mismatch")
        when(!lineError) {
            if (trackedLines != 0) {
                assert(!owned(lineIndex(acquireAddress)) || lineOwned(acquireAddress),
                    "single-hart L1 must release an indexed line before acquiring another")
                ownedTags.get(lineIndex(acquireAddress)) := acquireAddress(params.addrWidth - 1, 6)
            }
            owned(lineIndex(acquireAddress)) := true.B
            owner(lineIndex(acquireAddress)) := acquireClient
        }
        state := idle
    }

    probeEngine.io.request.valid := state === probeSend && !releaseAny
    probeEngine.io.request.bits.address := probeAddress
    probeEngine.io.request.bits.tag := 0.U
    when(probeEngine.io.request.fire) { state := probeWait }
    probeEngine.io.response.ready := state === probeWait && !releaseAny
    when(probeEngine.io.response.fire) {
        assert(!probeEngine.io.response.bits.corrupt, "dirty probe data must not be corrupt")
        owned(lineIndex(probeAddress)) := false.B
        when(probeEngine.io.response.bits.hasData) {
            lineAddress := probeAddress
            for (i <- 0 until 8) {
                lineData(i) := probeEngine.io.response.bits.data(64 * i + 63, 64 * i)
            }
            lineError := false.B
            beat := 0.U
            releaseOrigin := false.B
            state := lineWriteSend
        }.otherwise { state := Mux(probeForAcquire, fillSend, accessSend) }
    }

    // C is shared by probe acknowledgements and voluntary releases. A release can preempt a
    // queued probe so a cache evicting another line can make progress without a B/C deadlock.
    val isRelease = TLOpcode.isRelease(clientC.bits.opcode)
    probeEngine.io.ack.valid := clientC.valid && !isRelease && !releaseAny
    probeEngine.io.ack.bits := clientC.bits
    for (i <- 0 until nClients) {
        io.clients(i).c.ready := cSelect === i.U &&
            Mux(isRelease, releaseAllowed || state === releaseReceive, probeEngine.io.ack.ready)
    }
    when(clientC.fire && isRelease && state =/= releaseReceive) {
        assert(releaseAllowed && clientC.bits.size === 6.U &&
            clientC.bits.address(5, 0) === 0.U && inRam(clientC.bits.address) &&
            lineOwned(clientC.bits.address) &&
            owner(lineIndex(clientC.bits.address)) === cSelect &&
            clientC.bits.param === TLPermissions.tToN,
            "invalid voluntary line release")
        releaseClient := cSelect
        releaseSource := clientC.bits.source
        releaseParam := clientC.bits.param
        lineAddress := clientC.bits.address
        lineData(0) := clientC.bits.data
        beat := 1.U
        resume := state
        when(clientC.bits.opcode === TLOpcode.ReleaseData) {
            state := releaseReceive
        }.otherwise {
            owned(lineIndex(clientC.bits.address)) := false.B
            state := releaseAck
        }
    }
    when(clientC.fire && state === releaseReceive) {
        assert(clientC.bits.opcode === TLOpcode.ReleaseData &&
            clientC.bits.address === lineAddress &&
            clientC.bits.source === releaseSource &&
            clientC.bits.param === releaseParam &&
            clientC.bits.size === 6.U && !clientC.bits.corrupt,
            "ReleaseData burst changed control or was corrupt")
        lineData(beat) := clientC.bits.data
        when(beat === 7.U) {
            beat := 0.U
            releaseOrigin := true.B
            state := lineWriteSend
        }.otherwise { beat := beat + 1.U }
    }
    lineTransfer.io.writeRequest.valid := state === lineWriteSend
    lineTransfer.io.writeRequest.bits.address := lineAddress
    lineTransfer.io.writeRequest.bits.data := lineData.asUInt
    lineTransfer.io.writeRequest.bits.tag := 0.U
    when(lineTransfer.io.writeRequest.fire) { state := lineWriteWait }
    lineTransfer.io.writeResponse.ready := state === lineWriteWait
    when(lineTransfer.io.writeResponse.fire) {
        assert(!lineTransfer.io.writeResponse.bits.error,
            "coherent home backing RAM rejected a dirty line writeback")
        when(releaseOrigin) {
            owned(lineIndex(lineAddress)) := false.B
            state := releaseAck
        }.elsewhen(probeForAcquire) {
            // ProbeAckData already supplied the full line. Backing RAM is now current;
            // forwarding the buffered data avoids a redundant eight-beat refill.
            beat := 0.U
            state := grant
        }.otherwise { state := accessSend }
    }
    when(state === releaseAck && client(releaseClient).d.fire) { state := resume }
}
