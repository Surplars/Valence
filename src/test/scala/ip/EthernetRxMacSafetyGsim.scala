package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._
import soc.ip.bus.RegisterPort
import soc.ip.dma.EthernetPacketDma

/** Single-clock functional wrapper only, never a physical multi-clock MAC top. */
class EthernetRxMacSafetyGsim(readPrefetch: Boolean) extends Module {
    val io = IO(new Bundle {
        val txFrame = Flipped(Decoupled(new EthernetFrameBeat(4)))
        val rxFrame = Decoupled(new EthernetFrameBeat(4))
        val txEnable = Input(Bool())
        val rxEnable = Input(Bool())
        val promiscuous = Input(Bool())
        val broadcastEnable = Input(Bool())
        val macAddress = Input(UInt(48.W))
        val gmiiTxData = Output(UInt(8.W))
        val gmiiTxEnable = Output(Bool())
        val gmiiTxError = Output(Bool())
        val gmiiRxData = Input(UInt(8.W))
        val gmiiRxValid = Input(Bool())
        val gmiiRxError = Input(Bool())
        val txBusy = Output(Bool())
        val rxBusy = Output(Bool())
        val txDone = Output(Bool())
        val txRejected = Output(Bool())
        val rxAccepted = Output(Bool())
        val rxDropped = Output(Bool())
        val rxBadFcs = Output(Bool())
        val txBytes = Output(UInt(16.W))
        val rxBytes = Output(UInt(16.W))
    })
    val tx = Module(new GmiiFrameTx())
    val rx = Module(new GmiiFrameRx(frameSlots = 4, readPrefetch = readPrefetch))
    tx.io.frame <> io.txFrame
    io.rxFrame <> rx.io.frame
    tx.io.enable := io.txEnable
    rx.io.enable := io.rxEnable
    rx.io.promiscuous := io.promiscuous
    rx.io.broadcastEnable := io.broadcastEnable
    rx.io.macAddress := io.macAddress
    rx.io.gmiiData := io.gmiiRxData
    rx.io.gmiiValid := io.gmiiRxValid
    rx.io.gmiiError := io.gmiiRxError
    io.gmiiTxData := tx.io.gmiiData
    io.gmiiTxEnable := tx.io.gmiiEnable
    io.gmiiTxError := tx.io.gmiiError
    io.txBusy := tx.io.busy
    io.rxBusy := rx.io.busy
    io.txDone := tx.io.done
    io.txRejected := tx.io.rejected
    io.rxAccepted := rx.io.accepted
    io.rxDropped := rx.io.dropped
    io.rxBadFcs := rx.io.badFcs
    io.txBytes := tx.io.bytes
    io.rxBytes := rx.io.bytes
}

object EthernetRxMacSafetyGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetRxMacSafetyGsim(args(1) == "1"), Array("--target-dir", args(0)))
}
