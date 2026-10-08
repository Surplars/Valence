package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Single RX clock, bounded store-and-forward 1G/full-duplex native 32-bit frames.
  * PHY cannot be backpressured: when all frame banks are owned, drain and
  * drop new frames without touching them. Strip preamble/SFD/FCS, keep padding.
  * Check CRC residue, min/max length, RX_ER, basic L/T and destination address.
  * Config is snapshotted at frame start and must already be in this RX domain.
  * No VLAN tag removal, pause negotiation, multicast table, PHY or CDC here.
  */
class GmiiFrameRx(maxFrameBytes: Int = 2048, admissionStop: Boolean = false, frameSlots: Int = 4,
    rateAdaptation: Boolean = false, diagnostics: Boolean = false) extends Module {
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    require(frameSlots >= 1 && frameSlots <= 16 && isPow2(frameSlots))
    val io = IO(new Bundle {
        val gmiiData = Input(UInt(8.W))
        val gmiiValid = Input(Bool())
        val gmiiError = Input(Bool())
        val byteStep = if (rateAdaptation) Some(Input(Bool())) else None
        val abort = if (rateAdaptation) Some(Input(Bool())) else None
        // Mutually exclusive dropped-frame causes: bank full, admission closed,
        // preamble, FCS, length/LT, address, PHY error, link-transition abort.
        val dropReasons = if (diagnostics) Some(Output(UInt(8.W))) else None
        val enable = Input(Bool())
        val stopNewFrames = if (admissionStop) Some(Input(Bool())) else None
        val ownedBusy = if (admissionStop) Some(Output(Bool())) else None
        val promiscuous = Input(Bool())
        val broadcastEnable = Input(Bool())
        val macAddress = Input(UInt(48.W))
        val frame = Decoupled(new EthernetFrameBeat(4))
        val busy = Output(Bool())
        val accepted = Output(Bool())
        val dropped = Output(Bool())
        val badFcs = Output(Bool())
        val bytes = Output(UInt(16.W))
    })
    private val indexBits = log2Ceil(maxFrameBytes / 4)
    private val lengthBits = log2Ceil(maxFrameBytes + 5)
    private val slotBits = log2Ceil(frameSlots).max(1)
    val buffer = SyncReadMem(frameSlots * maxFrameBytes / 4, UInt(32.W))
    val producer = RegInit(0.U(slotBits.W))
    val consumer = RegInit(0.U(slotBits.W))
    val occupied = RegInit(0.U(log2Ceil(frameSlots + 1).W))
    val lengths = Reg(Vec(frameSlots, UInt(lengthBits.W)))
    val publish = WireDefault(false.B)
    val release = WireDefault(false.B)
    when(publish =/= release) { occupied := Mux(publish, occupied + 1.U, occupied - 1.U) }
    when(publish) { producer := (if (frameSlots == 1) 0.U else producer + 1.U) }
    when(release) { consumer := (if (frameSlots == 1) 0.U else consumer + 1.U) }
    assert(occupied <= frameSlots.U)
    assert(!release || occupied =/= 0.U)
    assert(!publish || occupied < frameSlots.U)
    // One physical write port: the full-word and EOF-tail cases are mutually
    // exclusive but separate memory.write calls create two FIRRTL write ports.
    // That plus the reader cannot map to a dual-port FPGA block RAM.
    val writeEnable = WireDefault(false.B)
    val writeIndex = WireDefault(0.U(indexBits.W))
    val writeWord = WireDefault(0.U(32.W))
    when(writeEnable) { buffer.write(if (frameSlots == 1) writeIndex else Cat(producer, writeIndex), writeWord) }
    val search :: preamble :: body :: drain :: Nil = Enum(4)
    // A reset in the middle of a physical frame must wait for DV=0, not search
    // for a coincidental 55/D5 pair in that frame's payload.
    val state = RegInit(drain)
    val reportDrop = RegInit(false.B)
    val reason = if (diagnostics) Some(RegInit(0.U(3.W))) else None
    val step = io.byteStep.getOrElse(true.B)
    val abort = io.abort.getOrElse(false.B)
    val preambleCount = RegInit(0.U(3.W))
    val crc = RegInit("hffffffff".U(32.W))
    val wireCount = RegInit(0.U(lengthBits.W))
    val tail = RegInit(0.U(32.W))
    val pack = RegInit(0.U(32.W))
    val errored = RegInit(false.B)
    val destination = RegInit(0.U(48.W))
    val typeLength = RegInit(0.U(16.W))
    val address = Reg(UInt(48.W))
    val promiscuous = RegInit(false.B)
    val broadcastEnable = RegInit(false.B)
    val idle :: load :: waitRead :: offer :: Nil = Enum(4)
    val outputState = RegInit(idle)
    val length = RegInit(0.U(lengthBits.W))
    val outputIndex = RegInit(0.U(indexBits.W))
    val outputWord = Reg(UInt(32.W))
    val outputRead = buffer.read(if (frameSlots == 1) outputIndex else Cat(consumer, outputIndex), outputState === load)
    when(outputState === idle && occupied =/= 0.U) {
        length := lengths(consumer)
        outputIndex := 0.U
        outputState := load
    }
    when(outputState === load) { outputState := waitRead }
    when(outputState === waitRead) { outputWord := outputRead; outputState := offer }
    val remaining = length - (outputIndex << 2)
    io.frame.valid := outputState === offer
    io.frame.bits.data := outputWord
    io.frame.bits.keep := Mux(remaining >= 4.U, 15.U,
        ((1.U(5.W) << remaining(1, 0)) - 1.U)(3, 0))
    io.frame.bits.last := remaining <= 4.U
    io.frame.bits.bad := false.B
    when(io.frame.fire) {
        when(io.frame.bits.last) { outputState := idle; release := true.B }
            .otherwise { outputIndex := outputIndex + 1.U; outputState := load }
    }
    io.busy := state =/= search || occupied =/= 0.U
    // Discarding an unadmitted physical frame owns no payload. Its endless
    // arrival must not prevent a requested shutdown from becoming quiescent.
    io.ownedBusy.foreach(_ := state === preamble || state === body || occupied =/= 0.U)
    io.accepted := false.B
    io.dropped := false.B
    io.badFcs := false.B
    io.dropReasons.foreach(_ := 0.U)
    def dropReason(code: UInt): Unit = io.dropReasons.foreach(_ := UIntToOH(code, 8))
    val bodyBytes = wireCount - 4.U
    io.bytes := bodyBytes
    when(state === search && io.gmiiValid && step) {
        reportDrop := true.B
        address := io.macAddress
        promiscuous := io.promiscuous
        broadcastEnable := io.broadcastEnable
        errored := io.gmiiError
        reason.foreach(_ := Mux(!io.enable || io.stopNewFrames.getOrElse(false.B), 1.U,
            Mux(occupied === frameSlots.U, 0.U, 2.U)))
        when(io.enable && !io.stopNewFrames.getOrElse(false.B) && occupied < frameSlots.U && io.gmiiData === "h55".U) {
            preambleCount := 1.U
            state := preamble
        }.otherwise { state := drain }
    }
    when(state === preamble && step) {
        errored := errored || io.gmiiError
        when(!io.gmiiValid) { state := search; io.dropped := true.B; dropReason(2.U) }
            .elsewhen(io.gmiiData === "h55".U) {
                when(preambleCount < 7.U) { preambleCount := preambleCount + 1.U }
            }.elsewhen(io.gmiiData === "hd5".U && preambleCount =/= 0.U) {
                state := body
                wireCount := 0.U
                crc := "hffffffff".U
                tail := 0.U
                pack := 0.U
                destination := 0.U
                typeLength := 0.U
            }.otherwise { state := drain }
    }
    when(state === body && step) {
        when(io.gmiiValid) {
            crc := EthernetCrc32.update(crc, io.gmiiData, 1)
            errored := errored || io.gmiiError
            wireCount := wireCount + 1.U
            tail := Cat(io.gmiiData, tail(31, 8))
            when(wireCount < 6.U) { destination := Cat(destination(39, 0), io.gmiiData) }
            when(wireCount === 12.U || wireCount === 13.U) {
                typeLength := Cat(typeLength(7, 0), io.gmiiData)
            }
            // Four-byte tail delay excludes FCS from the packet RAM. The word
            // packer writes once per four bytes; partial final word at EOF.
            when(wireCount >= 4.U && wireCount < (maxFrameBytes + 4).U) {
                val bodyIndex = wireCount - 4.U
                val packed = pack | (tail(7, 0) << Cat(bodyIndex(1, 0), 0.U(3.W)))
                when(bodyIndex(1, 0) === 3.U) {
                    writeEnable := true.B
                    writeIndex := (bodyIndex >> 2)(indexBits - 1, 0)
                    writeWord := packed
                    pack := 0.U
                }.otherwise { pack := packed }
            }
            when(wireCount === (maxFrameBytes + 4).U) { state := drain; reason.foreach(_ := 4.U) }
        }.otherwise {
            val crcGood = crc === "hdebb20e3".U
            val lengthGood = wireCount >= 64.U && wireCount <= (maxFrameBytes + 4).U
            val expectedBody = Mux(typeLength +& 14.U < 60.U, 60.U, typeLength +& 14.U)
            val ltGood = typeLength >= 1536.U || (typeLength <= 1500.U && bodyBytes === expectedBody)
            val addressGood = promiscuous || destination === address ||
                (broadcastEnable && destination.andR)
            val good = crcGood && lengthGood && ltGood && addressGood && !errored
            io.badFcs := !crcGood
            io.dropped := !good
            io.accepted := good
            when(!good) {
                dropReason(Mux(errored, 6.U, Mux(!crcGood, 3.U,
                    Mux(!lengthGood || !ltGood, 4.U, 5.U))))
            }
            when(good) {
                when(bodyBytes(1, 0) =/= 0.U) {
                    writeEnable := true.B
                    writeIndex := (bodyBytes >> 2)(indexBits - 1, 0)
                    writeWord := pack
                }
                lengths(producer) := bodyBytes
                publish := true.B
            }
            state := search
        }
    }
    when(state === drain && !io.gmiiValid && step) {
        state := search
        io.dropped := reportDrop
        reportDrop := false.B
        when(reportDrop) { dropReason(reason.getOrElse(0.U)) }
    }
    if (rateAdaptation) {
        // Keep all complete packet banks/output ownership intact on link loss.
        // The parser drains the physical tail and cannot search for a false SFD.
        when(abort && (state === preamble || state === body)) {
            state := drain
            reportDrop := true.B
            reason.foreach(_ := 7.U)
            io.accepted := false.B
            io.dropped := false.B
            io.badFcs := false.B
            io.dropReasons.foreach(_ := 0.U)
            publish := false.B
            writeEnable := false.B
        }
    }
}
