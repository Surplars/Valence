package soc.ip.timer

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterResponse}

/** Single-hart 64-bit machine timer. Synchronous fixed-frequency tick; see docs/machine-timer.md. */
class MachineTimer(
    compareAddress: BigInt = BigInt("02004000", 16),
    timeAddress: BigInt = BigInt("0200bff8", 16)
) extends Module {
    require(Seq(compareAddress, timeAddress).forall(a => a >= 0 && a % 8 == 0 && a + 8 <= (BigInt(1) << 64)))
    require(compareAddress != timeAddress)
    val io = IO(new Bundle {
        val mmio = Flipped(new RegisterPort)
        val tick = Input(Bool())
        val irq  = Output(Bool())
        val timeValue = Output(UInt(64.W))
    })
    val time    = RegInit(0.U(64.W))
    val compare = RegInit("hffffffffffffffff".U(64.W))
    io.timeValue := time
    io.irq := RegNext(time >= compare, false.B)
    when(io.tick) { time := time + 1.U }
    val r          = io.mmio.request.bits
    val timeHit    = r.address === timeAddress.U || r.address === (timeAddress + 4).U
    val compareHit = r.address === compareAddress.U || r.address === (compareAddress + 4).U
    val full       = r.size === 3.U && r.byteEnable === 255.U && !r.address(2)
    val half       = r.size === 2.U && r.byteEnable === 15.U
    val legal      = (timeHit || compareHit) && (full || half)
    val before     = Mux(timeHit, time, compare)
    val after      =
        Mux(full, r.data, Mux(r.address(2), Cat(r.data(31, 0), before(31, 0)), Cat(before(63, 32), r.data(31, 0))))
    val responses = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    io.mmio.request.ready       := responses.io.enq.ready
    responses.io.enq.valid      := io.mmio.request.valid
    responses.io.enq.bits.error := !legal
    responses.io.enq.bits.data  := Mux(
        legal && !r.write,
        Mux(full, before, Mux(r.address(2), before(63, 32), before(31, 0))),
        0.U
    )
    io.mmio.response <> responses.io.deq
    when(io.mmio.request.fire && legal && r.write) {
        when(timeHit) { time := after }.otherwise { compare := after }
    }
}
