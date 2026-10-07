package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.ip.bus._

case class ClockResource(name: String, nominalHz: Long, canGate: Boolean = false,
    present: Boolean = true, parent: Int = -1) {
    require(name.matches("[A-Z][A-Z0-9_]{0,7}") && nominalHz >= 0 && nominalHz <= 0xffffffffL)
    require(!present || nominalHz > 0)
    require(!canGate || present)
    val tag: BigInt = name.zipWithIndex.map { case (c, n) => BigInt(c.toInt) << (8 * n) }.sum
}

case class CmuParams(alwaysOnHz: Int, resources: Seq[ClockResource],
    base: BigInt = BigInt("10080000", 16), timeoutCycles: Int = 1024, idleCycles: Int = 3) {
    require(alwaysOnHz > 0 && resources.nonEmpty && resources.size <= 16)
    require(base >= 0 && base % 4096 == 0 && base + 4096 <= (BigInt(1) << 64))
    require(resources.map(_.name).distinct.size == resources.size)
    require(resources.head.present && !resources.head.canGate && resources.head.nominalHz == alwaysOnHz)
    require(timeoutCycles >= 8 && idleCycles >= 2 && idleCycles < timeoutCycles)
    for ((r, n) <- resources.zipWithIndex) {
        require(r.parent >= -1 && r.parent < n, "clock parents must precede children")
        if (r.present && r.parent >= 0) {
            require(resources(r.parent).present && !resources(r.parent).canGate,
                "V1 cannot gate a present child's parent")
        }
    }
    val presentMask: BigInt = resources.zipWithIndex.filter(_._1.present).map(x => BigInt(1) << x._2).sum
    val gateableMask: BigInt = resources.zipWithIndex.filter(_._1.canGate).map(x => BigInt(1) << x._2).sum
}

class ClockResourceControl extends Bundle {
    val ack = Input(Bool())
    // Persistent/latching wake only, not an asynchronous short pulse.
    val wake = Input(Bool())
    val clockEnable = Output(Bool())
    val quiesce = Output(Bool())
    val isolate = Output(Bool())
    val allowAdmission = Output(Bool())
}

/** Independent always-on CMU. Four ordered reply credits, one access/cycle,
  * response visible next cycle; payload is stable while stalled. Internal
  * RegisterPort uses right-justified naturally aligned 1/2/4/8-byte accesses.
  * Invalid/RO/protected writes return errors without ANY partial side effect.
  * No hot reset, power switch, runtime rate change or frequency measurement.
  * Only resources with proven endpoint/backend wiring may advertise canGate.
  */
