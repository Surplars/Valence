package soc.ip.ethernet

import chisel3._
import chisel3.util._

sealed trait EthernetPortKind {
    def capabilityBit: Int
    def mediaBits: Int
    def mediaClockHz: Long
}
case object Rgmii1G extends EthernetPortKind {
    val capabilityBit = 0
    val mediaBits = 8
    val mediaClockHz = 125000000L
}
/** Architecture contract only: does not instantiate or claim a working 10G MAC/PCS. */
case object Xgmii10G extends EthernetPortKind {
    val capabilityBit = 1
    val mediaBits = 64
    val mediaClockHz = 156250000L
}

case class GmacParams(
    base: BigInt = BigInt("10040000", 16),
    ports: Seq[EthernetPortKind] = Seq(Rgmii1G),
    maxFrameBytes: Int = 2048,
    controlClockHz: Int = 100000000,
    mdcHz: Int = 2500000,
    aggregateStats: Boolean = false,
    rxAdmissionStop: Boolean = false
) {
    require(base >= 0 && base % 4096 == 0 && ports.nonEmpty && ports.size <= 4)
    require(base + ports.size * 4096 <= (BigInt(1) << 64))
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    require(controlClockHz > 0 && mdcHz > 0 && mdcHz <= 2500000 &&
        controlClockHz.toLong >= 4L * mdcHz)
}

/** Packet boundary excludes preamble/SFD/FCS; first frame byte is the lowest lane.
  * A non-final beat has all lanes valid; final keep is a nonzero low prefix.
  * Bad-frame indication is meaningful on the final beat. MAC RX must drop a
  * complete frame on overflow: the PHY cannot be backpressured.
  */
class EthernetFrameBeat(bytes: Int = 8) extends Bundle {
    require(bytes >= 1 && bytes <= 8 && isPow2(bytes))
    val data = UInt((8 * bytes).W)
    val keep = UInt(bytes.W)
    val last = Bool()
    val bad = Bool()
}

/** All fields below are in the control clock domain; integrations must cross
  * MAC events/status explicitly and preserve pulses/counters. Never wire raw
  * RGMII/XGMII levels here. No CPU implementation types are used by this IP.
  */
class GmacPortControl(aggregateStats: Boolean = false, rxAdmissionStop: Boolean = false) extends Bundle {
    val txEnable = Output(Bool())
    val rxEnable = Output(Bool())
    val promiscuous = Output(Bool())
    val broadcastEnable = Output(Bool())
    val macAddress = Output(UInt(48.W))
    val linkUp = Input(Bool())
    val txBusy = Input(Bool())
    val rxBusy = Input(Bool())
    // Optional additive shutdown barrier; admission only, never a frame reset.
    val rxStopRequest = if (rxAdmissionStop) Some(Output(Bool())) else None
    val rxStopDrained = if (rxAdmissionStop) Some(Input(Bool())) else None
    // tx-complete, rx-complete, rx-drop, rx-bad-fcs, tx-underflow, link-change.
    val events = Input(UInt(6.W))
    val txBytes = Input(UInt(16.W))
    val rxBytes = Input(UInt(16.W))
    // Atomic control-domain delta snapshots: tx frames, rx frames, drops,
    // bad FCS, TX bytes, RX bytes. Modulo32 source deltas accumulate into64.
    val deltas = if (aggregateStats) Some(Input(Vec(6, UInt(32.W)))) else None
    val mdc = Output(Bool())
    val mdioIn = Input(Bool())
    val mdioOut = Output(Bool())
    val mdioOe = Output(Bool())
}
