package soc.ip.uart

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterResponse}

/** 16550A-style console: 16-byte FIFOs, 16x majority RX, programmable line format.
  * referenceClockHz is a virtual baud reference, NOT another hardware clock.
  * Zero preserves the core-clock reference (or the historical board 24 MHz reference).
  */
class UartConsole(base: BigInt = BigInt("10000000", 16), clockHz: Int = 40000000,
    fastDivisorOne: Boolean = false, referenceClockHz: Int = 0) extends Module {
    require(base >= 0 && base % 8 == 0 && base + 8 <= (BigInt(1) << 64))
    private val referenceHz = if (referenceClockHz != 0) referenceClockHz
        else if (fastDivisorOne) 24000000 else clockHz
    require(clockHz > 0 && referenceHz > 0 && referenceHz <= clockHz)
    val io = IO(new Bundle {
        val mmio = Flipped(new RegisterPort)
        val rx = Input(Bool())
        val tx = Output(Bool())
        val irq = Output(Bool())
        val idle = Output(Bool())
    })
    val ier = RegInit(0.U(4.W))
    val lcr = RegInit(3.U(8.W))
    val mcr = RegInit(0.U(5.W))
    val scratch = RegInit(0.U(8.W))
    val divisor = RegInit(1.U(16.W))
    val fifoEnabled = RegInit(false.B)
    val triggerSelect = RegInit(0.U(2.W))
    val capacity = Mux(fifoEnabled, 16.U(5.W), 1.U(5.W))
    val trigger = MuxLookup(triggerSelect, 1.U(5.W))(Seq(
        1.U -> 4.U(5.W), 2.U -> 8.U(5.W), 3.U -> 14.U(5.W)))

    // A bounded phase accumulator gives an exact average reference frequency.
    // All divisors share baud = referenceHz/(16*divisor); DLL=0 is treated as 1.
    val referenceTick = if (referenceHz == clockHz) true.B else {
        val phase = RegInit(0.U(log2Ceil(clockHz).W))
        val advance = phase +& referenceHz.U
        val carry = advance >= clockHz.U
        phase := Mux(carry, advance - clockHz.U, advance)
        carry
    }
    val divider = RegInit(0.U(16.W))
    val effectiveDivisor = Mux(divisor === 0.U, 1.U(16.W), divisor)
    val baudTick = referenceTick && divider === effectiveDivisor - 1.U
    when(referenceTick) { divider := Mux(baudTick, 0.U, divider + 1.U) }

    val txMemory = Reg(Vec(16, UInt(8.W)))
    val txRead = RegInit(0.U(4.W))
    val txWrite = RegInit(0.U(4.W))
    val txCount = RegInit(0.U(5.W))
    val txShift = RegInit(4095.U(12.W))
    val txRemaining = RegInit(0.U(4.W))
    val txPhase = RegInit(0.U(4.W))
    val txHalfStop = RegInit(false.B)
    val txPending = RegInit(false.B)
    val serialTx = Mux(lcr(6), false.B, Mux(txRemaining === 0.U, true.B, txShift(0)))
    io.tx := Mux(mcr(4), true.B, serialTx)
    val rxMeta = RegNext(Mux(mcr(4), serialTx, io.rx), true.B)
    val rxSync = RegNext(rxMeta, true.B)

    val rxState = RegInit(0.U(3.W)) // idle, start, data, parity, stop, break-wait
    val rxPhase = RegInit(0.U(4.W))
    val rxVotes = RegInit(0.U(2.W))
    val rxIndex = RegInit(0.U(3.W))
    val rxShift = RegInit(0.U(8.W))
    val rxFormat = RegInit(3.U(6.W))
    val rxParityError = RegInit(false.B)
    val rxAllLow = RegInit(true.B)
    val rxWidth = 5.U(4.W) + rxFormat(1, 0)
    val sampled = (rxVotes +& rxSync.asUInt) >= 2.U
    val received = baudTick && rxState === 4.U && rxPhase === 8.U
    val breakReceived = !sampled && rxAllLow
    val receivedWord = Cat(breakReceived, !sampled, rxParityError, rxShift)
    when(rxState === 0.U) {
        when(!rxSync) {
            rxState := 1.U; rxPhase := 0.U; rxVotes := 0.U; rxIndex := 0.U
            rxShift := 0.U; rxFormat := lcr(5, 0); rxParityError := false.B; rxAllLow := true.B
        }
    }.elsewhen(rxState === 5.U) {
        when(rxSync) { rxState := 0.U }
    }.elsewhen(baudTick) {
        rxPhase := rxPhase + 1.U
        when(rxPhase === 0.U) { rxVotes := 0.U }
        when(rxPhase === 6.U || rxPhase === 7.U) { rxVotes := rxVotes + rxSync.asUInt }
        when(rxPhase === 8.U) {
            switch(rxState) {
                is(1.U) { when(sampled) { rxState := 0.U } }
                is(2.U) {
                    rxShift := (rxShift & ~(1.U(8.W) << rxIndex)) | (sampled.asUInt << rxIndex)
                    when(sampled) { rxAllLow := false.B }
                }
                is(3.U) {
                    val expected = Mux(rxFormat(5), !rxFormat(4), rxShift.xorR ^ !rxFormat(4))
                    rxParityError := sampled =/= expected
                    when(sampled) { rxAllLow := false.B }
                }
                is(4.U) { rxState := Mux(breakReceived, 5.U, 0.U) }
            }
        }
        when(rxPhase === 15.U) {
            switch(rxState) {
                is(1.U) { rxState := 2.U }
                is(2.U) {
                    rxIndex := rxIndex + 1.U
                    when(rxIndex === rxWidth - 1.U) { rxState := Mux(rxFormat(3), 3.U, 4.U) }
                }
                is(3.U) { rxState := 4.U }
            }
        }
    }

    val rxMemory = Reg(Vec(16, UInt(11.W))) // BI, FE, PE, character
    val rxErrors = RegInit(VecInit(Seq.fill(16)(false.B)))
    val rxRead = RegInit(0.U(4.W))
    val rxWrite = RegInit(0.U(4.W))
    val rxCount = RegInit(0.U(5.W))
    val overrun = RegInit(false.B)
    val rxTimeout = RegInit(0.U(10.W))
    val rxHead = rxMemory(rxRead)
    val headErrors = Mux(rxCount =/= 0.U, rxHead(10, 8), 0.U(3.W))
    val characterTicks = (5.U(4.W) + lcr(1, 0) + lcr(3).asUInt + 2.U) * 16.U +
        Mux(lcr(2), Mux(lcr(1, 0) === 0.U, 8.U, 16.U), 0.U)
    val timeoutLimit = characterTicks << 2
    val lineIrq = ier(2) && (overrun || headErrors.orR)
    val rxIrq = ier(0) && rxCount >= Mux(fifoEnabled, trigger, 1.U)
    val timeoutIrq = ier(0) && fifoEnabled && rxCount =/= 0.U && rxTimeout >= timeoutLimit
    val txIrq = ier(1) && txPending
    val modem = Mux(mcr(4), Cat(mcr(3), mcr(2), mcr(0), mcr(1)), 0.U(4.W))
    val previousModem = RegNext(modem, 0.U(4.W))
    val modemDelta = RegInit(0.U(4.W))
    val modemChanged = Cat(modem(3) ^ previousModem(3), previousModem(2) && !modem(2),
        modem(1) ^ previousModem(1), modem(0) ^ previousModem(0))
    val modemIrq = ier(3) && modemDelta.orR
    val interruptId = Mux(lineIrq, 6.U(4.W), Mux(rxIrq, 4.U,
        Mux(timeoutIrq, 12.U, Mux(txIrq, 2.U, Mux(modemIrq, 0.U, 1.U)))))
    val iir = Cat(Mux(fifoEnabled, 3.U(2.W), 0.U(2.W)), 0.U(2.W), interruptId)
    io.irq := lineIrq || rxIrq || timeoutIrq || txIrq || modemIrq
    val lsr = Cat(fifoEnabled && rxErrors.asUInt.orR,
        txCount === 0.U && txRemaining === 0.U, txCount === 0.U,
        headErrors, overrun, rxCount =/= 0.U)

    val request = io.mmio.request.bits
    val offset = request.address(2, 0)
    val data = request.data(7, 0)
    val dlab = lcr(7)
    val responses = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    // A FIFO-empty LSR alone is not a clock-stop contract. Include receiver,
    // retained bytes, replies, interrupts and forced break before ACKing drain.
    io.idle := txCount === 0.U && txRemaining === 0.U && rxCount === 0.U && rxState === 0.U &&
        responses.io.count === 0.U && !io.mmio.request.valid && !io.irq && !lcr(6)
    val addressLegal = request.address >= base.U && request.address < (base + 8).U(65.W)
    val legal = addressLegal && request.size === 0.U && request.byteEnable === 1.U
    val divisorWrite = request.write && dlab && offset <= 1.U
    val txAvailable = txCount < capacity || (txCount =/= 0.U && txRemaining === 0.U)
    val blocked = legal && request.write && (
        (!dlab && offset === 0.U && !txAvailable) ||
        (divisorWrite && (txCount =/= 0.U || txRemaining =/= 0.U || rxState =/= 0.U)))
    io.mmio.request.ready := responses.io.enq.ready && !blocked
    responses.io.enq.valid := io.mmio.request.valid && !blocked
    io.mmio.response <> responses.io.deq
    responses.io.enq.bits.error := !legal
    val fire = io.mmio.request.fire && legal
    val readRbr = fire && !request.write && offset === 0.U && !dlab
    val readLsr = fire && !request.write && offset === 5.U
    val fcrWrite = fire && request.write && offset === 2.U
    val modeChange = fcrWrite && data(0) =/= fifoEnabled
    val clearRx = fcrWrite && (data(1) || modeChange)
    val clearTx = fcrWrite && (data(2) || modeChange)
    val rxPop = readRbr && rxCount =/= 0.U
    val rxPush = received && !clearRx && (rxCount < capacity || rxPop)
    val txPop = txCount =/= 0.U && txRemaining === 0.U && !clearTx
    val txPush = fire && request.write && offset === 0.U && !dlab
    responses.io.enq.bits.data := Mux(legal && !request.write,
        MuxLookup(offset, 0.U)(Seq(
            0.U -> Mux(dlab, divisor(7, 0), Mux(rxCount =/= 0.U, rxHead(7, 0), 0.U)),
            1.U -> Mux(dlab, divisor(15, 8), ier),
            2.U -> iir, 3.U -> lcr, 4.U -> mcr, 5.U -> lsr,
            6.U -> Cat(modem, modemDelta), 7.U -> scratch)), 0.U)
    when(fire && request.write) {
        switch(offset) {
            is(0.U) { when(dlab) { divisor := Cat(divisor(15, 8), data); divider := 0.U } }
            is(1.U) {
                when(dlab) { divisor := Cat(data, divisor(7, 0)); divider := 0.U }
                    .otherwise {
                        ier := data(3, 0)
                        when(!ier(1) && data(1) && txCount === 0.U) { txPending := true.B }
                    }
            }
            is(2.U) { fifoEnabled := data(0); triggerSelect := data(7, 6) }
            is(3.U) { lcr := data }
            is(4.U) { mcr := data(4, 0) }
            is(7.U) { scratch := data }
        }
    }
    when(fire && !request.write && offset === 2.U && interruptId === 2.U) { txPending := false.B }
    when(fire && !request.write && offset === 6.U) { modemDelta := 0.U }
    when(modemChanged.orR) {
        modemDelta := Mux(fire && !request.write && offset === 6.U, 0.U, modemDelta) | modemChanged
    }

    when(txRemaining =/= 0.U && baudTick) {
        txPhase := txPhase + 1.U
        when(txPhase === Mux(txRemaining === 1.U && txHalfStop, 7.U, 15.U)) {
            txPhase := 0.U
            txShift := Cat(1.U(1.W), txShift(11, 1))
            txRemaining := txRemaining - 1.U
        }
    }
    when(txPop) {
        val width = 5.U(4.W) + lcr(1, 0)
        val mask = MuxLookup(lcr(1, 0), 255.U(8.W))(Seq(
            0.U -> 31.U(8.W), 1.U -> 63.U(8.W), 2.U -> 127.U(8.W)))
        val value = txMemory(txRead) & mask
        val parity = Mux(lcr(5), !lcr(4), value.xorR ^ !lcr(4))
        val baseFrame = Cat(7.U(3.W), value | ~mask, 0.U(1.W))
        val parityMask = (1.U(12.W) << (width + 1.U))(11, 0)
        txShift := Mux(lcr(3), (baseFrame & ~parityMask) |
            (parity.asUInt << (width + 1.U)), baseFrame)
        txRemaining := width + lcr(3).asUInt + Mux(lcr(2), 3.U, 2.U)
        txHalfStop := lcr(2) && lcr(1, 0) === 0.U
        txPhase := 0.U
        txRead := txRead + 1.U
        when(txCount === 1.U && !txPush) { txPending := true.B }
    }
    when(txPush) {
        txMemory(txWrite) := data; txWrite := txWrite + 1.U; txPending := false.B
    }
    when(txPush =/= txPop) { txCount := Mux(txPush, txCount + 1.U, txCount - 1.U) }
    when(clearTx) { txRead := 0.U; txWrite := 0.U; txCount := 0.U; txPending := true.B }

    when(readLsr) {
        overrun := false.B
        when(rxCount =/= 0.U) {
            rxMemory(rxRead) := Cat(0.U(3.W), rxHead(7, 0))
            rxErrors(rxRead) := false.B
        }
    }
    when(rxPop) { rxRead := rxRead + 1.U; rxErrors(rxRead) := false.B }
    when(rxPush) {
        rxMemory(rxWrite) := receivedWord; rxErrors(rxWrite) := receivedWord(10, 8).orR
        rxWrite := rxWrite + 1.U
    }
    when(rxPush =/= rxPop) { rxCount := Mux(rxPush, rxCount + 1.U, rxCount - 1.U) }
    when(received && !clearRx && !rxPush) { overrun := true.B }
    when(clearRx) {
        rxRead := 0.U; rxWrite := 0.U; rxCount := 0.U; overrun := false.B
        rxErrors.foreach(_ := false.B)
    }
    when(rxCount === 0.U || received || readRbr || clearRx) { rxTimeout := 0.U }
        .elsewhen(baudTick && rxTimeout < timeoutLimit) { rxTimeout := rxTimeout + 1.U }
}
