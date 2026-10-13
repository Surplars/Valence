package soc.ip.ethernet

import chisel3._
import chisel3.util.{Cat, HasBlackBoxResource}

/** Explicit negative-edge source registers; no fabric clock inverter or gate. */
private class MacRawFallingSample extends BlackBox with HasBlackBoxResource {
    override def desiredName: String = "ValenceMacRawFallingSample"
    val io = IO(new Bundle {
        val rawClock = Input(Clock())
        val rawReset = Input(AsyncReset())
        val payload = Input(UInt(12.W))
        val sampled = Output(UInt(12.W))
    })
    addResource("/ethernet/ValenceMacRawFallingSample.sv")
}

/** Related-clock media boundary. RAW never stops. TX retains its original
  * positive-edge byteStep epoch. RX consumes one tuple per enabled edge with
  * one additional managed edge of latency, including byteStep gaps and EOF.
  * Only cold-reset releases may reset this stage; quiesce/isolate do not.
  */
class MacRawHandoff extends RawModule {
    val rawClock = IO(Input(Clock()))
    val rawReset = IO(Input(AsyncReset()))
    val rxClock = IO(Input(Clock()))
    val rxReset = IO(Input(AsyncReset()))
    val rawRxPayload = IO(Input(UInt(11.W)))
    val rawTxByteStep = IO(Input(Bool()))
    val rxPayload = IO(Output(UInt(11.W)))
    val txByteStep = IO(Output(Bool()))
    val rxPending = IO(Output(Bool()))

    private val falling = Module(new MacRawFallingSample)
    falling.io.rawClock := rawClock
    falling.io.rawReset := rawReset
    falling.io.payload := Cat(rawTxByteStep, rawRxPayload)
    txByteStep := falling.io.sampled(11)
    val managed = withClockAndReset(rxClock, rxReset) {
        RegNext(falling.io.sampled(10, 0), 0.U(11.W))
    }
    rxPayload := managed
    // Keep the full tuple even when valid or byteStep is low. Only valid marks
    // this register as work for CMU drain; an idle byteStep=1 cannot hold it busy.
    rxPending := managed(9)
}
