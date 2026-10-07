package soc.ip.bus

import chisel3._
import chisel3.util._

/** Atomic held-data mailbox. ACK means the destination consumed the payload,
  * not just that its toggle arrived. Common cold reset only; both endpoints
  * discard work together. Held payloads and toggle inputs require scoped
  * physical max-delay constraints, in addition to synchronizer attributes.
  */
class CdcMailbox(width: Int) extends RawModule {
    require(width > 0)
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(Decoupled(UInt(width.W))))
    val destination = IO(Decoupled(UInt(width.W)))
    val sourceIdle = IO(Output(Bool()))
    val destinationIdle = IO(Output(Bool()))
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset
    val held = withClockAndReset(sourceClock, sourceRelease.resetOut) { Reg(UInt(width.W)) }
    val requestToggle = withClockAndReset(sourceClock, sourceRelease.resetOut) { RegInit(false.B) }
    val ackToggle = withClockAndReset(destinationClock, destinationRelease.resetOut) { RegInit(false.B) }
    val requestSync = Module(new CdcLevel)
    requestSync.clockIn := destinationClock
    requestSync.resetIn := destinationRelease.resetOut
    requestSync.levelIn := requestToggle
    val ackSync = Module(new CdcLevel)
    ackSync.clockIn := sourceClock
    ackSync.resetIn := sourceRelease.resetOut
    ackSync.levelIn := ackToggle
    source.ready := requestToggle === ackSync.levelOut && !sourceRelease.resetOut.asBool
    sourceIdle := source.ready
    withClockAndReset(sourceClock, sourceRelease.resetOut) {
        when(source.fire) { held := source.bits; requestToggle := !requestToggle }
    }
    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val valid = RegInit(false.B)
        val captured = Reg(UInt(width.W))
        val token = RegInit(false.B)
        destination.valid := valid && !destinationRelease.resetOut.asBool
        destination.bits := captured
        destinationIdle := !destinationRelease.resetOut.asBool && !valid && requestSync.levelOut === ackToggle
        when(!valid && requestSync.levelOut =/= ackToggle) {
            captured := held
            token := requestSync.levelOut
            valid := true.B
        }
        when(destination.fire) { valid := false.B; ackToggle := token }
    }
}

/** Small dual-clock FIFO with synchronous read and registered output. A read
  * releases its RAM slot only after the output register captured it; a pending read and
  * the held output are additional storage, not part of pointer-empty alone.
  * The destination never exposes a combinational cross-domain RAM payload.
  * Common reset only. Gray buses need max-delay and bus-skew constraints.
  */
class CdcDataFifo(width: Int, depth: Int = 16) extends RawModule {
    require(width > 0 && depth >= 4 && isPow2(depth))
    private val addressBits = log2Ceil(depth)
    private val pointerBits = addressBits + 1
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(Decoupled(UInt(width.W))))
    val destination = IO(Decoupled(UInt(width.W)))
    val sourceIdle = IO(Output(Bool()))
    val destinationIdle = IO(Output(Bool()))
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset
    val storage = SyncReadMem(depth, UInt(width.W))
    val writeBinary = withClockAndReset(sourceClock, sourceRelease.resetOut) { RegInit(0.U(pointerBits.W)) }
    val writeGray = withClockAndReset(sourceClock, sourceRelease.resetOut) { RegInit(0.U(pointerBits.W)) }
    val readBinary = withClockAndReset(destinationClock, destinationRelease.resetOut) { RegInit(0.U(pointerBits.W)) }
    val readGray = withClockAndReset(destinationClock, destinationRelease.resetOut) { RegInit(0.U(pointerBits.W)) }
    val readGraySync = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val stage0 = RegInit(0.U(pointerBits.W))
        val stage1 = RegInit(0.U(pointerBits.W))
        addAttribute(stage0, "ASYNC_REG = \"TRUE\"")
        addAttribute(stage1, "ASYNC_REG = \"TRUE\"")
        stage0 := readGray
        stage1 := stage0
        stage1
    }
    val writeGraySync = withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val stage0 = RegInit(0.U(pointerBits.W))
        val stage1 = RegInit(0.U(pointerBits.W))
        addAttribute(stage0, "ASYNC_REG = \"TRUE\"")
        addAttribute(stage1, "ASYNC_REG = \"TRUE\"")
        stage0 := writeGray
        stage1 := stage0
        stage1
    }
    withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val full = RegInit(false.B)
        source.ready := !full && !sourceRelease.resetOut.asBool
        sourceIdle := writeGray === readGraySync && !sourceRelease.resetOut.asBool
        val nextBinary = writeBinary + source.fire
        val nextGray = (nextBinary >> 1) ^ nextBinary
        val fullTarget = Cat(~readGraySync(pointerBits - 1, pointerBits - 2), readGraySync(pointerBits - 3, 0))
        full := nextGray === fullTarget
        writeBinary := nextBinary
        writeGray := nextGray
        when(source.fire) { storage.write(writeBinary(addressBits - 1, 0), source.bits) }
    }
    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val valid = RegInit(false.B)
        val output = Reg(UInt(width.W))
        val pending = RegInit(false.B)
        val empty = readGray === writeGraySync
        val readEnable = !empty && !pending && (!valid || destination.ready) && !destinationRelease.resetOut.asBool
        val word = storage.read(readBinary(addressBits - 1, 0), readEnable)
        pending := readEnable
        destination.valid := valid && !destinationRelease.resetOut.asBool
        destination.bits := output
        destinationIdle := empty && !pending && !valid && !destinationRelease.resetOut.asBool
        when(destination.fire) { valid := false.B }
        when(pending) {
            output := word
            valid := true.B
            // CIRCT's synchronous-read model registers the RAM address before
            // exposing data. Returning credit at readEnable would let a fast
            // writer overwrite that slot before this output capture.
            val nextBinary = readBinary + 1.U
            readBinary := nextBinary
            readGray := (nextBinary >> 1) ^ nextBinary
        }
    }
}

/** Lossless modular accumulation, not pulse synchronization. Source increments
  * continue while destination stalls/stops. Periodic atomic total snapshots
  * become ordered deltas, held until consumed. Fewer than 2^width increments
  * may occur between consumed snapshots. A common reset starts a new epoch.
  */
class CdcAccumulator(width: Int = 32) extends RawModule {
    require(width >= 8 && width <= 64)
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val increment = IO(Input(UInt(width.W)))
    val delta = IO(Decoupled(UInt(width.W)))
    val mailbox = Module(new CdcMailbox(width))
    mailbox.sourceClock := sourceClock
    mailbox.destinationClock := destinationClock
    mailbox.commonReset := commonReset
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val total = RegInit(0.U(width.W))
        val sent = RegInit(0.U(width.W))
        total := total + increment
        mailbox.source.valid := total =/= sent
        mailbox.source.bits := total
        when(mailbox.source.fire) { sent := total }
    }
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset
    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val previous = RegInit(0.U(width.W))
        val valid = RegInit(false.B)
        val heldDelta = Reg(UInt(width.W))
        mailbox.destination.ready := !valid || delta.ready
        delta.valid := valid && !destinationRelease.resetOut.asBool
        delta.bits := heldDelta
        when(delta.fire) { valid := false.B }
        when(mailbox.destination.fire) {
            val difference = mailbox.destination.bits - previous
            previous := mailbox.destination.bits
            heldDelta := difference
            valid := difference =/= 0.U
        }
    }
}
