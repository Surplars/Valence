package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.ip.bus._

/** Source-domain CMU page extension. The chosen reply reaches READY only when
  * the same upstream owner consumes it. This preserves the rate boundary's
  * end-to-end receipt; it never acknowledges a reply into an intermediate FIFO.
  */
class ClockRateRegisterRouter(rateBase: BigInt = BigInt("10080800", 16)) extends Module {
    require(rateBase >= 0 && rateBase % 256 == 0 && rateBase + 256 < (BigInt(1) << 64))
    val io = IO(new Bundle {
        val upstream = Flipped(new RegisterPort)
        val legacy = new RegisterPort
        val rates = new RegisterPort
        val idle = Output(Bool())
    })
    val owners = Module(new Queue(Bool(), 4, pipe = false, flow = false))
    val request = io.upstream.request
    val selectedRate = request.bits.address >= rateBase.U && request.bits.address < (rateBase + 256).U(65.W)
    io.legacy.request.bits := request.bits
    io.rates.request.bits := request.bits
    io.legacy.request.valid := request.valid && owners.io.enq.ready && !selectedRate
    io.rates.request.valid := request.valid && owners.io.enq.ready && selectedRate
    request.ready := owners.io.enq.ready && Mux(selectedRate, io.rates.request.ready, io.legacy.request.ready)
    owners.io.enq.valid := request.fire
    owners.io.enq.bits := selectedRate
    val rateOwner = owners.io.deq.bits
    io.upstream.response.valid := owners.io.deq.valid && Mux(rateOwner, io.rates.response.valid, io.legacy.response.valid)
    io.upstream.response.bits := Mux(rateOwner, io.rates.response.bits, io.legacy.response.bits)
    io.rates.response.ready := owners.io.deq.valid && rateOwner && io.upstream.response.ready
    io.legacy.response.ready := owners.io.deq.valid && !rateOwner && io.upstream.response.ready
    owners.io.deq.ready := io.upstream.response.fire
    io.idle := owners.io.count === 0.U && !request.valid
}

/** Integration fixture/reusable bank: existing CMU and rate component are
  * unchanged blocks. Control inputs belong to AON; upstream belongs to source.
  */
class ClockManagementWithRatesBoundary(config: CmuParams, domains: Seq[ClockRateParams]) extends RawModule {
    val sourceClock = IO(Input(Clock())); val alwaysOnClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val resources = IO(Vec(config.resources.size, new ClockResourceControl))
    val irq = IO(Output(Bool()))
    val endpoints = IO(Vec(2, new ClockRateEndpoint))
    val status = IO(Output(Vec(2, new ClockRateStatus)))
    val release = Module(new CdcResetRelease)
    release.clockIn := sourceClock; release.asyncReset := commonReset
    val router = withClockAndReset(sourceClock, release.resetOut) {
        Module(new ClockRateRegisterRouter(config.base + 0x800))
    }
    router.io.upstream <> registers
    val legacy = Module(new ClockManagementBoundary(config))
    legacy.sourceClock := sourceClock; legacy.alwaysOnClock := alwaysOnClock; legacy.commonReset := commonReset
    legacy.registers <> router.io.legacy
    resources <> legacy.resources; irq := legacy.irq
    val rates = Module(new ClockRateManagementBoundary(domains, config.base + 0x800))
    rates.sourceClock := sourceClock; rates.alwaysOnClock := alwaysOnClock; rates.commonReset := commonReset
    rates.registers <> router.io.rates
    endpoints <> rates.endpoints; status := rates.status
}
