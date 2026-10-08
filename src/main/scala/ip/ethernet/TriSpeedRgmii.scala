package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** RGMII speed encoding, matching Clause 22 RTL8211F PHYSR and RGMII idle status.
  * Half duplex, pause, EEE and the reserved encoding are deliberately unsupported.
  */
object EthernetSpeed {
    val Mbps10 = 0
    val Mbps100 = 1
    val Mbps1000 = 2
    def legal(speed: UInt): Bool = speed <= Mbps1000.U
}

/** Byte-rate adapter plus DDR symbol generation on ONE continuous 125 MHz clock.
  * The forwarded PHY clock is DATA to an ODDR, never an internally used fabric
  * clock. At 10/100 each nibble is repeated on both RGMII edges. Clock periods
  * are 50/5 reference cycles; odd divide-by-five uses different D1/D2 values
  * for an exact 20 ns high and 20 ns low. MAC byteStep is 1/100, 1/10, or 1/1.
  *
  * All six DDR symbol pairs share this registered boundary. Physical skew must
  * be supplied by the dedicated clock-output delay in native_rgmii_trispeed.
  * A speed command is acknowledged only at an idle complete-byte boundary.
  */
class TriSpeedRgmiiTx extends Module {
    val io = IO(new Bundle {
        val rate = Flipped(Decoupled(UInt(2.W)))
        val datapathIdle = Input(Bool())
        val appliedSpeed = Output(UInt(2.W))
        val byteStep = Output(Bool())
        val gmiiData = Input(UInt(8.W))
        val gmiiEnable = Input(Bool())
        val gmiiError = Input(Bool())
        val rise = Output(UInt(5.W))
        val fall = Output(UInt(5.W))
        val clockRise = Output(Bool())
        val clockFall = Output(Bool())
        val idle = Output(Bool())
    })
    val speed = RegInit(EthernetSpeed.Mbps1000.U(2.W))
    val phase = RegInit(0.U(7.W))
    val heldData = RegInit(0.U(8.W))
    val heldEnable = RegInit(false.B)
    val heldError = RegInit(false.B)
    val rateGap = RegInit(0.U(4.W))
    val byteStart = phase === 0.U
    io.appliedSpeed := speed
    io.byteStep := byteStart && rateGap === 0.U
    io.idle := !heldEnable && !io.gmiiEnable
    io.rate.ready := io.datapathIdle && io.idle && byteStart && EthernetSpeed.legal(io.rate.bits)
    // Start the FIRST new complete period on the command-accepting edge. Do
    // not emit one extra old phase-zero symbol (which would shorten a pulse).
    val symbolSpeed = Mux(io.rate.fire, io.rate.bits, speed)
    val gigabit = symbolSpeed === EthernetSpeed.Mbps1000.U
    val hundred = symbolSpeed === EthernetSpeed.Mbps100.U
    val lastPhase = Mux(gigabit, 0.U, Mux(hundred, 9.U, 99.U))
    when(io.rate.fire) { speed := io.rate.bits; phase := Mux(gigabit, 0.U, 1.U); rateGap := 12.U }
        .otherwise { phase := Mux(phase === lastPhase, 0.U, phase + 1.U) }
    when(!io.rate.fire && byteStart && rateGap =/= 0.U) { rateGap := rateGap - 1.U }
    when(byteStart) {
        heldData := io.gmiiData
        heldEnable := io.gmiiEnable && rateGap === 0.U
        heldError := io.gmiiError
    }
    val data = Mux(byteStart, io.gmiiData, heldData)
    val enable = Mux(byteStart, io.gmiiEnable && rateGap === 0.U, heldEnable)
    val error = Mux(byteStart, io.gmiiError, heldError)
    val highNibble = Mux(hundred, phase >= 5.U, phase >= 50.U)
    val nibblePhase = Mux(highNibble, phase - Mux(hundred, 5.U, 50.U), phase)
    val clockRise = gigabit || Mux(hundred, nibblePhase < 3.U, nibblePhase < 25.U)
    val clockFall = !gigabit && Mux(hundred, nibblePhase < 2.U, nibblePhase < 25.U)
    val nibble = Mux(highNibble, data(7, 4), data(3, 0))
    val riseControl = Mux(clockRise, enable, enable ^ error)
    val fallControl = Mux(clockFall, enable, enable ^ error)
    io.rise := RegNext(Cat(riseControl, Mux(gigabit, data(3, 0), nibble)), 0.U)
    io.fall := RegNext(Cat(fallControl, Mux(gigabit, data(7, 4), nibble)), 0.U)
    io.clockRise := RegNext(clockRise, false.B)
    io.clockFall := RegNext(clockFall, false.B)
    assert(phase <= lastPhase || io.rate.fire, "RGMII byte phase escaped selected rate")
    when(io.rate.fire) { assert(!io.gmiiEnable && !heldEnable, "RGMII speed changed in an owned byte") }
}

