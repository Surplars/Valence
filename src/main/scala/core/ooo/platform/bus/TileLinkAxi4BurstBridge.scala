package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.axi._

/** TL-UL Get/Put to an AXI4 INCR memory or register window.
  * One complete TL transaction is owned at a time. This bounds buffering and
  * preserves TL ordering across reads, writes, and AXI error responses.
  * AXI IDs are fixed at zero; no coherent, atomic, or exclusive operations.
  */
class TileLinkAxi4BurstBridge(
    val tlParams: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    val axiAddressWidth: Int = 64,
    val axiIdWidth: Int = 1,
    val maxBurstBeats: Int = 16,
    axiCache: Int = 0,
    axiProt: Int = 0,
    axiQos: Int = 0,
    val axiAddressBase: BigInt = 0,
    val axiWindowBytes: BigInt = 0,
    val writeCollectionFlow: Boolean = false,
    val lineReadChannel: Boolean = false,
    val localPayloadWriteEnable: Boolean = false,
    val localPayloadWriteRow: Boolean = false,
    val localAddressRanges: Boolean = false
) extends Module {
    require(!localPayloadWriteRow || (lineReadChannel && localPayloadWriteEnable),
        "local payload write rows require line banks and localized upper-bank enables")
    require(tlParams.dataWidth == 64 && tlParams.addrWidth >= axiAddressWidth)
    require(tlParams.sizeBits >= 3 && maxBurstBeats >= 2 && maxBurstBeats <= 256 && isPow2(maxBurstBeats))
    require((1 << tlParams.sizeBits) > log2Ceil(maxBurstBeats) + 3,
        "TL size field cannot encode the configured AXI burst length")
    require(axiCache >= 0 && axiCache < 16 && axiProt >= 0 && axiProt < 8 && axiQos >= 0 && axiQos < 16)
    require(axiAddressBase >= 0 && axiWindowBytes >= 0)
    require(axiAddressBase % 4096 == 0, "translated AXI and physical TL pages must share boundaries")
    require(axiWindowBytes == 0 || (axiWindowBytes <= (BigInt(1) << axiAddressWidth) &&
        axiAddressBase + axiWindowBytes <= (BigInt(1) << tlParams.addrWidth)))
    require(axiAddressBase == 0 || axiWindowBytes > 0)
    require(!writeCollectionFlow || axiWindowBytes > 0,
        "write collection flow requires an explicit ordinary RAM window")
    require(!lineReadChannel || (axiWindowBytes > 0 && maxBurstBeats >= 8),
        "whole-line playback requires a bounded RAM window and at least eight beats")
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
        val lineData = if (lineReadChannel) Some(Output(UInt(512.W))) else None
        val lineMode = if (lineReadChannel) Some(Input(Bool())) else None
    })
    io.tl.b.valid := false.B
    io.tl.b.bits := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    assert(!io.tl.c.valid && !io.tl.e.valid, "TL-AXI boundary does not support coherence")

    val (sIdle :: sCollectWrite :: sReadAddress :: sReadData :: sReadReply ::
        sWriteAddress :: sWriteData :: sWriteResponse :: sWriteReply :: Nil) = Enum(9)
    val state = RegInit(sIdle)
    val address = Reg(UInt(tlParams.addrWidth.W))
    // Translate on acceptance, before any narrowing. Keep the physical address
    // separately for TL multi-beat consistency checks.
    val axiAddress = Reg(UInt(axiAddressWidth.W))
    val source = Reg(UInt(tlParams.sourceBits.W))
    val size = Reg(UInt(tlParams.sizeBits.W))
    val countWidth = TileLinkTransferBeatCount.width(tlParams)
    val beatCount = Reg(UInt(countWidth.W))
    val index = RegInit(0.U(countWidth.W))
    val bufferIndex = index(log2Ceil(maxBurstBeats) - 1, 0)
    val readError = RegInit(false.B)
    val writeError = RegInit(false.B)
    val writeOpcode = Reg(UInt(3.W))
    val writeAddressDone = RegInit(false.B)
    val writeDataDone = RegInit(false.B)
    // One lane owns either a TL write or an AXI read, never both. Share its
    // payload capacity without sharing storage across independent AXI IDs.
    // One explicit write port and one asynchronous read port permit distributed
    // RAM inference; there is no extra request/response pipeline stage.
    // Carry write strobes beside data so both use the same capture/read address.
    // AXI read captures leave the unused strobe bits zero.
    val payload = if (!lineReadChannel) Some(Mem(maxBurstBeats, UInt(72.W))) else None
    // Same total payload bits. Eight beat-interleaved banks each have one
    // write/read port, allowing a completed 64-byte line to leave in one beat.
    // R capture still accepts one 64-bit beat/cycle; no unreturned byte escapes.
    val payloadBanks = if (lineReadChannel)
        Seq.fill(8)(Mem(maxBurstBeats / 8, UInt(72.W))) else Seq.empty
    val payloadWrite = WireDefault(false.B)
    val payloadWriteIndex = WireDefault(bufferIndex)
    val payloadWriteData = WireDefault(Cat(io.tl.a.bits.mask, io.tl.a.bits.data))
    // Default lanes still share one capture/playback cursor. The opt-in write
    // path gives the consumer its own cursor and uses registered capture
    // credits: no W beat can see a same-edge A write or an uninitialized word.
    // Capacity and the single memory write/read ports are unchanged.
    val writeCaptured = if (writeCollectionFlow) Some(RegInit(0.U(countWidth.W))) else None
    val writeSendIndex = if (writeCollectionFlow) Some(RegInit(0.U(countWidth.W))) else None
    val earlyWrite = if (writeCollectionFlow) state === sCollectWrite && !writeError else false.B
    val writePhase = state === sWriteAddress || earlyWrite
    val sendIndex = if (writeCollectionFlow) writeSendIndex.get else index
    val payloadReadIndex = if (writeCollectionFlow)
        Mux(writePhase, sendIndex, index)(log2Ceil(maxBurstBeats) - 1, 0) else bufferIndex
    val bankReads = if (lineReadChannel) {
        val row = if (maxBurstBeats == 8) 0.U else payloadReadIndex >> 3
        VecInit(payloadBanks.map(_.read(row)))
    } else WireDefault(VecInit(Seq.fill(8)(0.U(72.W))))
    val payloadRead = if (lineReadChannel) bankReads(payloadReadIndex(2, 0))
        else payload.get.read(payloadReadIndex)
    io.lineData.foreach(_ := Cat((0 until 8).reverse.map(i => bankReads(i)(63, 0))))
    val payloadReadData = payloadRead(63, 0)
    val a = io.tl.a.bits
    val maxSize = log2Ceil(maxBurstBeats) + 3
    val requestBeats = TileLinkTransferBeatCount(a.size, tlParams)
    val fitsBuffer = a.size <= maxSize.U
    val fullMask = MuxLookup(a.size, 255.U(8.W))(Seq(
        0.U -> (1.U(8.W) << a.address(2, 0)),
        1.U -> (3.U(8.W) << a.address(2, 0)),
        2.U -> (15.U(8.W) << a.address(2, 0)),
        3.U -> 255.U(8.W)))
    val isRead = a.opcode === TLOpcode.Get
    val isWrite = a.opcode === TLOpcode.PutFullData || a.opcode === TLOpcode.PutPartialData
    val isBurst = a.size > 3.U
    val byteCount = 1.U(12.W) << a.size
    val pageOffset = a.address(11, 0)
    val inWindow = if (axiWindowBytes > 0)
        a.address >= axiAddressBase.U &&
            (a.address +& byteCount) <= (axiAddressBase + axiWindowBytes).U((tlParams.addrWidth + 1).W)
        else true.B

    val acceptedWindow = if (localAddressRanges && tlParams.addrWidth > 12 && axiWindowBytes > 0 &&
        (axiAddressBase + axiWindowBytes) % 4096 == 0) {
        // TL size describes the WHOLE transfer: 2^size bytes, not the AXI
        // per-beat size. fitsBuffer bounds it to at most 256*8=2048 bytes.
        // For a page-aligned exclusive limit, only the final page needs an
        // offset+length sum. Keep arbitrary byte offsets (including malformed
        // requests) exact; natural-alignment assertions do not justify this gate.
        val lastPage = (axiAddressBase + axiWindowBytes) / 4096 - 1
        val addressPage = a.address(tlParams.addrWidth - 1, 12)
        val boundedBytes = byteCount(maxSize, 0)
        val localEnd = pageOffset +& boundedBytes
        fitsBuffer && a.address >= axiAddressBase.U &&
            (addressPage < lastPage.U || (addressPage === lastPage.U && localEnd <= 4096.U))
    } else inWindow && fitsBuffer

    io.tl.a.ready := state === sIdle || state === sCollectWrite
    when(io.tl.a.fire) {
        assert(a.param === 0.U && !a.corrupt && (isRead || isWrite), "unsupported TL-UL request")
        when(state === sIdle) {
            assert((a.address & (byteCount - 1.U)) === 0.U,
                "TL-AXI address must be naturally aligned")
            when(fitsBuffer) {
                assert(pageOffset +& byteCount <= 4096.U,
                    "AXI burst must not cross a 4-KiB boundary")
            }
            if (axiWindowBytes == 0 && axiAddressWidth < tlParams.addrWidth) {
                when(fitsBuffer) {
                    assert((a.address >> axiAddressWidth) === 0.U, "AXI address truncation")
                }
            }
            when(isBurst) {
                when(a.opcode =/= TLOpcode.PutPartialData) {
                    assert(a.mask === 255.U, "multi-beat Get/PutFullData require a full mask")
                }
            }.otherwise {
                when(a.opcode === TLOpcode.PutPartialData) {
                    assert((a.mask & ~fullMask) === 0.U, "TL partial mask outside access")
                }.otherwise {
                    assert(a.mask === fullMask, "TL full mask mismatch")
                }
            }
            address := a.address
            axiAddress := (a.address - axiAddressBase.U(tlParams.addrWidth.W))(axiAddressWidth - 1, 0)
            source := a.source
            size := a.size
            beatCount := requestBeats
            index := 0.U
            readError := !acceptedWindow
            writeError := !acceptedWindow
            writeAddressDone := false.B
            writeDataDone := false.B
            writeCaptured.foreach(_ := 1.U)
            writeSendIndex.foreach(_ := 0.U)
            when(isRead) {
                state := Mux(acceptedWindow, sReadAddress, sReadReply)
            }.otherwise {
                when(acceptedWindow) {
                    payloadWrite := true.B
                    payloadWriteIndex := 0.U
                }
                writeOpcode := a.opcode
                index := Mux(requestBeats === 1.U, 0.U, 1.U)
                state := Mux(requestBeats === 1.U,
                    Mux(acceptedWindow, sWriteAddress, sWriteReply), sCollectWrite)
            }
        }.otherwise {
            assert(state === sCollectWrite && a.opcode === writeOpcode &&
                a.param === 0.U && !a.corrupt && a.address === address &&
                a.size === size && a.source === source &&
                (writeOpcode === TLOpcode.PutPartialData || a.mask === 255.U),
                "TL write burst changed control fields")
            // Denied writes still own/drain every A beat but never touch the buffer or AXI.
            when(!writeError) {
                payloadWrite := true.B
                writeCaptured.foreach(count => count := count + 1.U)
            }
            index := index + 1.U
            when(index === beatCount - 1.U) {
                when(!writeError) { index := 0.U }
                state := Mux(writeError, sWriteReply, sWriteAddress)
            }
        }
    }

    val axiSize = Mux(size > 3.U, 3.U, size)
    io.axi.ar.valid := state === sReadAddress
    io.axi.aw.valid := writePhase && !writeAddressDone
    for (channel <- Seq(io.axi.ar.bits, io.axi.aw.bits)) {
        channel.id := 0.U
        channel.addr := axiAddress
        channel.len := beatCount - 1.U
        channel.size := axiSize
        channel.burst := 1.U // INCR
        channel.lock := false.B
        channel.cache := axiCache.U
        channel.prot := axiProt.U
        channel.qos := axiQos.U
    }
    when(io.axi.ar.fire) { index := 0.U; state := sReadData }
    when(io.axi.aw.fire) { writeAddressDone := true.B }

    io.axi.r.ready := state === sReadData
    when(io.axi.r.fire) {
        assert(io.axi.r.bits.id === 0.U &&
            io.axi.r.bits.last === (index === beatCount - 1.U),
            "AXI read ID or RLAST mismatch")
        payloadWrite := true.B
        payloadWriteData := Cat(0.U(8.W), io.axi.r.bits.data)
        readError := readError || io.axi.r.bits.resp(1)
        index := index + 1.U
        when(index === beatCount - 1.U) { index := 0.U; state := sReadReply }
    }
    // Neither VALID depends on the other channel's READY. In flow mode AW
    // may prepare the subordinate while A is still collecting, and W consumes
    // only previously captured beats. Producer gaps and either channel's
    // backpressure cannot withdraw an offered W or overwrite its memory word.
    io.axi.w.valid := writePhase && !writeDataDone &&
        (if (writeCollectionFlow) sendIndex < writeCaptured.get else true.B)
    io.axi.w.bits.data := payloadReadData
    io.axi.w.bits.strb := payloadRead(71, 64)
    io.axi.w.bits.last := sendIndex === beatCount - 1.U
    when(io.axi.w.fire) {
        when(io.axi.w.bits.last) { writeDataDone := true.B }
            .otherwise {
                if (writeCollectionFlow) writeSendIndex.get := sendIndex + 1.U
                else index := index + 1.U
            }
    }
    when(state === sWriteAddress && (writeAddressDone || io.axi.aw.fire) &&
        (writeDataDone || (io.axi.w.fire && io.axi.w.bits.last))) {
        state := sWriteResponse
    }
    io.axi.b.ready := state === sWriteResponse
    when(io.axi.b.fire) {
        assert(io.axi.b.bits.id === 0.U, "AXI write response ID mismatch")
        writeError := io.axi.b.bits.resp(1)
        state := sWriteReply
    }

    io.tl.d.valid := state === sReadReply || state === sWriteReply
    io.tl.d.bits := 0.U.asTypeOf(io.tl.d.bits)
    io.tl.d.bits.opcode := Mux(state === sReadReply, TLOpcode.AccessAckData, TLOpcode.AccessAck)
    io.tl.d.bits.source := source
    io.tl.d.bits.size := size
    io.tl.d.bits.denied := Mux(state === sReadReply, readError, writeError)
    io.tl.d.bits.corrupt := state === sReadReply && readError
    io.tl.d.bits.data := Mux(state === sReadReply && !readError, payloadReadData, 0.U)
    when(io.tl.d.fire) {
        index := index + 1.U
        val wholeLine = io.lineMode.getOrElse(false.B)
        when(wholeLine) {
            assert(state === sReadReply && size === 6.U && beatCount === 8.U && index === 0.U,
                "whole-line owner completed before a complete eight-beat read")
        }
        when(state === sWriteReply || index === beatCount - 1.U || wholeLine) { state := sIdle }
    }
    when(payloadWrite) {
        assert(!(io.tl.a.fire && io.axi.r.fire), "shared payload has two capture owners")
        assert(!io.tl.d.valid, "shared payload changed while TL reply was offered")
        if (writeCollectionFlow) {
            when(io.axi.w.valid) {
                assert(earlyWrite && io.tl.a.fire && payloadWriteIndex =/= payloadReadIndex,
                    "write capture overwrote a live AXI W word")
            }
            when(writePhase && !writeError) {
                assert(sendIndex < beatCount && writeCaptured.get <= beatCount &&
                    sendIndex <= writeCaptured.get, "write producer/consumer credit overflow")
            }
        } else {
            assert(!io.axi.w.valid, "shared payload changed while AXI W was offered")
        }
        if (lineReadChannel) {
            val row = if (maxBurstBeats == 8) 0.U else payloadWriteIndex >> 3
            // Preserve bank zero's original first/continuation/read control.
            // When enabled, the other banks are written below without the
            // first-beat acceptance/range cone, which can only select bank zero.
            val genericBanks = if (localPayloadWriteEnable) 0 until 1 else 0 until 8
            for (i <- genericBanks) {
                when(payloadWriteIndex(2, 0) === i.U) { payloadBanks(i).write(row, payloadWriteData) }
            }
        } else payload.get.write(payloadWriteIndex, payloadWriteData)
    }
    if (lineReadChannel && localPayloadWriteEnable) {
        // In these states READY is unconditional. The retained cursor covers
        // continuation/read captures; a first Put always overrides it to zero.
        // Do not use payloadWriteIndex for bank selection: its zero override
        // depends on the new request's acceptance and address-range checks.
        val continuedPayloadWrite = (state === sCollectWrite && io.tl.a.valid && !writeError) ||
            (state === sReadData && io.axi.r.valid)
        // continuedPayloadWrite implies collection or read state, disjoint from
        // idle first-Put acceptance. Thus the generic zero override is inactive
        // whenever these banks write. Localize only their row; keep DATA shared.
        val row = if (maxBurstBeats == 8) 0.U
            else if (localPayloadWriteRow) bufferIndex >> 3 else payloadWriteIndex >> 3
        for (i <- 1 until 8) {
            when(continuedPayloadWrite && bufferIndex(2, 0) === i.U) {
                payloadBanks(i).write(row, payloadWriteData)
            }
        }
    }
}