class ClockManagementUnit(config: CmuParams) extends Module {
    private val count = config.resources.size
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val resources = Vec(count, new ClockResourceControl)
        val irq = Output(Bool())
    })
    val replies = Module(new Queue(new RegisterResponse, 4, pipe = false, flow = false))
    io.registers.response <> replies.io.deq
    io.registers.request.ready := replies.io.enq.ready
    val request = io.registers.request.bits
    val offset = request.address(11, 0) & "hff8".U
    val shift = Cat(request.address(2, 0), 0.U(3.W))
    val accessMask = MuxLookup(request.size, 0.U(8.W))((0 to 3).map { n =>
        n.U -> ((BigInt(1) << (1 << n)) - 1).U(8.W)
    })
    val aligned = MuxLookup(request.size, false.B)((0 to 3).map { n =>
        n.U -> ((request.address & ((BigInt(1) << n) - 1).U(64.W)) === 0.U)
    })
    val maskLegal = Mux(request.write, (request.byteEnable & ~accessMask) === 0.U,
        request.byteEnable === accessMask)
    val bytes = Cat((0 until 8).reverse.map(n => Fill(8, request.byteEnable(n))))
    val writeMask = (bytes << shift)(63, 0)
    val writeData = ((request.data & bytes) << shift)(63, 0)
    val globalOffsets = Seq(0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38,
        0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x70, 0x78)
    val metadataOffsets = for (n <- config.resources.indices; word <- 0 until 6)
        yield 0x100 + n * 0x40 + word * 8
    val known = (globalOffsets ++ metadataOffsets).map(n => offset === n.U).reduce(_ || _)
    val writable = Seq(0x20, 0x50, 0x58, 0x60, 0x68, 0x70).map(n => offset === n.U).reduce(_ || _)
    val range = request.address >= config.base.U && request.address < (config.base + 4096).U(65.W)
    val reservedLegal = (writeData & ~config.gateableMask.U(64.W)) === 0.U
    val legal = range && request.size <= 3.U && aligned && maskLegal && known &&
        (!request.write || (writable && reservedLegal))
    val accepted = io.registers.request.fire && legal && request.write
    val stop = RegInit(0.U(count.W))
    val wakePending = RegInit(0.U(count.W))
    val wakeEnable = RegInit(config.gateableMask.U(count.W))
    val irqEnable = RegInit(0.U(count.W))
    val enabled = Wire(Vec(count, Bool()))
    val stopped = Wire(Vec(count, Bool()))
    val quiesce = Wire(Vec(count, Bool()))
    val isolated = Wire(Vec(count, Bool()))
    val admission = Wire(Vec(count, Bool()))
    val faults = Wire(Vec(count, Bool()))
    val externalWake = Wire(Vec(count, Bool()))
    val lowMask = writeMask(count - 1, 0)
    val lowData = writeData(count - 1, 0)
    val clearWake = Mux(accepted && offset === 0x50.U, lowData, 0.U(count.W))
    val softwareWake = Mux(accepted && offset === 0x60.U, lowData, 0.U(count.W))
    val wakeEvents = (externalWake.asUInt & wakeEnable) | softwareWake
    val nextStop = Mux(accepted && offset === 0x20.U, (stop & ~lowMask) | lowData, stop)
    // Wake wins over a coincident STOP/W1C, and clears STOP so execution can
    // resume without software having to service its own wake while isolated.
    stop := nextStop & ~wakeEvents
    wakePending := (wakePending & ~clearWake) | wakeEvents
    when(accepted && offset === 0x58.U) { wakeEnable := (wakeEnable & ~lowMask) | lowData }
    when(accepted && offset === 0x70.U) { irqEnable := (irqEnable & ~lowMask) | lowData }
    for ((resource, n) <- config.resources.zipWithIndex) {
        if (resource.canGate) {
            val wakeSync = Module(new CdcLevel)
            wakeSync.clockIn := clock
            wakeSync.resetIn := reset.asBool.asAsyncReset
            wakeSync.levelIn := io.resources(n).wake
            externalWake(n) := wakeSync.levelOut
            val policy = Module(new PeripheralClockControl(config.timeoutCycles, config.idleCycles))
            policy.io.stopRequest := stop(n)
            policy.io.wake := wakePending(n) || wakeEvents(n)
            policy.io.domainAck := io.resources(n).ack
            policy.io.clearFault := accepted && offset === 0x68.U && lowData(n)
            enabled(n) := policy.io.clockEnable
            stopped(n) := policy.io.stopped
            quiesce(n) := policy.io.quiesce
            isolated(n) := policy.io.isolate
            admission(n) := policy.io.allowAdmission
            faults(n) := policy.io.fault
        } else {
            externalWake(n) := false.B
            enabled(n) := resource.present.B
            stopped(n) := false.B
            quiesce(n) := false.B
            isolated(n) := false.B
            admission(n) := resource.present.B
            faults(n) := false.B
        }
        io.resources(n).clockEnable := enabled(n)
        io.resources(n).quiesce := quiesce(n)
        io.resources(n).isolate := isolated(n)
        io.resources(n).allowAdmission := admission(n)
    }
    val irqStatus = wakePending | faults.asUInt
    io.irq := (irqStatus & irqEnable).orR
    val capabilities = (BigInt(config.alwaysOnHz) << 32) | (BigInt(count) << 16) | 7
    val metadata = for ((r, n) <- config.resources.zipWithIndex) yield {
        val status = Cat(wakePending(n), faults(n), admission(n), isolated(n), quiesce(n), stopped(n), enabled(n))
        Seq((0x100 + n * 0x40).U -> n.U(64.W),
            (0x108 + n * 0x40).U -> r.nominalHz.U(64.W),
            (0x110 + n * 0x40).U -> BigInt((if (r.present) 1 else 0) | (if (r.canGate) 2 else 0)).U(64.W),
            (0x118 + n * 0x40).U -> status.asUInt.pad(64),
            (0x120 + n * 0x40).U ->
                (if (r.parent < 0) BigInt("ffffffffffffffff", 16) else BigInt(r.parent)).U(64.W),
            (0x128 + n * 0x40).U -> r.tag.U(64.W))
    }
    val readData = MuxLookup(offset, 0.U(64.W))(Seq(
        0x00.U -> "h56434d5500010001".U(64.W), 0x08.U -> capabilities.U(64.W),
        0x10.U -> config.presentMask.U(64.W), 0x18.U -> config.gateableMask.U(64.W),
        0x20.U -> stop.pad(64), 0x28.U -> enabled.asUInt.pad(64), 0x30.U -> stopped.asUInt.pad(64),
        0x38.U -> quiesce.asUInt.pad(64), 0x40.U -> isolated.asUInt.pad(64), 0x48.U -> admission.asUInt.pad(64),
        0x50.U -> wakePending.pad(64), 0x58.U -> wakeEnable.pad(64), 0x60.U -> 0.U(64.W),
        0x68.U -> faults.asUInt.pad(64), 0x70.U -> irqEnable.pad(64), 0x78.U -> irqStatus.pad(64)
    ) ++ metadata.flatten)
    replies.io.enq.valid := io.registers.request.fire
    replies.io.enq.bits.error := !legal
    replies.io.enq.bits.data := Mux(legal && !request.write, readData >> shift, 0.U)
}

/** Always-on MMIO stays accessible regardless of managed clock state. Only
  * the complete bus request/response crosses; CPU implementation is irrelevant.
  * Both endpoints and the CPU/master must share the coordinated cold reset.
  */
class ClockManagementBoundary(config: CmuParams) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val resources = IO(Vec(config.resources.size, new ClockResourceControl))
    val irq = IO(Output(Bool()))
    val bridge = Module(new RegisterClockDomainBridge)
    bridge.sourceClock := sourceClock
    bridge.destinationClock := alwaysOnClock
    bridge.commonReset := commonReset
    bridge.source <> registers
    val cmu = withClockAndReset(alwaysOnClock, bridge.destinationReset) { Module(new ClockManagementUnit(config)) }
    cmu.io.registers <> bridge.destination
    resources <> cmu.io.resources
    val irqSync = Module(new CdcLevel)
    irqSync.clockIn := sourceClock
    irqSync.resetIn := bridge.sourceReset
    irqSync.levelIn := withClockAndReset(alwaysOnClock, bridge.destinationReset) { RegNext(cmu.io.irq, false.B) }
    irq := irqSync.levelOut
}
