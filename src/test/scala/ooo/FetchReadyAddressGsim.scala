package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Standalone instruction owner boundary; translation and physical-memory
  * responses come from the independent software fixture, not a DUT TLB.
  */
class FetchReadyAddressGsim extends Module {
    private val words = 2
    private val retimed = true
    private val aligned = true
    private val turnover = true
    private val identity = true
    require(Set(2, 4).contains(words))
    val io = IO(new Bundle {
        val virtualValid = Input(Bool())
        val virtualPc = Input(UInt(64.W))
        val virtualMask = Input(UInt(4.W))
        val virtualReady = Output(Bool())
        val virtualResponseReady = Input(Bool())
        val virtualResponseValid = Output(Bool())
        val virtualResponseLow = Output(UInt(64.W))
        val virtualResponseHigh = Output(UInt(64.W))
        val virtualErrors = Output(UInt(4.W))
        val virtualPages = Output(UInt(4.W))
        val satp = Input(UInt(64.W))
        val sum = Input(Bool())
        val mxr = Input(Bool())
        val privilege = Input(UInt(2.W))
        val cfg0 = Input(UInt(8.W))
        val cfg1 = Input(UInt(8.W))
        val addr0 = Input(UInt(54.W))
        val addr1 = Input(UInt(54.W))
        val translationReady = Input(Bool())
        val translationValid = Output(Bool())
        val translationPc = Output(UInt(64.W))
        val translationRoot = Output(UInt(44.W))
        val translationAsid = Output(UInt(16.W))
        val translationMode = Output(UInt(4.W))
        val translationPrivilege = Output(UInt(2.W))
        val translationAccess = Output(UInt(2.W))
        val translationSum = Output(Bool())
        val translationMxr = Output(Bool())
        val translationResponseValid = Input(Bool())
        val translationPhysical = Input(UInt(64.W))
        val translationPage = Input(Bool())
        val translationError = Input(Bool())
        val translationResponseReady = Output(Bool())
        val physicalReady = Input(Bool())
        val physicalValid = Output(Bool())
        val physicalPc = Output(UInt(64.W))
        val physicalMask = Output(UInt(4.W))
        val physicalResponseValid = Input(Bool())
        val physicalResponseLow = Input(UInt(64.W))
        val physicalResponseHigh = Input(UInt(64.W))
        val physicalErrors = Input(UInt(4.W))
        val physicalPages = Input(UInt(4.W))
        val physicalResponseReady = Output(Bool())
        val idle = Output(Bool())
        val readyClearIdleDifference = Output(Bool())
    })
    val p = OooParams(renameWidth = words, commitWidth = words, completionWidth = words,
        compressedInstructions = words == 4 || aligned, machineSystem = true,
        pmpEntries = 16, virtualMemoryLevels = 4, alignedFetchPmp = aligned,
        bufferedFetchRequests = retimed, flowThroughFetchRequests = retimed,
        independentFetchCapture = retimed, parallelHomeQualification = retimed,
        registeredFabricBoundary = retimed, registeredTranslatedResponses = retimed,
        registeredTranslationHeads = retimed, fetchReplyTurnover = turnover,
        fetchIdentityTranslation = identity, alignedFetchSinglePage = true, fetchReadyDataClear = true)
    val adapter = Module(new InstructionTranslationAdapter(p))
    adapter.io.virtual.request.valid := io.virtualValid
    adapter.io.virtual.request.bits := io.virtualPc
    adapter.io.virtual.requestMask := io.virtualMask(words - 1, 0)
    io.virtualReady := adapter.io.virtual.request.ready
    adapter.io.virtual.response.ready := io.virtualResponseReady
    io.virtualResponseValid := adapter.io.virtual.response.valid
    io.virtualResponseLow := adapter.io.virtual.response.bits(63, 0)
    io.virtualResponseHigh := (if (words == 4) adapter.io.virtual.response.bits(127, 64) else 0.U)
    io.virtualErrors := adapter.io.virtual.responseError
    io.virtualPages := adapter.io.virtual.responsePageFault
    adapter.io.vmState := 0.U.asTypeOf(new VmCsrState)
    adapter.io.vmState.satp := io.satp
    adapter.io.vmState.sum := io.sum
    adapter.io.vmState.mxr := io.mxr
    adapter.io.privilege := io.privilege
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.cfg0
    pmp.cfg(1) := io.cfg1
    pmp.addr(0) := io.addr0
    pmp.addr(1) := io.addr1
    PmpState.decodeRegions(pmp)
    adapter.io.pmpState := pmp
    adapter.io.translation.request.ready := io.translationReady
    io.translationValid := adapter.io.translation.request.valid
    val translation = adapter.io.translation.request.bits
    io.translationPc := translation.virtualAddress
    io.translationRoot := translation.rootPpn
    io.translationAsid := translation.asid
    io.translationMode := translation.mode
    io.translationPrivilege := translation.privilege
    io.translationAccess := translation.access
    io.translationSum := translation.sum
    io.translationMxr := translation.mxr
    adapter.io.translation.response.valid := io.translationResponseValid
    adapter.io.translation.response.bits := 0.U.asTypeOf(new SvTranslationResponse)
    adapter.io.translation.response.bits.physicalAddress := io.translationPhysical
    adapter.io.translation.response.bits.pageFault := io.translationPage
    adapter.io.translation.response.bits.accessFault := io.translationError
    io.translationResponseReady := adapter.io.translation.response.ready
    adapter.io.physical.request.ready := io.physicalReady
    io.physicalValid := adapter.io.physical.request.valid
    io.physicalPc := adapter.io.physical.request.bits
    io.physicalMask := adapter.io.physical.requestMask
    adapter.io.physical.response.valid := io.physicalResponseValid
    adapter.io.physical.response.bits := (if (words == 4)
        Cat(io.physicalResponseHigh, io.physicalResponseLow) else io.physicalResponseLow)
    adapter.io.physical.responseError := io.physicalErrors(words - 1, 0)
    adapter.io.physical.responsePageFault := io.physicalPages(words - 1, 0)
    io.physicalResponseReady := adapter.io.physical.response.ready
    io.idle := adapter.io.idle
    // Frozen pre-candidate hardware is a second check. All responses still
    // originate from the independent software byte-range/owner oracle.
    val reference = Module(new FrozenFetchAdapterBeforeReadyCapture(p))
    reference.io.virtual.request.valid := adapter.io.virtual.request.valid
    reference.io.virtual.request.bits := adapter.io.virtual.request.bits
    reference.io.virtual.requestMask := adapter.io.virtual.requestMask
    reference.io.virtual.response.ready := adapter.io.virtual.response.ready
    reference.io.vmState := adapter.io.vmState
    reference.io.privilege := adapter.io.privilege
    reference.io.pmpState := adapter.io.pmpState
    reference.io.translation.request.ready := adapter.io.translation.request.ready
    reference.io.translation.response.valid := adapter.io.translation.response.valid
    reference.io.translation.response.bits := adapter.io.translation.response.bits
    reference.io.physical.request.ready := adapter.io.physical.request.ready
    reference.io.physical.response.valid := adapter.io.physical.response.valid
    reference.io.physical.response.bits := adapter.io.physical.response.bits
    reference.io.physical.responseError := adapter.io.physical.responseError
    reference.io.physical.responsePageFault := adapter.io.physical.responsePageFault
    assert(adapter.io.idle === reference.io.idle &&
        adapter.io.virtual.request.ready === reference.io.virtual.request.ready &&
        adapter.io.virtual.response.valid === reference.io.virtual.response.valid,
        "ready PA capture changed owner admission/retirement")
    assert(adapter.io.translation.request.valid === reference.io.translation.request.valid &&
        adapter.io.translation.response.ready === reference.io.translation.response.ready &&
        adapter.io.physical.request.valid === reference.io.physical.request.valid &&
        adapter.io.physical.response.ready === reference.io.physical.response.ready,
        "ready PA capture changed translation/physical handshakes")
    when(adapter.io.translation.request.valid) {
        assert(adapter.io.translation.request.bits.asUInt === reference.io.translation.request.bits.asUInt,
            "ready PA capture changed live translation context")
    }
    when(adapter.io.physical.request.valid) {
        assert(adapter.io.physical.request.bits === reference.io.physical.request.bits &&
            adapter.io.physical.requestMask === reference.io.physical.requestMask,
            "ready PA capture changed physical permission/address/mask")
    }
    when(!adapter.io.idle) {
        assert(adapter.io.virtual.response.bits === reference.io.virtual.response.bits,
            "ready PA capture changed owned response data")
    }
    when(adapter.io.virtual.response.valid) {
        assert(adapter.io.virtual.responseError === reference.io.virtual.responseError &&
            adapter.io.virtual.responsePageFault === reference.io.virtual.responsePageFault,
            "ready PA capture changed held response faults")
    }
    val seenOwner = RegInit(false.B)
    when(adapter.io.virtual.request.fire) { seenOwner := true.B }
    // Retain the old host port spelling only for fixture compatibility. This
    // witness is PA dead-payload divergence, not response-data clearing.
    io.readyClearIdleDifference := seenOwner && adapter.io.idle &&
        adapter.io.physical.request.bits =/= reference.io.physical.request.bits
}

object FetchReadyAddressGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchReadyAddressGsim, Array("--target-dir", args.head))
}
