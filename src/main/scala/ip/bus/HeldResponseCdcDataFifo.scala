package soc.ip.bus

import chisel3._
import chisel3.util._

/** Separate area experiment: one captured output plus one owned RAM response.
  * Re-read the pending address under stall; return credit only on output capture.
  * Common cold reset only. Total payload elasticity is depth + 1, not depth + 2.
  * Requires true synchronous-read semantics and scoped Gray-bus constraints.
  */
class HeldResponseCdcDataFifo(width: Int, depth: Int = 16) extends RawModule {
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

    private val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    private val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset

    private val storage = SyncReadMem(depth, UInt(width.W))
    private val writeBinary = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        RegInit(0.U(pointerBits.W))
    }
    private val writeGray = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        RegInit(0.U(pointerBits.W))
    }
    private val capturedBinary = withClockAndReset(destinationClock, destinationRelease.resetOut) {
        RegInit(0.U(pointerBits.W))
    }
    private val capturedGray = withClockAndReset(destinationClock, destinationRelease.resetOut) {
        RegInit(0.U(pointerBits.W))
    }
    private val capturedGraySync = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val stage0 = RegInit(0.U(pointerBits.W))
        val stage1 = RegInit(0.U(pointerBits.W))
        addAttribute(stage0, "ASYNC_REG = \"TRUE\"")
        addAttribute(stage1, "ASYNC_REG = \"TRUE\"")
        stage0 := capturedGray
        stage1 := stage0
        stage1
    }
    private val writeGraySync = withClockAndReset(destinationClock, destinationRelease.resetOut) {
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
        sourceIdle := writeGray === capturedGraySync && !sourceRelease.resetOut.asBool
        val nextBinary = writeBinary + source.fire
        val nextGray = (nextBinary >> 1) ^ nextBinary
        val fullTarget = Cat(~capturedGraySync(pointerBits - 1, pointerBits - 2),
            capturedGraySync(pointerBits - 3, 0))
        full := nextGray === fullTarget
        writeBinary := nextBinary
        writeGray := nextGray
        when(source.fire) {
            storage.write(writeBinary(addressBits - 1, 0), source.bits)
        }
    }

    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val issueBinary = RegInit(0.U(pointerBits.W))
        val pending = RegInit(false.B)
        val heldAddress = Reg(UInt(addressBits.W))
        val output = Reg(UInt(width.W))
        val valid = RegInit(false.B)
        val resetActive = destinationRelease.resetOut.asBool
        destination.valid := valid && !resetActive
        destination.bits := output
        val pop = destination.fire
        val capture = pending && (!valid || pop) && !resetActive
        val issueGray = (issueBinary >> 1) ^ issueBinary
        val empty = issueGray === writeGraySync
        val issue = !empty && (!pending || capture) && !resetActive
        // Disabled SyncReadMem output is unspecified. Keep re-reading the
        // same still-owned address throughout a pending-response stall.
        val readAddress = Mux(issue, issueBinary(addressBits - 1, 0), heldAddress)
        val readEnable = (pending || issue) && !resetActive
        val word = storage.read(readAddress, readEnable)
        when(issue) {
            issueBinary := issueBinary + 1.U
            heldAddress := issueBinary(addressBits - 1, 0)
        }
        pending := (pending && !capture) || issue
        when(capture) {
            output := word
            val nextCaptured = capturedBinary + 1.U
            capturedBinary := nextCaptured
            capturedGray := (nextCaptured >> 1) ^ nextCaptured
        }
        when(capture || pop) { valid := capture }
        destinationIdle := empty && !pending && !valid && !resetActive
        assert(issueBinary === capturedBinary + pending.asUInt,
            "Pending RAM response must retain source-visible slot ownership")
        when(pending && !capture) {
            assert(readEnable && readAddress === heldAddress,
                "Stalled response must re-read its still-owned RAM address")
        }
    }
}
