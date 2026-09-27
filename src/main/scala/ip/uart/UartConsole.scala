package soc.ip.uart

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterResponse}

/** Non-FIFO 8N1 console with a 16550 register subset. See docs/uart.md. */
class UartConsole(base: BigInt = BigInt("10000000", 16)) extends Module {
    require(base >= 0 && base % 8 == 0 && base + 8 <= (BigInt(1) << 64))
    val io = IO(new Bundle {
        val mmio = Flipped(new RegisterPort)
        val rx   = Input(Bool())
        val tx   = Output(Bool())
        val irq  = Output(Bool())
    })
    val ier       = RegInit(0.U(3.W))
    val lcr       = RegInit(3.U(8.W))
    val mcr       = RegInit(0.U(4.W))
    val scratch   = RegInit(0.U(8.W))
    val divisor   = RegInit(1.U(16.W))
    val period    = Cat(Mux(divisor === 0.U, 1.U(16.W), divisor), 0.U(4.W))
    val txFull    = RegInit(false.B)
    val txByte    = Reg(UInt(8.W))
    val txBits    = RegInit(0.U(4.W))
    val txShift   = RegInit(1023.U(10.W))
    val txTimer   = RegInit(0.U(20.W))
    val txPending = RegInit(false.B)
    val txStart   = txFull && txBits === 0.U
    io.tx := Mux(txBits === 0.U, true.B, txShift(0))
    when(txBits =/= 0.U) {
        when(txTimer === 0.U) {
            txTimer := period - 1.U
            txShift := Cat(1.U(1.W), txShift(9, 1))
            txBits  := txBits - 1.U
        }.otherwise { txTimer := txTimer - 1.U }
    }
    when(txStart) {
        txFull    := false.B
        txShift   := Cat(1.U(1.W), txByte, 0.U(1.W))
        txBits    := 10.U
        txTimer   := period - 1.U
        txPending := true.B
    }
    val rxMeta   = RegNext(io.rx, true.B)
    val rxSync   = RegNext(rxMeta, true.B)
    val rxState  = RegInit(0.U(2.W)) // idle, start, data, stop
    val rxTimer  = RegInit(0.U(20.W))
    val rxIndex  = RegInit(0.U(3.W))
    val rxShift  = Reg(UInt(8.W))
    val rxFull   = RegInit(false.B)
    val rxByte   = Reg(UInt(8.W))
    val overrun  = RegInit(false.B)
    val framing  = RegInit(false.B)
    val received = rxState === 3.U && rxTimer === 0.U
    when(rxState === 0.U) {
        when(!rxSync) { rxState := 1.U; rxTimer := (period >> 1) - 1.U }
    }.elsewhen(rxTimer =/= 0.U) { rxTimer := rxTimer - 1.U }
        .otherwise {
            rxTimer := period - 1.U
            switch(rxState) {
                is(1.U) {
                    when(rxSync) { rxState := 0.U }
                        .otherwise { rxState := 2.U; rxIndex := 0.U }
                }
                is(2.U) {
                    rxShift := (rxShift & ~(1.U(8.W) << rxIndex)) | (rxSync.asUInt << rxIndex)
                    rxIndex := rxIndex + 1.U
                    when(rxIndex === 7.U) { rxState := 3.U }
                }
                is(3.U) { rxState := 0.U }
            }
        }
    val lineIrq = ier(2) && (overrun || framing)
    val rxIrq   = ier(0) && rxFull
    val txIrq   = ier(1) && txPending
    val iir     = Mux(lineIrq, 6.U, Mux(rxIrq, 4.U, Mux(txIrq, 2.U, 1.U)))
    io.irq := lineIrq || rxIrq || txIrq
    val lsr          = Cat(0.U(1.W), !txFull && txBits === 0.U, !txFull, 0.U(1.W), framing, 0.U(1.W), overrun, rxFull)
    val request      = io.mmio.request.bits
    val offset       = request.address(2, 0)
    val data         = request.data(7, 0)
    val dlab         = lcr(7)
    val responses    = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    val addressLegal = request.address >= base.U && request.address < (base + 8).U(65.W)
    val formatLegal  = !request.write || offset =/= 3.U || data === 3.U || data === 128.U || data === 131.U
    val divisorWrite = request.write && dlab && offset <= 1.U
    val legal        = addressLegal && request.size === 0.U && request.byteEnable === 1.U && formatLegal
    val blocked      = legal && request.write && ((!dlab && offset === 0.U && txFull && !txStart) ||
        (divisorWrite && (txFull || txBits =/= 0.U || rxState =/= 0.U)))
    io.mmio.request.ready  := responses.io.enq.ready && !blocked
    responses.io.enq.valid := io.mmio.request.valid && !blocked
    io.mmio.response <> responses.io.deq
    responses.io.enq.bits.error := !legal
    val fire    = io.mmio.request.fire && legal
    val readRbr = fire && !request.write && offset === 0.U && !dlab
    val readLsr = fire && !request.write && offset === 5.U
    val clearRx = fire && request.write && offset === 2.U && data(1)
    val clearTx = fire && request.write && offset === 2.U && data(2)
    responses.io.enq.bits.data := Mux(
        legal && !request.write,
        MuxLookup(offset, 0.U)(
            Seq(
                0.U -> Mux(dlab, divisor(7, 0), Mux(rxFull, rxByte, 0.U)),
                1.U -> Mux(dlab, divisor(15, 8), ier),
                2.U -> iir,
                3.U -> lcr,
                4.U -> mcr,
                5.U -> lsr,
                6.U -> 0.U,
                7.U -> scratch
            )
        ),
        0.U
    )
    when(fire && request.write) {
        switch(offset) {
            is(0.U) {
                when(dlab) { divisor := Cat(divisor(15, 8), data) }
                    .otherwise { txFull := true.B; txByte := data; txPending := false.B }
            }
            is(1.U) {
                when(dlab) { divisor := Cat(data, divisor(7, 0)) }
                    .otherwise {
                        ier := data(2, 0)
                        when(!ier(1) && data(1) && !txFull) { txPending := true.B }
                    }
            }
            is(3.U) { lcr := data }
            is(4.U) { mcr := data(3, 0) }
            is(7.U) { scratch := data }
        }
    }
    when(fire && !request.write && offset === 2.U && iir === 2.U) { txPending := false.B }
    when(clearTx) { txFull := false.B; txPending := true.B }
    when(readRbr || clearRx) { rxFull := false.B }
    when(readLsr || clearRx) { overrun := false.B; framing := false.B }
    when(received && !clearRx) {
        when(!rxFull || readRbr) { rxFull := true.B; rxByte := rxShift }
            .otherwise { overrun := true.B }
        when(!rxSync) { framing := true.B }
    }
}
