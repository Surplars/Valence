package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Uniform observation ABI only. Absent production handle/metadata fields are
  * tied to zero, never modeled with an extra queue or a second owner register.
  */
class MemoryDomainSelectorLane(p: OooParams) extends Bundle {
    val acceptedStart = Input(Valid(new ProtectedSystemStart(p)))
    val acceptedComplete = Input(Valid(new RobToken(p)))
    val commit0 = Input(Valid(new RobToken(p)))
    val commit1 = Input(Valid(new RobToken(p)))
    val integer = Flipped(new DataPort(5))
    val h = Flipped(new DataPort(5))
    val fp = Flipped(new DataPort(5))
    val memory = new DataPort(5)
    val guestFault = Input(new GuestFaultMetadata)
    val integerFault = Output(new GuestFaultMetadata)
    val hFault = Output(new GuestFaultMetadata)
    val fpFault = Output(new GuestFaultMetadata)
    val integerBusy = Input(Bool())
    val hBusy = Input(Bool())
    val fpMemoryBusy = Input(Bool())
    val postedBusy = Input(Bool())
    val prefetchBusy = Input(Bool())
    val architecturalFpBusy = Input(Bool())
    val busy = Output(Bool())
    val cpuBusy = Output(Bool())
    val architectureOnly = Output(Bool())
    val ownerActive = Output(Bool())
    val ownerToken = Output(new RobToken(p))
    val contextMemoryEpoch = Output(Bool())
    val hMemoryEpoch = Output(Bool())
    val fpMemoryEpoch = Output(Bool())
    val domain = Output(UInt(2.W))
    val retired = Output(Bool())
    val retireMatches = Output(UInt(2.W))
    val decodedHLoad = Output(Bool())
    val decodedHStore = Output(Bool())
    val decodedHMemory = Output(Bool())
    val decodedFpMemory = Output(Bool())
}

/** Production selector + production protected owner, not an executing CPU.
  * Start/complete/commit inputs are the already-accepted backend boundary
  * events. The C++ driver supplies only legal success lifetimes. Synthetic
  * response fault bits prove transport, not guest trap precision. No cancel,
  * exception release, reset-with-owner, MSU, ROB, dual FS or numerical FP model.
  */
class MemoryDomainSelectorGsim extends Module {
    private val guestParams = OooParams(robEntries = 16, tagBits = 64, machineSystem = true,
        hypervisorExperiment = true, floatingPoint = FloatingPointConfig.fullFD)
    private val hostParams = guestParams.copy(hypervisorExperiment = false,
        memoryEntries = 8, storeBufferEntries = 8, bufferedRamStores = true,
        speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 65536,
        registeredMemoryRequests = true, registeredStoreResponseOwners = true, taggedStoreReturns = true)
    val io = IO(new Bundle {
        val guest = new MemoryDomainSelectorLane(guestParams)
        val host = new MemoryDomainSelectorLane(hostParams)
    })
    for ((lane, p) <- Seq(io.guest -> guestParams, io.host -> hostParams)) {
        val owner = Module(new ProtectedSystemOwner(p))
        val selector = Module(new MemoryDomainSelector(p))
        owner.io.start := lane.acceptedStart
        owner.io.complete.valid := lane.acceptedComplete.valid
        owner.io.complete.bits := 0.U.asTypeOf(new BackendCompletion(p))
        owner.io.complete.bits.token := lane.acceptedComplete.bits
        owner.io.commits(0) := lane.commit0
        owner.io.commits(1) := lane.commit1
        selector.io.hMemoryEpoch := owner.io.hMemoryEpoch
        selector.io.fpMemoryEpoch := owner.io.fpMemoryEpoch
        selector.io.integerBusy := lane.integerBusy
        selector.io.hBusy := lane.hBusy
        selector.io.fpMemoryBusy := lane.fpMemoryBusy
        selector.io.postedBusy := lane.postedBusy
        selector.io.prefetchBusy := lane.prefetchBusy
        selector.io.guestFault.foreach(_ := lane.guestFault)
        lane.integerFault := selector.io.integerGuestFault.getOrElse(0.U.asTypeOf(new GuestFaultMetadata))
        lane.hFault := selector.io.hGuestFault.getOrElse(0.U.asTypeOf(new GuestFaultMetadata))
        lane.fpFault := selector.io.fpGuestFault.getOrElse(0.U.asTypeOf(new GuestFaultMetadata))

        // Adapt width only. Every actual route, acceptance gate and owner bit
        // comes from the production helpers used by IntegerBackend.
        def client(external: DataPort, actual: DataPort): Unit = {
            actual.request.valid := external.request.valid
            external.request.ready := actual.request.ready
            CpuReturnTransport.requestPayload(actual.request.bits, external.request.bits)
            actual.request.bits.returnHandle.foreach(_ := external.request.bits.returnHandle.get)
            external.response.valid := actual.response.valid
            actual.response.ready := external.response.ready
            CpuReturnTransport.responsePayload(external.response.bits, actual.response.bits)
            external.response.bits.returnHandle.get := actual.response.bits.returnHandle.getOrElse(0.U)
        }
        client(lane.integer, selector.io.integer)
        client(lane.fp, selector.io.fp.get)
        selector.io.h match {
            case Some(h) => client(lane.h, h)
            case None =>
                lane.h.request.ready := false.B
                lane.h.response.valid := false.B
                lane.h.response.bits := 0.U.asTypeOf(lane.h.response.bits)
        }
        lane.memory.request.valid := selector.io.memory.request.valid
        selector.io.memory.request.ready := lane.memory.request.ready
        CpuReturnTransport.requestPayload(lane.memory.request.bits, selector.io.memory.request.bits)
        lane.memory.request.bits.returnHandle.get := selector.io.memory.request.bits.returnHandle.getOrElse(0.U)
        selector.io.memory.response.valid := lane.memory.response.valid
        lane.memory.response.ready := selector.io.memory.response.ready
        CpuReturnTransport.responsePayload(selector.io.memory.response.bits, lane.memory.response.bits)
        selector.io.memory.response.bits.returnHandle.foreach(_ := lane.memory.response.bits.returnHandle.get)
        lane.busy := selector.io.busy
        lane.cpuBusy := selector.io.cpuBusy
        lane.architectureOnly := lane.architecturalFpBusy && !selector.io.busy
        lane.ownerActive := owner.io.active
        lane.ownerToken := owner.io.token
        lane.contextMemoryEpoch := owner.io.contextMemoryEpoch
        lane.hMemoryEpoch := owner.io.hMemoryEpoch
        lane.fpMemoryEpoch := owner.io.fpMemoryEpoch
        lane.domain := selector.io.domain
        lane.retired := owner.io.retired
        lane.retireMatches := owner.io.retireMatches.asUInt
        lane.decodedHLoad := HypervisorInstruction.load(lane.acceptedStart.bits.instruction)
        lane.decodedHStore := HypervisorInstruction.store(lane.acceptedStart.bits.instruction)
        lane.decodedHMemory := HypervisorInstruction.memory(lane.acceptedStart.bits.instruction)
        lane.decodedFpMemory := FloatingPointSubset.memory(lane.acceptedStart.bits.instruction)
    }
}

object MemoryDomainSelectorGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new MemoryDomainSelectorGsim, Array("--target-dir", args.head))
}