/** Recovered-clock RGMII decoder after SAME_EDGE_PIPELINED IDDRs.
  * At 1G one edge-pair is one byte. At 10/100 only the rising data nibble
  * is significant; the falling data nibble is not used as a second byte half.
  * Control is still DDR at every speed: RX_DV on rise, RX_DV xor RX_ER on fall.
  * A byteStep=0 cycle is NOT an idle byte and must not terminate a frame.
  * Odd-nibble tails become a synthetic errored byte followed by explicit idle,
  * ensuring the packet engine rejects them instead of accepting a truncated FCS.
  * abort flushes only the partial physical byte, never a retained packet bank.
  */
class TriSpeedRgmiiRx extends Module {
    val io = IO(new Bundle {
        val rate = Flipped(Decoupled(UInt(2.W)))
        val admissionClosed = Input(Bool())
        val abort = Input(Bool())
        val rise = Input(UInt(5.W))
        val fall = Input(UInt(5.W))
        val appliedSpeed = Output(UInt(2.W))
        val byteStep = Output(Bool())
        val gmiiData = Output(UInt(8.W))
        val gmiiValid = Output(Bool())
        val gmiiError = Output(Bool())
        val physicalIdle = Output(Bool())
        val oddNibble = Output(Bool())
        val inbandValid = Output(Bool())
        val inbandStatus = Output(UInt(4.W))
    })
    val speed = RegInit(EthernetSpeed.Mbps1000.U(2.W))
    val half = RegInit(false.B)
    val low = RegInit(0.U(4.W))
    val lowError = RegInit(false.B)
    val valid = io.rise(4)
    val error = io.rise(4) ^ io.fall(4)
    val gigabit = speed === EthernetSpeed.Mbps1000.U
    io.appliedSpeed := speed
    io.physicalIdle := !valid && !half
    // Admission must be closed externally before applying a rate. A frame in
    // progress is being discarded; no fabricated physical idle is required.
    io.rate.ready := io.admissionClosed && EthernetSpeed.legal(io.rate.bits)
    io.inbandValid := !io.rise(4) && !io.fall(4) && io.rise(3, 0) === io.fall(3, 0)
    io.inbandStatus := io.rise(3, 0)
    io.byteStep := true.B
    io.gmiiData := Cat(io.fall(3, 0), io.rise(3, 0))
    io.gmiiValid := valid
    io.gmiiError := error
    io.oddNibble := false.B
    when(!gigabit) {
        io.gmiiData := Cat(io.rise(3, 0), low)
        io.gmiiValid := valid && half
        io.gmiiError := error || lowError
        io.byteStep := !valid || half
        when(valid) {
            half := !half
            when(!half) { low := io.rise(3, 0); lowError := error }
        }.otherwise {
            half := false.B
            when(half) {
                io.gmiiValid := true.B
                io.gmiiError := true.B
                io.oddNibble := true.B
            }
        }
    }.otherwise { half := false.B }
    when(io.abort || io.rate.fire) {
        half := false.B
        lowError := false.B
        io.byteStep := true.B
        io.gmiiValid := false.B
        io.gmiiError := false.B
        io.oddNibble := false.B
    }
    when(io.rate.fire) { speed := io.rate.bits }
}
