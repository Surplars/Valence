// Independent I1 bus adapter, copied from TileLinkAxi4BurstBridge.scala; no CPU/OoO state/control.
package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.axi._

/** TL-UL Get/Put to an AXI4 INCR memory or register window.
  * One complete TL transaction is owned at a time. This bounds buffering and
  * preserves TL ordering across reads, writes, and AXI error responses.
  * AXI IDs are fixed at zero; no coherent, atomic, or exclusive operations.
  */
class I1TileLinkAxi4BurstBridge(
    tlParams: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    axiAddressWidth: Int = 64,
    axiIdWidth: Int = 1,
    maxBurstBeats: Int = 16,
    axiCache: Int = 0,
    axiProt: Int = 0,
    axiQos: Int = 0,
    axiAddressBase: BigInt = 0,
    axiWindowBytes: BigInt = 0,
    writeCollectionFlow: Boolean = false,
    lineReadChannel: Boolean = false,
    parallelAdmission: Boolean = false
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
    require(axiWindowBytes > 0 && axiWindowBytes % (maxBurstBeats * 8) == 0,
        "I1 aligned-window proof requires whole maximum-message boundaries")
    require(!writeCollectionFlow || axiWindowBytes > 0,
        "write collection flow requires an explicit ordinary RAM window")
    require(!lineReadChannel || (axiWindowBytes > 0 && maxBurstBeats >= 8),
        "whole-line playback requires a bounded RAM window and at least eight beats")
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(tlParams))
        val axi = new Axi4MemoryPort(axiAddressWidth, axiIdWidth)
        val lineData = if (lineReadChannel) Some(Output(UInt(512.W))) else None
        val lineMode = if (lineReadChannel) Some(Input(Bool())) else None
        // Raw ordinary A bytes, independent of line/allocation arbitration.
        // An idle lane may prepare its otherwise UNOWNED first word. Only
        // real A acceptance grants a slot/credit or allows AXI side effects.
        val writePayload = if (lineReadChannel) Some(Flipped(Valid(UInt(72.W)))) else None
        // Pure preflight of the raw contenders, before parent hazard/selection.
        // Not an owner, permission credit, early ACK or additional pipeline edge.
        val admissionWindow = if (parallelAdmission) Some(Input(Bool())) else None
        val admissionAxiAddress = if (parallelAdmission) Some(Input(UInt(axiAddressWidth.W))) else None
        val admissionPhases = if (parallelAdmission) Some(Input(UInt(5.W))) else None
    })
    io.tl.b.valid := false.B
    io.tl.b.bits := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    assert(!io.tl.c.valid && !io.tl.e.valid, "TL-AXI boundary does not support coherence")

    val Seq(sIdle, sCollectWrite, sReadAddress, sReadData, sReadReply,
        sWriteAddress, sWriteData, sWriteResponse, sWriteReply) =
        if (parallelAdmission) (0 until 9).map(i => (BigInt(1) << i).U(9.W)) else Enum(9)
    val state = RegInit(sIdle)
    val nextState = WireDefault(state)
    private def in(phase: UInt): Bool =
        if (parallelAdmission) state(phase.litValue.bitLength - 1) else state === phase
    val address = Reg(UInt(tlParams.addrWidth.W))
    // Translate on acceptance, before any narrowing. Keep the physical address
    // separately for TL multi-beat consistency checks.
    val axiAddress = Reg(UInt(axiAddressWidth.W))
    val source = Reg(UInt(tlParams.sourceBits.W))
    val size = Reg(UInt(tlParams.sizeBits.W))
    val countWidth = I1TileLinkTransferBeatCount.width(tlParams)
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
    // Payload selection belongs to the REGISTERED lane phase, not R.fire.
    // READY/ID/AR forwarding still qualify the write enable, but no longer
    // travel through the 72-bit RAM data mux. An invalid R offer has no write.
    val payloadWriteData = Mux(in(sReadData),
        Cat(0.U(8.W), io.axi.r.bits.data),
        io.writePayload.map(_.bits).getOrElse(Cat(io.tl.a.bits.mask, io.tl.a.bits.data)))
    if (lineReadChannel) {
        when(in(sIdle) && io.writePayload.get.valid) {
            payloadWrite := true.B
            payloadWriteIndex := 0.U
        }
        when(in(sCollectWrite)) {
            // The sole collecting lane is already an authorized owner.
            // Its local READY is unconditional; raw producer presence must
            // equal the real continuation transfer, not a new allocation.
            assert(io.writePayload.get.valid === io.tl.a.fire,
                "prepared write continuation lost its real accepted owner")
            when(io.writePayload.get.valid && !writeError) { payloadWrite := true.B }
        }
    }
    // Default lanes still share one capture/playback cursor. The opt-in write
    // path gives the consumer its own cursor and uses registered capture
    // credits: no W beat can see a same-edge A write or an uninitialized word.
    // Capacity and the single memory write/read ports are unchanged.
    val writeCaptured = if (writeCollectionFlow) Some(RegInit(0.U(countWidth.W))) else None
    val writeSendIndex = if (writeCollectionFlow) Some(RegInit(0.U(countWidth.W))) else None
    val earlyWrite = if (writeCollectionFlow) in(sCollectWrite) && !writeError else false.B
    val writePhase = in(sWriteAddress) || earlyWrite
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
    val requestBeats = I1TileLinkTransferBeatCount(a.size, tlParams)
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
    // Natural alignment is asserted at acceptance. Both window boundaries
    // are aligned to every supported message size, so checking the start
    // proves the whole message fits. Oversized sizes still fail fitsBuffer.
    // Do not add a 65-bit end address before selecting the next state.
    val inWindow = I1AddressWindow.contains(a.address, axiAddressBase, axiWindowBytes)

    val acceptedWindow = io.admissionWindow.getOrElse(inWindow) && fitsBuffer

    io.tl.a.ready := in(sIdle) || in(sCollectWrite)
    when(io.tl.a.fire) {
        assert(a.param === 0.U && !a.corrupt && (isRead || isWrite), "unsupported TL-UL request")
        when(in(sIdle)) {
            io.admissionWindow.foreach { proof =>
                assert(proof === inWindow, "parallel window preflight differs from accepted physical owner")
                assert(io.admissionAxiAddress.get ===
                    (a.address - axiAddressBase.U(tlParams.addrWidth.W))(axiAddressWidth - 1, 0),
                    "parallel AXI address preparation differs from accepted physical owner")
            }
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
            axiAddress := io.admissionAxiAddress.getOrElse(
                (a.address - axiAddressBase.U(tlParams.addrWidth.W))(axiAddressWidth - 1, 0))
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
                nextState := Mux(acceptedWindow, sReadAddress, sReadReply)
            }.otherwise {
                when(acceptedWindow) {
                    if (lineReadChannel) {
                        assert(io.writePayload.get.valid &&
                            io.writePayload.get.bits === Cat(a.mask, a.data),
                            "prepared first write differs from its accepted TL owner")
                    } else {
                        payloadWrite := true.B
                        payloadWriteIndex := 0.U
                    }
                }
                writeOpcode := a.opcode
                index := Mux(requestBeats === 1.U, 0.U, 1.U)
                nextState := Mux(requestBeats === 1.U,
                    Mux(acceptedWindow, sWriteAddress, sWriteReply), sCollectWrite)
            }
        }.otherwise {
            assert(in(sCollectWrite) && a.opcode === writeOpcode &&
                a.param === 0.U && !a.corrupt && a.address === address &&
                a.size === size && a.source === source &&
                (writeOpcode === TLOpcode.PutPartialData || a.mask === 255.U),
                "TL write burst changed control fields")
            // Denied writes own/drain every A beat and emit no AXI. Any
            // unowned idle staging word is not a committed producer credit.
            when(!writeError) {
                if (!lineReadChannel) payloadWrite := true.B
                writeCaptured.foreach(count => count := count + 1.U)
            }
            index := index + 1.U
            when(index === beatCount - 1.U) {
                when(!writeError) { index := 0.U }
                nextState := Mux(writeError, sWriteReply, sWriteAddress)
            }
        }
    }

    val axiSize = Mux(size > 3.U, 3.U, size)
    io.axi.ar.valid := in(sReadAddress)
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
    when(io.axi.ar.fire) { index := 0.U; nextState := sReadData }
    when(io.axi.aw.fire) { writeAddressDone := true.B }

    io.axi.r.ready := in(sReadData)
    when(io.axi.r.fire) {
        assert(io.axi.r.bits.id === 0.U &&
            io.axi.r.bits.last === (index === beatCount - 1.U),
            "AXI read ID or RLAST mismatch")
        payloadWrite := true.B
        readError := readError || io.axi.r.bits.resp(1)
        index := index + 1.U
        when(index === beatCount - 1.U) { index := 0.U; nextState := sReadReply }
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
    when(in(sWriteAddress) && (writeAddressDone || io.axi.aw.fire) &&
        (writeDataDone || (io.axi.w.fire && io.axi.w.bits.last))) {
        nextState := sWriteResponse
    }
    io.axi.b.ready := in(sWriteResponse)
    when(io.axi.b.fire) {
        assert(io.axi.b.bits.id === 0.U, "AXI write response ID mismatch")
        writeError := io.axi.b.bits.resp(1)
        nextState := sWriteReply
    }

    io.tl.d.valid := in(sReadReply) || in(sWriteReply)
    io.tl.d.bits := 0.U.asTypeOf(io.tl.d.bits)
    io.tl.d.bits.opcode := Mux(in(sReadReply), TLOpcode.AccessAckData, TLOpcode.AccessAck)
    io.tl.d.bits.source := source
    io.tl.d.bits.size := size
    io.tl.d.bits.denied := Mux(in(sReadReply), readError, writeError)
    io.tl.d.bits.corrupt := in(sReadReply) && readError
    io.tl.d.bits.data := Mux(in(sReadReply) && !readError, payloadReadData, 0.U)
    when(io.tl.d.fire) {
        index := index + 1.U
        val wholeLine = io.lineMode.getOrElse(false.B)
        when(wholeLine) {
            assert(in(sReadReply) && size === 6.U && beatCount === 8.U && index === 0.U,
                "whole-line owner completed before a complete eight-beat read")
        }
        when(in(sWriteReply) || index === beatCount - 1.U || wholeLine) { nextState := sIdle }
    }
    if (parallelAdmission) {
        // No late shared binary encoder/CE after parent allocation/hazard.
        // Each phase owns only its local hold and incoming transitions. The
        // old transition program above remains an exact every-cycle oracle.
        val first = in(sIdle) && io.tl.a.valid
        val lastCollected = in(sCollectWrite) && io.tl.a.valid && index === beatCount - 1.U
        val lastRead = in(sReadData) && io.axi.r.valid && index === beatCount - 1.U
        val readRetired = io.tl.d.ready &&
            (index === beatCount - 1.U || io.lineMode.getOrElse(false.B))
        val writeIssued = (writeAddressDone || io.axi.aw.fire) &&
            (writeDataDone || (io.axi.w.fire && io.axi.w.bits.last))
        val local = VecInit(Seq(
            (in(sIdle) && !io.tl.a.valid) ||
                (in(sReadReply) && readRetired) || (in(sWriteReply) && io.tl.d.ready),
            (first && io.admissionPhases.get(0)) ||
                (in(sCollectWrite) && !lastCollected),
            (first && io.admissionPhases.get(1)) ||
                (in(sReadAddress) && !io.axi.ar.ready),
            (in(sReadAddress) && io.axi.ar.ready) || (in(sReadData) && !lastRead),
            (first && io.admissionPhases.get(2)) || lastRead ||
                (in(sReadReply) && !readRetired),
            (first && io.admissionPhases.get(3)) ||
                (lastCollected && !writeError) || (in(sWriteAddress) && !writeIssued),
            false.B,
            (in(sWriteAddress) && writeIssued) ||
                (in(sWriteResponse) && !io.axi.b.valid),
            (first && io.admissionPhases.get(4)) ||
                (lastCollected && writeError) || (in(sWriteResponse) && io.axi.b.valid) ||
                (in(sWriteReply) && !io.tl.d.ready)))
        state := local.asUInt
        when(!reset.asBool) {
            assert(PopCount(state) === 1.U && local.asUInt === nextState,
                "local bridge phase changed the exact accepted slot transition")
        }
    } else { state := nextState }
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
            // A first prepared Put can only target bank0. Localize the
            // remaining seven banks below so neither first-A eligibility nor
            // its zero-index override precedes their write-enable/row pins.
            val genericBanks = if (parallelAdmission) 0 until 1 else 0 until 8
            for (i <- genericBanks) {
                when(payloadWriteIndex(2, 0) === i.U) { payloadBanks(i).write(row, payloadWriteData) }
            }
        } else payload.get.write(payloadWriteIndex, payloadWriteData)
    }
    if (lineReadChannel && parallelAdmission) {
        // Ported from dev's local upper-bank control, adapted to the I1 raw
        // write-payload handoff and one-hot phases. Both local READYs are
        // unconditional here; VALID is therefore the genuine capture edge.
        val continuedWrite = (in(sCollectWrite) && io.writePayload.get.valid && !writeError) ||
            (in(sReadData) && io.axi.r.valid)
        val row = if (maxBurstBeats == 8) 0.U else bufferIndex >> 3
        for (i <- 1 until 8) {
            val enabled = continuedWrite && bufferIndex(2, 0) === i.U
            when(enabled) { payloadBanks(i).write(row, payloadWriteData) }
            when(!reset.asBool) {
                assert(enabled === (payloadWrite && payloadWriteIndex(2, 0) === i.U),
                    "localized AXI payload bank changed an actual capture edge")
                when(enabled) {
                    assert(row === (if (maxBurstBeats == 8) 0.U else payloadWriteIndex >> 3),
                        "localized AXI payload bank changed its owned row")
                }
            }
        }
    }

}
