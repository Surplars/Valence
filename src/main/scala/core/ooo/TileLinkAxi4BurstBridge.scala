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
    tlParams: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    axiAddressWidth: Int = 64,
    axiIdWidth: Int = 1,
    maxBurstBeats: Int = 16,
    axiCache: Int = 0,
    axiProt: Int = 0,
    axiQos: Int = 0,
    axiAddressBase: BigInt = 0,
    axiWindowBytes: BigInt = 0
) extends Module {
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
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
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
    val payload = Mem(maxBurstBeats, UInt(72.W))
    val payloadWrite = WireDefault(false.B)
    val payloadWriteIndex = WireDefault(bufferIndex)
    val payloadWriteData = WireDefault(Cat(io.tl.a.bits.mask, io.tl.a.bits.data))
    // Capture and playback cannot overlap within this lane. Rewind the same
    // cursor after the final R beat instead of adding an address mux before
    // the asynchronous memory read or retaining a second counter/adder.
    val payloadRead = payload.read(bufferIndex)
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

    val acceptedWindow = inWindow && fitsBuffer

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
    io.axi.aw.valid := state === sWriteAddress && !writeAddressDone
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
    // Neither VALID depends on the other channel's READY. A complete TL
    // burst is buffered before either independent AXI channel is offered.
    io.axi.w.valid := state === sWriteAddress && !writeDataDone
    io.axi.w.bits.data := payloadReadData
    io.axi.w.bits.strb := payloadRead(71, 64)
    io.axi.w.bits.last := index === beatCount - 1.U
    when(io.axi.w.fire) {
        when(io.axi.w.bits.last) { writeDataDone := true.B }
            .otherwise { index := index + 1.U }
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
        when(state === sWriteReply || index === beatCount - 1.U) { state := sIdle }
    }
    when(payloadWrite) {
        assert(!(io.tl.a.fire && io.axi.r.fire), "shared payload has two capture owners")
        assert(!io.axi.w.valid && !io.tl.d.valid, "shared payload changed while being offered")
        payload.write(payloadWriteIndex, payloadWriteData)
    }
}
