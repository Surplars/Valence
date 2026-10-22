package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.ip.bus._

private class ClockRateReply extends Bundle {
    val response = new RegisterResponse
    val begins = Bool()
    val domain = UInt(1.W)
}

/** AON observation for a fixed management/debug domain, including fatal isolation. */
class ClockRateStatus extends Bundle {
    val requestedHz = UInt(32.W); val targetHz = UInt(32.W); val actualHz = UInt(32.W)
    val errors = UInt(32.W); val completed = UInt(32.W); val state = UInt(4.W)
    val actualValid = Bool(); val busy = Bool(); val lastSuccess = Bool()
}

/** Optional CMU page extension, CPU at +0x800 and fabric at +0x880. Existing
  * CMU v1 decoding is deliberately unchanged until real production endpoints
  * exist. Eight-byte aligned accesses only; four ordered reply credits.
  * sourceRetired is the END-TO-END response receipt, not local reply enqueue.
  */
class ClockRateManagement(domains: Seq[ClockRateParams], base: BigInt = BigInt("10080800", 16),
    externalDrainLease: Boolean = false, backendFaultInput: Boolean = false) extends Module {
    require(!backendFaultInput || externalDrainLease)
    require(domains.size == 2 && base >= 0 && base % 256 == 0 && base + 256 < (BigInt(1) << 64))
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val endpoints = Vec(2, new ClockRateEndpoint)
        val sourceRetired = Input(UInt(2.W))
        val status = Output(Vec(2, new ClockRateStatus))
        val leases = if (externalDrainLease) Some(Vec(2, new ClockRateDrainLease)) else None
        val backendFault = if (backendFaultInput) Some(Input(UInt(2.W))) else None
    })
    val controls = domains.map(p => Module(new ClockRateControl(p, externalDrainLease, backendFaultInput)))
    controls.zipWithIndex.foreach { case (c, n) =>
        io.leases.foreach(_(n) <> c.io.lease.get)
        io.backendFault.foreach(f => c.io.backendFault.get := f(n))
    }
    private val replies = Module(new Queue(new ClockRateReply, 4, pipe = false, flow = false))
    val delivered = RegInit(VecInit(Seq.fill(2)(false.B)))
    val index = RegInit(VecInit(Seq.fill(2)(0.U(16.W))))
    io.registers.request.ready := replies.io.enq.ready
    io.registers.response.valid := replies.io.deq.valid
    io.registers.response.bits := replies.io.deq.bits.response
    replies.io.deq.ready := io.registers.response.ready
    val req = io.registers.request.bits
    val bank = req.address(7)
    val offset = req.address(6, 3)
    val inRange = req.address >= base.U && req.address < (base + 256).U(65.W)
    val aligned = req.address(2, 0) === 0.U && req.size === 3.U && req.byteEnable === 255.U
    val writeAllowed = offset === 0.U || offset === 3.U || offset === 6.U
    val narrow = !req.data(63, 32).orR
    val selectedError = Mux(bank, controls(1).io.requestError, controls.head.io.requestError)
    val indexLegal = Mux(bank, req.data < domains(1).points.size.U, req.data < domains.head.points.size.U)
    val writeValueLegal = MuxLookup(offset, true.B)(Seq(
        0.U -> narrow, 3.U -> ((req.data & ~ClockRateError.mask.U(64.W)) === 0.U), 6.U -> indexLegal))
    val basicLegal = inRange && aligned && (!req.write || (writeAllowed && writeValueLegal))
    val rateWrite = req.write && offset === 0.U
    val error = !basicLegal || (rateWrite && selectedError =/= 0.U)
    val readData = Wire(Vec(2, UInt(64.W)))
    for (n <- 0 until 2) {
        val c = controls(n)
        io.status(n).requestedHz := c.io.requestedHz; io.status(n).targetHz := c.io.targetHz
        io.status(n).actualHz := c.io.actualHz; io.status(n).errors := c.io.errors
        io.status(n).completed := c.io.completed; io.status(n).state := c.io.state
        io.status(n).actualValid := c.io.actualValid; io.status(n).busy := c.io.busy
        io.status(n).lastSuccess := c.io.lastSuccess
        c.io.endpoint <> io.endpoints(n)
        c.io.submit.bits := req.data(31, 0)
        c.io.submit.valid := io.registers.request.fire && bank === n.U && basicLegal && rateWrite
        val localDelivered = replies.io.deq.fire && replies.io.deq.bits.begins && replies.io.deq.bits.domain === n.U
        c.io.responseCommitted := io.sourceRetired(n) && (delivered(n) || localDelivered)
        when(localDelivered) { delivered(n) := true.B }
        when(c.io.responseCommitted) { delivered(n) := false.B }
        when(io.sourceRetired(n) && !reset.asBool) {
            assert(delivered(n) || localDelivered, "rate receipt preceded local response or lost its owner")
        }
        c.io.clearErrors := Mux(io.registers.request.fire && bank === n.U && basicLegal &&
            req.write && offset === 3.U, req.data(31, 0), 0.U)
        when(io.registers.request.fire && bank === n.U && basicLegal && req.write && offset === 6.U) {
            index(n) := req.data(15, 0)
        }
        val pointHz = MuxLookup(index(n), 0.U(64.W))(domains(n).points.zipWithIndex.map {
            case (p, i) => i.U -> p.hz.U(64.W)
        })
        val pointFlags = MuxLookup(index(n), 0.U(64.W))(domains(n).points.zipWithIndex.map {
            case (p, i) => i.U -> p.flags.U(64.W)
        })
        val status = Cat(c.io.endpoint.present, c.io.state === 8.U, c.io.lastSuccess,
            c.io.endpoint.gateOpen, c.io.endpoint.gateClosed, c.io.endpoint.locked,
            c.io.endpoint.isolate, c.io.endpoint.quiesce, c.io.endpoint.clockEnable, c.io.actualValid, c.io.busy)
        readData(n) := MuxLookup(offset, 0.U(64.W))(Seq(
            0.U -> c.io.requestedHz.pad(64), 1.U -> Mux(c.io.actualValid, c.io.actualHz.pad(64), 0.U), 2.U -> status.pad(64),
            3.U -> c.io.errors.pad(64), 4.U -> c.io.targetHz.pad(64), 5.U -> domains(n).bootHz.U(64.W),
            6.U -> index(n).pad(64), 7.U -> pointHz, 8.U -> pointFlags, 9.U -> domains(n).timeoutCycles.U(64.W),
            10.U -> c.io.completed.pad(64), 11.U -> c.io.state.pad(64), 12.U -> domains(n).maximumHz.U(64.W),
            13.U -> domains(n).minimumHz.U(64.W), 14.U -> domains(n).stepHz.U(64.W),
            15.U -> ((BigInt("4352", 16) << 48) | (BigInt(domains(n).points.size) << 32) | 1).U(64.W)))
    }
    replies.io.enq.valid := io.registers.request.fire
    replies.io.enq.bits.response.error := error
    replies.io.enq.bits.response.data := Mux(basicLegal && !req.write, readData(bank), 0.U)
    replies.io.enq.bits.begins := basicLegal && rateWrite && selectedError === 0.U
    replies.io.enq.bits.domain := bank
}

