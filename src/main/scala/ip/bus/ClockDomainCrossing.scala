package soc.ip.bus

import chisel3._
import chisel3.util._

/** Common reset must reset both transaction endpoints; unilateral reset is NOT supported. */
class CdcResetRelease extends RawModule {
    val clockIn = IO(Input(Clock()))
    val asyncReset = IO(Input(AsyncReset()))
    val resetOut = IO(Output(AsyncReset()))
    val release = withClockAndReset(clockIn, asyncReset) {
        val stages = RegInit(7.U(3.W))
        addAttribute(stages, "ASYNC_REG = \"TRUE\"")
        stages := Cat(stages(1, 0), false.B)
        stages
    }
    resetOut := release(2).asAsyncReset
}

/** Only for persistent levels (e.g. IRQ); never use this to cross a pulse or a bus. */
class CdcLevel extends RawModule {
    val clockIn = IO(Input(Clock()))
    val resetIn = IO(Input(AsyncReset()))
    val levelIn = IO(Input(Bool()))
    val levelOut = IO(Output(Bool()))
    val stages = withClockAndReset(clockIn, resetIn) {
        val sync = RegInit(0.U(2.W))
        addAttribute(sync, "ASYNC_REG = \"TRUE\"")
        sync := Cat(sync(0), levelIn)
        sync
    }
    levelOut := stages(1)
}

/** Ordered bundled-data handshake. Capacity 1 request+response; no replay.
  * Source payload remains stable until its response is consumed. Destination
  * response remains stable until the next request. Two toggle synchronizers
  * give the held payload settling time; physical max-delay constraints are
  * required in addition to ASYNC_REG. A common reset discards in-flight work
  * only while the source CPU/master is itself reset. This is not hot-reset or DMA.
  */
class RegisterClockDomainBridge extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val sourceReset = IO(Output(AsyncReset()))
    val destinationReset = IO(Output(AsyncReset()))
    val sourceIdle = IO(Output(Bool()))
    val destinationIdle = IO(Output(Bool()))
    val source = IO(Flipped(new RegisterPort))
    val destination = IO(new RegisterPort)
    val sourceResetSync = Module(new CdcResetRelease)
    sourceResetSync.clockIn := sourceClock
    sourceResetSync.asyncReset := commonReset
    val destinationResetSync = Module(new CdcResetRelease)
    destinationResetSync.clockIn := destinationClock
    destinationResetSync.asyncReset := commonReset
    sourceReset := sourceResetSync.resetOut
    destinationReset := destinationResetSync.resetOut

    val requestHeld = withClockAndReset(sourceClock, sourceResetSync.resetOut) {
        Reg(new RegisterRequest)
    }
    val responseHeld = withClockAndReset(destinationClock, destinationResetSync.resetOut) {
        Reg(new RegisterResponse)
    }
    val requestToggle = withClockAndReset(sourceClock, sourceResetSync.resetOut) { RegInit(false.B) }
    val responseToggle = withClockAndReset(destinationClock, destinationResetSync.resetOut) { RegInit(false.B) }
    val requestSync = Module(new CdcLevel)
    requestSync.clockIn := destinationClock
    requestSync.resetIn := destinationResetSync.resetOut
    requestSync.levelIn := requestToggle
    val responseSync = Module(new CdcLevel)
    responseSync.clockIn := sourceClock
    responseSync.resetIn := sourceResetSync.resetOut
    responseSync.levelIn := responseToggle

    withClockAndReset(sourceClock, sourceResetSync.resetOut) {
        val busy = RegInit(false.B)
        val valid = RegInit(false.B)
        val seen = RegInit(false.B)
        val reply = Reg(new RegisterResponse)
        source.request.ready := !sourceResetSync.resetOut.asBool && !busy
        source.response.valid := valid && !sourceResetSync.resetOut.asBool
        source.response.bits := reply
        sourceIdle := !busy && !valid && !sourceResetSync.resetOut.asBool
        when(source.request.fire) {
            requestHeld := source.request.bits
            requestToggle := !requestToggle
            busy := true.B
        }
        when(responseSync.levelOut =/= seen && busy && !valid) {
            reply := responseHeld
            seen := responseSync.levelOut
            valid := true.B
        }
        when(source.response.fire) { valid := false.B; busy := false.B }
    }
    withClockAndReset(destinationClock, destinationResetSync.resetOut) {
        val seen = RegInit(false.B)
        val valid = RegInit(false.B)
        val waiting = RegInit(false.B)
        val request = Reg(new RegisterRequest)
        destination.request.valid := valid && !destinationResetSync.resetOut.asBool
        destination.request.bits := request
        destination.response.ready := waiting && !destinationResetSync.resetOut.asBool
        destinationIdle := !valid && !waiting && requestSync.levelOut === seen &&
            !destinationResetSync.resetOut.asBool
        when(requestSync.levelOut =/= seen && !valid && !waiting) {
            request := requestHeld
            seen := requestSync.levelOut
            valid := true.B
        }
        when(destination.request.fire) { valid := false.B; waiting := true.B }
        when(destination.response.fire) {
            responseHeld := destination.response.bits
            responseToggle := !responseToggle
            waiting := false.B
        }
    }
}

