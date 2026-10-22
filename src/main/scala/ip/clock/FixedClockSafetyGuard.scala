package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcLevel, CdcMailbox, CdcResetRelease}

class FixedClockSafetyCommand(epochBits: Int) extends Bundle {
    val epoch = UInt(epochBits.W)
    val enable = Bool()
}
class FixedClockSafetyReceipt(epochBits: Int) extends Bundle {
    val command = new FixedClockSafetyCommand(epochBits)
    val guarded = Bool()
}
class FixedClockSafetyPort(epochBits: Int) extends Bundle {
    val command = Flipped(Decoupled(new FixedClockSafetyCommand(epochBits)))
    val receipt = Decoupled(new FixedClockSafetyReceipt(epochBits))
    val fault = Output(Bool())
}

/** A held safety window, not an epoch allocator or a substitute for data drain.
  * The fixed source consumes an arm against its CURRENT real predicate. An arm
  * that cannot qualify returns guarded=false; cancellation never waits for idle.
  * Once armed, any revocation latches a source-domain fault until cold reset.
  * AON receives a registered sticky level, not a combinational CDC launch. Its
  * synchronization latency is real: an already accepted DRP must retain its own
  * backend owner; this circuit cannot retroactively cancel it.
  * An ordered disarm receipt proves actual fixed consumption before admission
  * release. Both mailbox directions retain requests/replies under backpressure.
  */
class FixedClockSafetyGuard(epochBits: Int = 16) extends RawModule {
    require(epochBits >= 2 && epochBits <= 32)
    val aonClock = IO(Input(Clock()))
    val fixedClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val safe = IO(Input(Bool())) // fixed-clock local owner predicate
    val io = IO(new FixedClockSafetyPort(epochBits))
    private def release(c: Clock): AsyncReset = {
        val r = Module(new CdcResetRelease)
        r.clockIn := c; r.asyncReset := commonColdReset; r.resetOut
    }
    private val fixedReset = release(fixedClock)
    private val aonReset = release(aonClock)
    private val requests = Module(new CdcMailbox((new FixedClockSafetyCommand(epochBits)).getWidth))
    requests.sourceClock := aonClock; requests.destinationClock := fixedClock
    requests.commonReset := commonColdReset
    requests.source.valid := io.command.valid; requests.source.bits := io.command.bits.asUInt
    io.command.ready := requests.source.ready
    private val replies = Module(new CdcMailbox((new FixedClockSafetyReceipt(epochBits)).getWidth))
    replies.sourceClock := fixedClock; replies.destinationClock := aonClock
    replies.commonReset := commonColdReset
    io.receipt.valid := replies.destination.valid
    io.receipt.bits := replies.destination.bits.asTypeOf(new FixedClockSafetyReceipt(epochBits))
    replies.destination.ready := io.receipt.ready
    private val sourceFault = Wire(Bool())
    withClockAndReset(fixedClock, fixedReset) {
        val owned = RegInit(false.B)
        val active = RegInit(false.B)
        val epoch = RegInit(0.U(epochBits.W))
        val lastEpoch = RegInit(0.U(epochBits.W))
        val failed = RegInit(false.B)
        val pending = RegInit(false.B)
        val reply = Reg(new FixedClockSafetyReceipt(epochBits))
        val safeRegistered = RegNext(safe, false.B)
        val command = requests.destination.bits.asTypeOf(new FixedClockSafetyCommand(epochBits))
        requests.destination.ready := !pending && !failed
        replies.source.valid := pending
        replies.source.bits := reply.asUInt
        when(replies.source.fire) { pending := false.B }
        val disarming = requests.destination.fire && !command.enable && owned && command.epoch === epoch
        when(active && !safe && !disarming) { failed := true.B }
        when(requests.destination.fire) {
            pending := true.B; reply.command := command; reply.guarded := false.B
            when(command.enable) {
                when(!owned && command.epoch =/= 0.U && command.epoch > lastEpoch) {
                    owned := true.B; epoch := command.epoch; lastEpoch := command.epoch
                    active := safe && safeRegistered
                    reply.guarded := safe && safeRegistered
                }.otherwise { failed := true.B }
            }.otherwise {
                when(owned && command.epoch === epoch) { active := false.B; owned := false.B }
                    .otherwise { failed := true.B }
            }
        }
        sourceFault := failed
    }
    private val faultSync = Module(new CdcLevel)
    faultSync.clockIn := aonClock; faultSync.resetIn := aonReset
    faultSync.levelIn := sourceFault
    io.fault := faultSync.levelOut
}