/** A real complete-request/reply CDC plus a separate source-consumed receipt.
  * The receipt mailbox holds its domain tag until AON consumes it. This avoids
  * equating an AON-side buffered reply with completion at the source boundary.
  * If this boundary is placed behind another bus response queue, that outer
  * owner must also drain before clock stop; this is not CPU-retirement proof.
  */
class ClockRateManagementBoundary(domains: Seq[ClockRateParams], base: BigInt = BigInt("10080800", 16),
    externalDrainLease: Boolean = false, backendFaultInput: Boolean = false)
    extends RawModule {
    val sourceClock = IO(Input(Clock())); val alwaysOnClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val endpoints = IO(Vec(2, new ClockRateEndpoint))
    val status = IO(Output(Vec(2, new ClockRateStatus)))
    val leases = if (externalDrainLease) Some(IO(Vec(2, new ClockRateDrainLease))) else None
    val backendFault = if (backendFaultInput) Some(IO(Input(UInt(2.W)))) else None
    val sourceIdle = if (externalDrainLease) Some(IO(Output(Bool()))) else None
    val aonIdle = if (externalDrainLease) Some(IO(Output(Bool()))) else None
    val bridge = Module(new RegisterClockDomainBridge)
    bridge.sourceClock := sourceClock; bridge.destinationClock := alwaysOnClock; bridge.commonReset := commonReset
    val receipt = Module(new CdcMailbox(1))
    receipt.sourceClock := sourceClock; receipt.destinationClock := alwaysOnClock; receipt.commonReset := commonReset
    val pending = withClockAndReset(sourceClock, bridge.sourceReset) { RegInit(false.B) }
    val receiptBank = withClockAndReset(sourceClock, bridge.sourceReset) { Reg(UInt(1.W)) }
    val ownedBank = withClockAndReset(sourceClock, bridge.sourceReset) { Reg(UInt(1.W)) }
    val ownedRateWrite = withClockAndReset(sourceClock, bridge.sourceReset) { RegInit(false.B) }
    bridge.source.request.valid := registers.request.valid && !pending
    bridge.source.request.bits := registers.request.bits
    registers.request.ready := bridge.source.request.ready && !pending
    registers.response <> bridge.source.response
    receipt.source.valid := pending; receipt.source.bits := receiptBank
    withClockAndReset(sourceClock, bridge.sourceReset) {
        when(registers.request.fire) {
            val r = registers.request.bits
            ownedBank := r.address(7)
            ownedRateWrite := r.write && r.address >= base.U && r.address < (base + 256).U(65.W) &&
                r.address(6, 0) === 0.U
        }
        when(receipt.source.fire) { pending := false.B }
        when(registers.response.fire && ownedRateWrite && !registers.response.bits.error) {
            assert(!pending, "rate receipt storage overwritten")
            receiptBank := ownedBank; pending := true.B
        }
    }
    val rates = withClockAndReset(alwaysOnClock, bridge.destinationReset) {
        Module(new ClockRateManagement(domains, base, externalDrainLease, backendFaultInput))
    }
    rates.io.registers <> bridge.destination
    receipt.destination.ready := true.B
    rates.io.sourceRetired := Mux(receipt.destination.fire, UIntToOH(receipt.destination.bits, 2), 0.U)
    endpoints <> rates.io.endpoints
    status := rates.io.status
    leases.foreach(_ <> rates.io.leases.get)
    backendFault.foreach(f => rates.io.backendFault.get := f)
    sourceIdle.foreach(_ := bridge.sourceIdle && receipt.sourceIdle && !pending &&
        !registers.request.valid && !registers.response.valid)
    aonIdle.foreach(_ := bridge.destinationIdle && receipt.destinationIdle &&
        !rates.io.registers.request.valid && !rates.io.registers.response.valid)
}
