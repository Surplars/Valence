package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.ooo._

/** Real CSR/MRET/trap privilege producer followed by the production translation,
  * request-buffer, physical I-cache and TL path. This is a permission/ownership
  * fixture, not a CPU, ROB exception-selection or performance model. It uses a
  * 64KiB test RAM aperture, four banked I-cache lines and disables the MSU's
  * unused FPU and its otherwise-uninstantiated backend head-sharing option.
  * SATP stays Bare; the VM-capable adapter and sixteen PMP entries remain.
  */
class FetchOwnerPermissionGsim(transactionSlots: Int = 1) extends Module {
    require(Set(1, 2).contains(transactionSlots))
    private val config = FpgaNextConfig.Selected
    private val p = config.coreParams.copy(alignedFetchSinglePage = true,
        floatingPoint = FloatingPointConfig.disabled, experimentalFloatingPoint = false, advertiseFloatingPoint = false,
        shareProtectedHeadPayload = false)
    private val tlp = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    require(p.virtualMemoryLevels == 3 && p.pmpEntries == 16 && p.renameWidth == 2)
    val io = IO(new Bundle {
        val slots = Output(UInt(2.W))
        val start = Input(Bool())
        val instruction = Input(UInt(32.W))
        val operand = Input(UInt(64.W))
        val token = Input(UInt(64.W))
        val systemReady = Output(Bool())
        val complete = Output(Bool())
        val completeException = Output(Bool())
        val completeToken = Output(UInt(64.W))
        val trap = Input(Bool())
        val trapPc = Input(UInt(64.W))
        val trapCause = Input(UInt(64.W))
        val trapReady = Output(Bool())
        val livePrivilege = Output(UInt(2.W))
        val satp = Output(UInt(64.W))
        val cfg0 = Output(UInt(8.W))
        val cfg1 = Output(UInt(8.W))
        val addr0 = Output(UInt(54.W))
        val addr1 = Output(UInt(54.W))
        val requestValid = Input(Bool())
        val requestAddress = Input(UInt(64.W))
        val requestMask = Input(UInt(2.W))
        val requestReady = Output(Bool())
        val responseValid = Output(Bool())
        val responseReady = Input(Bool())
        val responseData = Output(UInt(64.W))
        val responseError = Output(UInt(2.W))
        val responsePageFault = Output(UInt(2.W))
        // Atomic test valve. While closed, the buffer's downstream payload is
        // still a real held offer; no cache offer has been made yet.
        val allowCache = Input(Bool())
        // Test-only mutation, enabled before the first cache offer, never in
        // the middle of an irrevocable held offer. Normal mode is hard-zero.
        val injectCacheContext = Input(Bool())
        // Component contract stimulus only, NOT a legal in-flight MRET path.
        // The real MSU stays M while the cache's otherwise-unused live input is S.
        val forceCacheLiveSupervisor = Input(Bool())
        val cacheLivePrivilege = Output(UInt(2.W))
        val bufferValid = Output(Bool())
        val bufferReady = Output(Bool())
        val bufferAddress = Output(UInt(64.W))
        val bufferMask = Output(UInt(2.W))
        val bufferPrivilege = Output(UInt(2.W))
        val queuedValid = Output(Bool())
        val queuedReady = Output(Bool())
        val queuedAddress = Output(UInt(64.W))
        val queuedMask = Output(UInt(2.W))
        val queuedPrivilege = Output(UInt(2.W))
        val cacheValid = Output(Bool())
        val cacheReady = Output(Bool())
        val cacheAddress = Output(UInt(64.W))
        val cacheMask = Output(UInt(2.W))
        val cachePrivilege = Output(UInt(2.W))
        val physicalResponse = Output(Bool())
        val quiescent = Output(Bool())
        val aValid = Output(Bool())
        val aReady = Input(Bool())
        val aOpcode = Output(UInt(3.W))
        val aAddress = Output(UInt(64.W))
        val aSize = Output(UInt(3.W))
        val aSource = Output(UInt(3.W))
        val aMask = Output(UInt(8.W))
        val dValid = Input(Bool())
        val dReady = Output(Bool())
        val dData = Input(UInt(64.W))
        val dSize = Input(UInt(3.W))
        val dSource = Input(UInt(3.W))
    })
    io.slots := transactionSlots.U
    val system = Module(new MachineSystemUnit(p))
    system.io.start.valid := io.start
    system.io.start.bits := 0.U.asTypeOf(new SystemRequest(p))
    system.io.start.bits.token.tag := io.token
    system.io.start.bits.instruction := io.instruction
    system.io.start.bits.operand := io.operand
    system.io.start.bits.pc := "h80200100".U
    io.systemReady := system.io.start.ready
    system.io.complete.ready := true.B
    io.complete := system.io.complete.valid
    io.completeException := system.io.complete.bits.completion.exception
    io.completeToken := system.io.complete.bits.completion.token.tag
    system.io.imsic.request.ready := true.B
    system.io.imsic.response.valid := false.B
    system.io.imsic.response.bits := 0.U.asTypeOf(system.io.imsic.response.bits)
    system.io.trap.valid := io.trap
    system.io.trap.bits := 0.U.asTypeOf(system.io.trap.bits)
    system.io.trap.bits.pc := io.trapPc
    system.io.trap.bits.cause := io.trapCause
    io.trapReady := system.io.trapReady
    system.io.externalInterrupt := false.B
    system.io.supervisorExternalInterrupt := false.B
    system.io.timerInterrupt := false.B
    system.io.timeValue := 0.U
    system.io.vmFlushReady.foreach(_ := true.B)
    system.io.fenceIFlushReady := true.B
    io.livePrivilege := system.io.fetchPrivilege
    io.satp := system.io.vmState.get.satp
    io.cfg0 := system.io.pmpState.cfg(0)
    io.cfg1 := system.io.pmpState.cfg(1)
    io.addr0 := system.io.pmpState.addr(0)
    io.addr1 := system.io.pmpState.addr(1)

