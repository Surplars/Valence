package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Single RX clock, store-and-forward 1G/full-duplex native 32-bit frames.
  * PHY cannot be backpressured: while the one frame buffer is owned, drain and
  * drop new frames without touching it. Strip preamble/SFD/FCS, keep padding.
  * Check CRC residue, min/max length, RX_ER, basic L/T and destination address.
  * Config is snapshotted at frame start and must already be in this RX domain.
  * No VLAN tag removal, pause negotiation, multicast table, PHY or CDC here.
  */
class GmiiFrameRx(maxFrameBytes: Int = 2048) extends Module {
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    val io = IO(new Bundle {
        val gmiiData = Input(UInt(8.W))
        val gmiiValid = Input(Bool())
        val gmiiError = Input(Bool())
        val enable = Input(Bool())
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
    val buffer = SyncReadMem(maxFrameBytes / 4, UInt(32.W))
    // One physical write port: the full-word and EOF-tail cases are mutually
    // exclusive but separate memory.write calls create two FIRRTL write ports.
    // That plus the reader cannot map to a dual-port FPGA block RAM.
    val writeEnable = WireDefault(false.B)
    val writeIndex = WireDefault(0.U(indexBits.W))
    val writeWord = WireDefault(0.U(32.W))
    when(writeEnable) { buffer.write(writeIndex, writeWord) }
    val search :: preamble :: body :: drain :: Nil = Enum(4)
    // A reset in the middle of a physical frame must wait for DV=0, not search
    // for a coincidental 55/D5 pair in that frame's payload.
    val state = RegInit(drain)
    val reportDrop = RegInit(false.B)
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
    val outputRead = buffer.read(outputIndex, outputState === load)
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
        when(io.frame.bits.last) { outputState := idle }
            .otherwise { outputIndex := outputIndex + 1.U; outputState := load }
    }
    io.busy := state =/= search || outputState =/= idle
    io.accepted := false.B
    io.dropped := false.B
    io.badFcs := false.B
    val bodyBytes = wireCount - 4.U
    io.bytes := bodyBytes
    when(state === search && io.gmiiValid) {
        reportDrop := true.B
        address := io.macAddress
        promiscuous := io.promiscuous
        broadcastEnable := io.broadcastEnable
        errored := io.gmiiError
        when(io.enable && outputState === idle && io.gmiiData === "h55".U) {
            preambleCount := 1.U
            state := preamble
        }.otherwise { state := drain }
    }
    when(state === preamble) {
        errored := errored || io.gmiiError
        when(!io.gmiiValid) { state := search; io.dropped := true.B }
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
    when(state === body) {
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
            when(wireCount === (maxFrameBytes + 4).U) { state := drain }
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
            when(good) {
                when(bodyBytes(1, 0) =/= 0.U) {
                    writeEnable := true.B
                    writeIndex := (bodyBytes >> 2)(indexBits - 1, 0)
                    writeWord := pack
                }
                length := bodyBytes
                outputIndex := 0.U
                outputState := load
            }
            state := search
        }
    }
    when(state === drain && !io.gmiiValid) {
        state := search
        io.dropped := reportDrop
        reportDrop := false.B
    }
}
