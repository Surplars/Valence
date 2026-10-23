package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.ip.bus._

/** Passive counters: each input is a ONE-event-per-edge indication, not a count.
  * No output feeds any functional ready/valid path. Registered Gray encodings
  * change by at most one bit per source edge (including modulo wrap).
  */
class TelemetryGrayCounterBank(width: Int = 32) extends RawModule {
    require(width >= 4 && width <= 32)
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val events = IO(Input(UInt(7.W)))
    val totals = IO(Output(Vec(8, UInt(width.W))))
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock; sourceRelease.asyncReset := commonReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock; destinationRelease.asyncReset := commonReset
    val gray = withClockAndReset(sourceClock, sourceRelease.resetOut) {
        // Isolate late functional READY/retirement cones from the counter carry
        // and Gray encoder. Every accepted event is retained for exactly one
        // source edge; no functional control path depends on this staging.
        // Counter0 remains unstaged: it counts every actual managed edge.
        val sampledEvents = RegNext(events, 0.U(7.W))
        val binary = RegInit(VecInit(Seq.fill(8)(0.U(width.W))))
        val encoded = RegInit(VecInit(Seq.fill(8)(0.U(width.W))))
        for (n <- 0 until 8) {
            val increment = if (n == 0) true.B else sampledEvents(n - 1)
            val next = (binary(n) + increment)(width - 1, 0)
            binary(n) := next
            encoded(n) := next ^ (next >> 1)
        }
        encoded
    }
    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val graySync0 = RegInit(VecInit(Seq.fill(8)(0.U(width.W))))
        val graySync1 = RegInit(VecInit(Seq.fill(8)(0.U(width.W))))
        addAttribute(graySync0, "ASYNC_REG = \"TRUE\"")
        addAttribute(graySync1, "ASYNC_REG = \"TRUE\"")
        graySync0 := gray; graySync1 := graySync0
        for (n <- 0 until 8) {
            totals(n) := Cat((width - 1 to 0 by -1).map(bit => graySync1(n)(width - 1, bit).xorR))
        }
    }
}

/** AON-owned, read-only telemetry snapshots. Both banks publish on the SAME
  * AON edge. Gray CDC gives bounded sampling uncertainty, not exact cross-clock
  * simultaneity. Sequence-before/after protects a multi-register software read.
  */
class ClockPerformanceTelemetryRegisters(windowCycles: Int = 50000, referenceHz: Long = 50000000L,
    width: Int = 32, base: BigInt = BigInt("10080900", 16)) extends Module {
    require(windowCycles >= 8 && referenceHz > 0 && width >= 4 && width <= 32)
    require(base % 256 == 0)
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val totals = Input(Vec(2, Vec(8, UInt(width.W))))
        // AON levels: switching, reset/epoch instability, or reference invalidity.
        val invalidate = Input(Vec(2, Bool()))
    })
    val tick = RegInit(0.U(log2Ceil(windowCycles).W))
    val elapsed = RegInit(0.U(64.W))
    val sequence = RegInit(0.U(64.W))
    val stamp = RegInit(0.U(64.W))
    val previous = RegInit(0.U.asTypeOf(io.totals))
    val snapshot = RegInit(0.U.asTypeOf(io.totals))
    val delta = RegInit(0.U.asTypeOf(io.totals))
    val dirty = RegInit(VecInit(Seq.fill(2)(true.B)))
    val priorDirty = RegInit(VecInit(Seq.fill(2)(true.B)))
    val valid = RegInit(VecInit(Seq.fill(2)(false.B)))
    elapsed := elapsed + 1.U
    tick := Mux(tick === (windowCycles - 1).U, 0.U, tick + 1.U)
    for (d <- 0 until 2) {
        when(io.invalidate(d)) { dirty(d) := true.B; valid(d) := false.B }
        when(tick === (windowCycles - 1).U) {
            previous(d) := io.totals(d)
            snapshot(d) := io.totals(d)
            for (n <- 0 until 8) delta(d)(n) := io.totals(d)(n) - previous(d)(n)
            valid(d) := !dirty(d) && !priorDirty(d) && !io.invalidate(d)
            priorDirty(d) := dirty(d) || io.invalidate(d)
            dirty(d) := false.B
        }
    }
    when(tick === (windowCycles - 1).U) { sequence := sequence + 1.U; stamp := elapsed + 1.U }
    val replies = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    io.registers.response <> replies.io.deq
    io.registers.request.ready := replies.io.enq.ready
    val req = io.registers.request.bits
    val bank = (req.address - base.U)(8)
    val offset = req.address(7, 3)
    val legalOffset = offset <= 5.U || (offset >= 8.U && offset <= 23.U)
    val legal = req.address >= base.U && req.address < (base + 512).U(65.W) &&
        req.address(2, 0) === 0.U && req.size === 3.U && req.byteEnable === 255.U && !req.write && legalOffset
    val readData = Wire(Vec(2, UInt(64.W)))
    for (d <- 0 until 2) {
        // bit0: published interval usable; bit1: no measured edges; bit2: currently invalidating.
        val flags = Cat(io.invalidate(d), delta(d)(0) === 0.U, valid(d))
        readData(d) := MuxLookup(offset, 0.U(64.W))(Seq(
            0.U -> sequence, 1.U -> flags.pad(64), 2.U -> referenceHz.U(64.W),
            3.U -> windowCycles.U(64.W), 4.U -> stamp,
            5.U -> ((BigInt("544d", 16) << 48) | (BigInt(width) << 32) | 1).U(64.W)) ++
            (0 until 8).map(n => (8 + n).U -> delta(d)(n).pad(64)) ++
            (0 until 8).map(n => (16 + n).U -> snapshot(d)(n).pad(64)))
    }
    replies.io.enq.valid := io.registers.request.fire
    replies.io.enq.bits.error := !legal
    replies.io.enq.bits.data := Mux(legal, readData(bank), 0.U)
}

/** Complete request/reply CDC, usable from existing CPU or JTAG MMIO masters.
  * commonReset is cold-reset ONLY; do not clear live counters at a frequency change.
  */
class ClockPerformanceTelemetry(windowCycles: Int = 50000, referenceHz: Long = 50000000L,
    width: Int = 32, base: BigInt = BigInt("10080900", 16)) extends RawModule {
    val sourceClock = IO(Input(Clock())); val alwaysOnClock = IO(Input(Clock()))
    val managedClocks = IO(Input(Vec(2, Clock())))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val events = IO(Input(Vec(2, UInt(7.W))))
    val invalidate = IO(Input(Vec(2, Bool())))
    val sourceIdle = IO(Output(Bool())); val aonIdle = IO(Output(Bool()))
    val bridge = Module(new RegisterClockDomainBridge)
    bridge.sourceClock := sourceClock; bridge.destinationClock := alwaysOnClock; bridge.commonReset := commonReset
    bridge.source <> registers
    sourceIdle := bridge.sourceIdle; aonIdle := bridge.destinationIdle
    val bank = withClockAndReset(alwaysOnClock, bridge.destinationReset) {
        Module(new ClockPerformanceTelemetryRegisters(windowCycles, referenceHz, width, base))
    }
    bank.io.registers <> bridge.destination; bank.io.invalidate := invalidate
    for (d <- 0 until 2) {
        val counters = Module(new TelemetryGrayCounterBank(width))
        counters.suggestName(s"domain$d")
        counters.sourceClock := managedClocks(d); counters.destinationClock := alwaysOnClock
        counters.commonReset := commonReset; counters.events := events(d)
        bank.io.totals(d) := counters.totals
    }
}