    val adapter = Module(new InstructionTranslationAdapter(p, transactionSlots = transactionSlots,
        withRequestContext = true))
    adapter.io.virtual.request.valid := io.requestValid
    adapter.io.virtual.request.bits := io.requestAddress
    adapter.io.virtual.requestMask := io.requestMask
    io.requestReady := adapter.io.virtual.request.ready
    adapter.io.virtual.response.ready := io.responseReady
    io.responseValid := adapter.io.virtual.response.valid
    io.responseData := adapter.io.virtual.response.bits
    io.responseError := adapter.io.virtual.responseError
    io.responsePageFault := adapter.io.virtual.responsePageFault
    adapter.io.vmState := system.io.vmState.get
    adapter.io.privilege := system.io.fetchPrivilege
    adapter.io.pmpState := system.io.pmpState
    adapter.io.translation.request.ready := false.B
    adapter.io.translation.response.valid := false.B
    adapter.io.translation.response.bits := 0.U.asTypeOf(adapter.io.translation.response.bits)
    when(!reset.asBool) {
        assert(system.io.vmState.get.satp === 0.U, "permission fixture requires real MSU Bare SATP")
        assert(!adapter.io.translation.request.valid, "Bare fetch unexpectedly requested translation")
        when(io.trap) { assert(system.io.trapReady, "host trap issuer overlapped a system command") }
    }
    val requests = Module(new InstructionRequestBuffer(2, flowThrough = true,
        independentCapture = true, withRequestContext = true))
    requests.io.upstream <> adapter.io.physical
    val cache = Module(new InstructionLineCache(tlp, ramBase = BigInt("80200000", 16),
        ramBytes = 65536, romBytes = 128 * 1024, lines = 4, packetWords = 2,
        prefetchEnabled = false, parallelFallbackAddresses = p.parallelFetchAddresses,
        bankedData = config.bankedInstructionData, withRequestContext = true))
    cache.io.fetch.request.valid := requests.io.downstream.request.valid && io.allowCache
    cache.io.fetch.request.bits := requests.io.downstream.request.bits
    cache.io.fetch.requestMask := requests.io.downstream.requestMask
    cache.io.fetch.requestContext.get := requests.io.downstream.requestContext.get
    val cacheLivePrivilege = Mux(io.forceCacheLiveSupervisor, 1.U(2.W), system.io.fetchPrivilege)
    io.cacheLivePrivilege := cacheLivePrivilege
    when(io.injectCacheContext) {
        cache.io.fetch.requestContext.get.privilege := cacheLivePrivilege
    }
    requests.io.downstream.request.ready := cache.io.fetch.request.ready && io.allowCache
    requests.io.downstream.response <> cache.io.fetch.response
    requests.io.downstream.responseError := cache.io.fetch.responseError
    requests.io.downstream.responsePageFault := cache.io.fetch.responsePageFault
    cache.io.pmpState := system.io.pmpState
    cache.io.privilege := cacheLivePrivilege
    cache.io.invalidate := system.io.complete.fire && system.io.complete.bits.invalidateFetch

