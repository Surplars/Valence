package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational selection for the existing integer / explicit-H / FP epochs.
  *
  * The protected SYSTEM owner supplies stable epochs, never client valid/busy.
  * There is no queue, extra credit, arbitration policy or mandatory cycle here.
  * Integer reservations remain in ParallelLoadStoreUnit; H and FP use drained,
  * head-serialized epochs through successful retirement. Response payload and
  * provenance have exactly the selected response handshake's authority. Idle
  * clients may see those bits, but never response.valid or request.ready.
  * Tagged handles remain a host-only integer/FP reservation namespace.
  */
class MemoryDomainSelector(p: OooParams) extends Module {
    require(!p.hypervisorExperiment || p.cpuReturnConfig.isEmpty,
        "explicit-H memory retains the untagged native port")
    val io = IO(new Bundle {
        val integer = Flipped(new DataPort(p.dataReturnHandleBits))
        val h = if (p.hypervisorExperiment) Some(Flipped(new DataPort)) else None
        val fp = if (p.fpEnabled) Some(Flipped(new DataPort)) else None
        val memory = new DataPort(p.dataReturnHandleBits)
        val hMemoryEpoch = Input(Bool())
        val fpMemoryEpoch = Input(Bool())
        val integerBusy = Input(Bool())
        val hBusy = Input(Bool())
        val fpMemoryBusy = Input(Bool())
        val postedBusy = Input(Bool())
        val prefetchBusy = Input(Bool())
        val busy = Output(Bool())
        val cpuBusy = Output(Bool())
        val domain = Output(UInt(2.W)) // Integer=0, explicit-H=1, FP memory=2.
        val guestFault = if (p.hypervisorExperiment) Some(Input(new GuestFaultMetadata)) else None
        val integerGuestFault = if (p.hypervisorExperiment) Some(Output(new GuestFaultMetadata)) else None
        val hGuestFault = if (p.hypervisorExperiment) Some(Output(new GuestFaultMetadata)) else None
        val fpGuestFault = if (p.hypervisorExperiment && p.fpEnabled)
            Some(Output(new GuestFaultMetadata)) else None
    })

    val hEpoch = if (p.hypervisorExperiment) io.hMemoryEpoch else false.B
    val fpEpoch = if (p.fpEnabled) io.fpMemoryEpoch else false.B
    val integerEpoch = !hEpoch && !fpEpoch
    assert(!(hEpoch && fpEpoch), "H and FP cannot own the native memory port together")
    when(hEpoch || fpEpoch) {
        assert(!io.integerBusy, "integer memory must drain before protected memory ownership")
    }
    io.domain := Mux(hEpoch, 1.U, Mux(fpEpoch, 2.U, 0.U))

    val clients = Seq(integerEpoch -> io.integer) ++
        io.h.toSeq.map(hEpoch -> _) ++ io.fp.toSeq.map(fpEpoch -> _)
    io.memory.request.valid := clients.map { case (selected, port) => selected && port.request.valid }.reduce(_ || _)
    val payloads = clients.map { case (selected, port) =>
        val payload = Wire(new DataRequest)
        CpuReturnTransport.requestPayload(payload, port.request.bits)
        selected -> payload
    }
    CpuReturnTransport.requestPayload(io.memory.request.bits, Mux1H(payloads))
    io.memory.request.bits.returnHandle.foreach { handle =>
        handle := Mux(fpEpoch, p.cpuReturnConfig.get.fpHandle.U, io.integer.request.bits.returnHandle.get)
    }
    for ((selected, port) <- clients) {
        port.request.ready := selected && io.memory.request.ready
        port.response.valid := selected && io.memory.response.valid
        CpuReturnTransport.responsePayload(port.response.bits, io.memory.response.bits)
    }
    io.integer.response.bits.returnHandle.foreach(_ := io.memory.response.bits.returnHandle.get)
    io.memory.response.ready := clients.map { case (selected, port) => selected && port.response.ready }.reduce(_ || _)
    io.integerGuestFault.foreach(_ := io.guestFault.get)
    io.hGuestFault.foreach(_ := io.guestFault.get)
    io.fpGuestFault.foreach(_ := io.guestFault.get)
    p.cpuReturnConfig.foreach { config =>
        when(fpEpoch && io.memory.response.valid) {
            assert(io.memory.response.bits.returnHandle.get === config.fpHandle.U,
                "exclusive FP response lost its drained domain")
        }
    }

    // Architectural FP busy is intentionally absent: a faulted FP owner stays
    // busy until the precise trap, whose admission itself waits for this drain.
    io.cpuBusy := io.integerBusy || io.hBusy || io.fpMemoryBusy || io.postedBusy
    io.busy := io.cpuBusy || io.prefetchBusy
}