class CdcStreamBeat extends Bundle {
    val data = UInt(64.W)
    val keep = UInt(8.W)
    val last = Bool()
    val user = Bool()
}

/** Small distributed-RAM asynchronous stream FIFO; one beat/local cycle.
  * Packet sidebands are inseparable from data. Capacity is a power of two.
  * Gray buses need scoped max-delay/bus-skew constraints. Common reset only;
  * callers must discard partial packets on coordinated reset.
  */
class StreamClockDomainFifo(depth: Int = 16) extends RawModule {
    require(depth >= 4 && isPow2(depth))
    private val addressBits = log2Ceil(depth)
    private val pointerBits = addressBits + 1
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(Decoupled(new CdcStreamBeat)))
    val destination = IO(Decoupled(new CdcStreamBeat))
    val sourceResetSync = Module(new CdcResetRelease)
    sourceResetSync.clockIn := sourceClock
    sourceResetSync.asyncReset := commonReset
    val destinationResetSync = Module(new CdcResetRelease)
    destinationResetSync.clockIn := destinationClock
    destinationResetSync.asyncReset := commonReset
    val storage = Mem(depth, new CdcStreamBeat)
    val writeBinary = withClockAndReset(sourceClock, sourceResetSync.resetOut) { RegInit(0.U(pointerBits.W)) }
    val writeGray = withClockAndReset(sourceClock, sourceResetSync.resetOut) { RegInit(0.U(pointerBits.W)) }
    val readBinary = withClockAndReset(destinationClock, destinationResetSync.resetOut) { RegInit(0.U(pointerBits.W)) }
    val readGray = withClockAndReset(destinationClock, destinationResetSync.resetOut) { RegInit(0.U(pointerBits.W)) }
    val readGraySync = withClockAndReset(sourceClock, sourceResetSync.resetOut) {
        val stage0 = RegInit(0.U(pointerBits.W))
        val stage1 = RegInit(0.U(pointerBits.W))
        addAttribute(stage0, "ASYNC_REG = \"TRUE\"")
        addAttribute(stage1, "ASYNC_REG = \"TRUE\"")
        stage0 := readGray
        stage1 := stage0
        stage1
    }
    val writeGraySync = withClockAndReset(destinationClock, destinationResetSync.resetOut) {
        val stage0 = RegInit(0.U(pointerBits.W))
        val stage1 = RegInit(0.U(pointerBits.W))
        addAttribute(stage0, "ASYNC_REG = \"TRUE\"")
        addAttribute(stage1, "ASYNC_REG = \"TRUE\"")
        stage0 := writeGray
        stage1 := stage0
        stage1
    }
    withClockAndReset(sourceClock, sourceResetSync.resetOut) {
        val full = RegInit(false.B)
        source.ready := !full && !sourceResetSync.resetOut.asBool
        val nextBinary = writeBinary + source.fire
        val nextGray = (nextBinary >> 1) ^ nextBinary
        val fullTarget = Cat(~readGraySync(pointerBits - 1, pointerBits - 2),
            readGraySync(pointerBits - 3, 0))
        full := nextGray === fullTarget
        writeBinary := nextBinary
        writeGray := nextGray
        when(source.fire) { storage.write(writeBinary(addressBits - 1, 0), source.bits) }
    }
    withClockAndReset(destinationClock, destinationResetSync.resetOut) {
        val empty = RegInit(true.B)
        destination.valid := !empty && !destinationResetSync.resetOut.asBool
        destination.bits := storage.read(readBinary(addressBits - 1, 0))
        val nextBinary = readBinary + destination.fire
        val nextGray = (nextBinary >> 1) ^ nextBinary
        empty := nextGray === writeGraySync
        readBinary := nextBinary
        readGray := nextGray
    }
}