    io.bufferValid := adapter.io.physical.request.valid
    io.bufferReady := adapter.io.physical.request.ready
    io.bufferAddress := adapter.io.physical.request.bits
    io.bufferMask := adapter.io.physical.requestMask
    io.bufferPrivilege := adapter.io.physical.requestContext.get.privilege
    io.queuedValid := requests.io.downstream.request.valid
    io.queuedReady := requests.io.downstream.request.ready
    io.queuedAddress := requests.io.downstream.request.bits
    io.queuedMask := requests.io.downstream.requestMask
    io.queuedPrivilege := requests.io.downstream.requestContext.get.privilege
    io.cacheValid := cache.io.fetch.request.valid
    io.cacheReady := cache.io.fetch.request.ready
    io.cacheAddress := cache.io.fetch.request.bits
    io.cacheMask := cache.io.fetch.requestMask
    io.cachePrivilege := cache.io.fetch.requestContext.get.privilege
    io.physicalResponse := adapter.io.physical.response.fire
    io.quiescent := adapter.io.idle && cache.io.idle && !requests.io.downstream.request.valid
    val csrAddress = io.instruction(31, 20)
    val pmpWrite = io.instruction(6, 0) === "h73".U && io.instruction(14, 12) =/= 0.U &&
        (csrAddress === "h3a0".U || (csrAddress >= "h3b0".U && csrAddress < "h3c0".U))
    when(system.io.start.fire && pmpWrite) {
        assert(io.quiescent, "PMP programming must precede all pending fetch owners")
    }
    // The valve must not withdraw a visible cache request or mutate its payload.
    val cachePayload = Cat(cache.io.fetch.request.bits, cache.io.fetch.requestMask,
        cache.io.fetch.requestContext.get.asUInt)
    val cacheHeld = RegNext(cache.io.fetch.request.valid && !cache.io.fetch.request.ready, false.B)
    val heldPayload = RegEnable(cachePayload, cache.io.fetch.request.valid && !cache.io.fetch.request.ready)
    when(cacheHeld && !reset.asBool) {
        assert(cache.io.fetch.request.valid && cachePayload === heldPayload,
            "fixture changed an irrevocable cache offer")
    }

    io.aValid := cache.io.tl.a.valid
    cache.io.tl.a.ready := io.aReady
    io.aOpcode := cache.io.tl.a.bits.opcode
    io.aAddress := cache.io.tl.a.bits.address
    io.aSize := cache.io.tl.a.bits.size
    io.aSource := cache.io.tl.a.bits.source
    io.aMask := cache.io.tl.a.bits.mask
    cache.io.tl.d.valid := io.dValid
    cache.io.tl.d.bits := 0.U.asTypeOf(cache.io.tl.d.bits)
    cache.io.tl.d.bits.opcode := TLOpcode.AccessAckData
    cache.io.tl.d.bits.source := io.dSource
    cache.io.tl.d.bits.size := io.dSize
    cache.io.tl.d.bits.data := io.dData
    io.dReady := cache.io.tl.d.ready
    cache.io.tl.b.valid := false.B
    cache.io.tl.b.bits := 0.U.asTypeOf(cache.io.tl.b.bits)
    cache.io.tl.c.ready := false.B
    cache.io.tl.e.ready := false.B
}

object FetchOwnerPermissionGsimMain extends App {
    require(args.length == 2, "usage: FetchOwnerPermissionGsimMain output-dir slots")
    ChiselStage.emitCHIRRTLFile(new FetchOwnerPermissionGsim(args(1).toInt), Array("--target-dir", args(0)))
}
