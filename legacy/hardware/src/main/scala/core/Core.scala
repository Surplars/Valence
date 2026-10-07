package soc.core

import chisel3._
import chisel3.util._

import csr.CSRFile
import pipeline._
import soc.bus.tilelink.TLParams
import soc.bus.tilelink.TLTransTracker
import soc.bus.tilelink.TLBundle
import soc.bus.tilelink.TLSystemXbar
import soc.memory.cache.HasCacheCoreIO
import soc.memory.cache.L1Cache
import soc.memory.cache.UncachedTileLinkBridge
import soc.debug.DebugCacheControl
import soc.config.Config
import soc.config.SoCFeatures
import soc.isa.Extension
import soc.isa.MCause

class Core(
    XLEN: Int,
    hartID: Int,
    features: SoCFeatures = Config.features,
    enabledExt: Set[Extension.Value] = Config.enabledExt
) extends Module {
    private val tlParams = TLParams()
    private val hasICache = features.iCache
    private val hasDCache = features.dCache
    private val hasFrontendQueue = features.frontendQueueEntries > 0
    private val nMasters = 2 + (if (hasICache) 1 else 0) // dcache, tracker, optional icache
    private val dbusParams = tlParams.copy(sourceBits = tlParams.sourceBits + log2Ceil(nMasters))

    val io = IO(new Bundle {
        val instr = Input(UInt(64.W))
        val debug_instr = Output(UInt(32.W))

        val fetch_en = Output(Bool())
        val pc       = Output(UInt(XLEN.W))
        val debug_retire = Output(Bool())
        val debug_stall = Output(Bool())
        val debug_ifetch_stall = Output(Bool())
        val debug_frontend_starved = Output(Bool())
        val debug_frontend_queue_full = Output(Bool())
        val debug_frontend_queue_empty = Output(Bool())
        val debug_lsu_stall = Output(Bool())
        val debug_lsu_load_stall = Output(Bool())
        val debug_lsu_store_stall = Output(Bool())
        val debug_lsu_mmio_stall = Output(Bool())
        val debug_lsu_atomic_stall = Output(Bool())
        val debug_lsu_fence_stall = Output(Bool())
        val debug_fence_i_active = Output(Bool())
        val debug_branch_valid = Output(Bool())
        val debug_branch_taken = Output(Bool())
        val debug_branch_redirect = Output(Bool())
        val debug_branch_pred_taken = Output(Bool())
        val debug_branch_pred_correct = Output(Bool())
        val debug_commit_pc = Output(UInt(XLEN.W))
        val debug_commit_instr = Output(UInt(32.W))
        val debug_commit_instr_len = Output(UInt(2.W))
        val debug_commit_wen = Output(Bool())
        val debug_commit_wdest = Output(UInt(5.W))
        val debug_commit_wdata = Output(UInt(XLEN.W))
        val debug_commit_skip = Output(Bool())
        val debug_arch_event_valid = Output(Bool())
        val debug_arch_event_interrupt = Output(Bool())
        val debug_arch_event_cause = Output(UInt(XLEN.W))
        val debug_arch_event_pc = Output(UInt(XLEN.W))
        val debug_arch_event_instr = Output(UInt(32.W))
        val debug_arch_event_tval = Output(UInt(XLEN.W))
        val debug_gpr_snapshot = Output(Vec(32, UInt(XLEN.W)))
        val debug_csr_snapshot = Output(new soc.core.csr.CsrStateSnapshot(XLEN))

        val IBus = new TLBundle(tlParams)
        val DBus = new TLBundle(dbusParams)

        val msip = Input(Bool())
        val mtip = Input(Bool())
        val meip = Input(Bool())
        val ssip = Input(Bool())
        val stip = Input(Bool())
        val seip = Input(Bool())
        val debug_haltreq = Input(Bool())
        val debug_resumereq = Input(Bool())
        val debug_halted = Output(Bool())
        val debug_gpr_addr = Input(UInt(5.W))
        val debug_gpr_rdata = Output(UInt(XLEN.W))
        val debug_gpr_write = Input(Bool())
        val debug_gpr_wdata = Input(UInt(XLEN.W))
        val debug_csr_addr = Input(UInt(12.W))
        val debug_csr_rdata = Output(UInt(XLEN.W))
        val debug_csr_valid = Output(Bool())
        val debug_csr_writable = Output(Bool())
        val debug_csr_write = Input(Bool())
        val debug_csr_wdata = Input(UInt(XLEN.W))
        val debug_cache = Flipped(new DebugCacheControl)
    })

    val dcache: HasCacheCoreIO = if (hasDCache) {
        Module(new L1Cache(tlParams, features.dCacheSets, useTLCoherence = features.coherentCaches))
    } else {
        Module(new UncachedTileLinkBridge(tlParams))
    }
    val tracker = Module(new TLTransTracker(tlParams, maxInFlight = 1 << tlParams.sourceBits))
    val dbusXbar = Module(new TLSystemXbar(tlParams, nMasters))
    val icache = if (hasICache) Some(Module(new L1Cache(tlParams, features.iCacheSets, useTLCoherence = features.coherentCaches))) else None

    val pc       = Module(new PC(XLEN, soc.config.Config.resetVector))
    val register = Module(new RegisterFile(XLEN))
    val csr      = Module(new CSRFile(XLEN, hartID, enabledExt, features))

    val ifetch  = Module(new InstrFetch(XLEN, useCache = hasICache, useCompressed = enabledExt.contains(Extension.C)))
    val idecode = Module(new InstrDecode(XLEN, enabledExt))
    val alu     = Module(new ALU(XLEN))
    val lsu     = Module(new LSU(XLEN, features))
    val wb      = Module(new WirteBack(XLEN))
    val satpBarrier = Module(new SatpWriteBarrier(XLEN))

    // Global stall includes both memory-stage backpressure and optional
    // instruction-cache fetch backpressure.
    val global_stall = Wire(Bool())
    val pipe_stall = Wire(Bool())
    val debugHalted = RegInit(false.B)

    dontTouch(register.io)
    dontTouch(idecode.io)
    dontTouch(wb.io)

    val fenceIReq = alu.io.valid_out && alu.io.alu_out.mem.valid && alu.io.alu_out.mem.op === MemOpType.FenceI
    val debugDcachePending = RegInit(false.B)
    val debugDcacheIssued = RegInit(false.B)
    val debugDcacheAck = WireInit(false.B)
    val debugDcacheErr = RegInit(false.B)
    val debugIcachePending = RegInit(false.B)
    val debugIcacheIssued = RegInit(false.B)
    val debugIcacheAck = WireInit(false.B)
    val debugIcacheErr = RegInit(false.B)

    when(io.debug_cache.dcacheReq && !debugDcachePending) {
        debugDcachePending := true.B
        debugDcacheIssued := false.B
        debugDcacheErr := false.B
    }.elsewhen(debugDcacheAck) {
        debugDcachePending := false.B
        debugDcacheIssued := false.B
    }
    when(io.debug_cache.icacheReq && !debugIcachePending) {
        debugIcachePending := true.B
        debugIcacheIssued := false.B
        debugIcacheErr := false.B
    }.elsewhen(debugIcacheAck) {
        debugIcachePending := false.B
        debugIcacheIssued := false.B
    }

    val fenceIPending = RegInit(false.B)
    val fenceIDcacheIssued = RegInit(false.B)
    val fenceIDcacheDone = RegInit(false.B)
    val fenceIFlushIssued = RegInit(false.B)
    val fenceIStart = fenceIReq && !fenceIPending && !fenceIFlushIssued
    val fenceIDcacheFlushValid = WireInit(false.B)
    val fenceIDcacheAck = WireInit(false.B)
    val fenceIInvalidateFire = WireInit(false.B)
    val fenceIAck = WireInit(false.B)

    when(fenceIAck) {
        fenceIPending := false.B
    }.elsewhen(fenceIStart) {
        fenceIPending := true.B
    }
    when(fenceIAck) {
        fenceIDcacheIssued := false.B
        fenceIDcacheDone := false.B
    }.elsewhen(fenceIDcacheAck) {
        fenceIDcacheIssued := false.B
        fenceIDcacheDone := true.B
    }.elsewhen(fenceIDcacheFlushValid && dcache.io.invalidate.fire) {
        fenceIDcacheIssued := true.B
    }.elsewhen(fenceIStart) {
        fenceIDcacheIssued := false.B
        fenceIDcacheDone := !hasDCache.B
    }
    when(fenceIAck) {
        fenceIFlushIssued := false.B
    }.elsewhen(fenceIInvalidateFire) {
        fenceIFlushIssued := true.B
    }

    // fence.i is a frontend barrier: redirect to the fall-through PC, drain
    // stale fetches, then release only after the I-cache reports completion.
    val fenceIActive = fenceIPending || fenceIStart || fenceIFlushIssued
    val fenceIHold = fenceIActive
    dontTouch(fenceIReq)
    dontTouch(fenceIStart)
    dontTouch(fenceIPending)
    dontTouch(fenceIDcacheIssued)
    dontTouch(fenceIDcacheDone)
    dontTouch(fenceIDcacheFlushValid)
    dontTouch(fenceIDcacheAck)
    dontTouch(fenceIFlushIssued)
    dontTouch(fenceIInvalidateFire)
    dontTouch(fenceIAck)
    dontTouch(fenceIActive)
    dontTouch(fenceIHold)

    val dcacheArbiter = Module(new DcachePtwArbiter(tlParams))
    val dcacheMaintRespPending = fenceIDcacheIssued || debugDcacheIssued
    dcacheArbiter.io.ifetchPtwReq <> ifetch.io.ptw.req
    ifetch.io.ptw.resp <> dcacheArbiter.io.ifetchPtwResp
    dcacheArbiter.io.lsuReq <> lsu.io.dcache.req
    lsu.io.dcache.resp <> dcacheArbiter.io.lsuResp
    dcache.io.cpu.req <> dcacheArbiter.io.cacheReq
    dcacheArbiter.io.cacheResp <> dcache.io.cpu.resp
    dcacheArbiter.io.maintPending := dcacheMaintRespPending

    val dcacheRespPending = dcacheArbiter.io.respPending
    val dcacheRespOwnerPtw = dcacheArbiter.io.respOwnerPtw
    val dcacheCpuReqFire = dcacheArbiter.io.cacheReqFire
    val dcacheCpuRespAnyFire = dcacheArbiter.io.cacheRespFire

    val debugDcacheInvalidateValid = debugDcachePending && !debugDcacheIssued && !dcacheRespPending
    fenceIDcacheFlushValid := hasDCache.B && fenceIPending && !fenceIDcacheDone && !fenceIDcacheIssued &&
        !dcacheRespPending
    dcache.io.invalidate.valid := hasDCache.B && (fenceIDcacheFlushValid || debugDcacheInvalidateValid)
    dcache.io.invalidate.bits := false.B
    when(fenceIDcacheFlushValid && dcache.io.invalidate.fire) {
        fenceIDcacheIssued := true.B
    }.elsewhen(debugDcacheInvalidateValid && dcache.io.invalidate.fire) {
        debugDcacheIssued := true.B
    }
    fenceIDcacheAck := fenceIDcacheIssued && dcacheMaintRespPending && dcache.io.cpu.resp.fire
    when(debugDcachePending && debugDcacheIssued && dcacheMaintRespPending && dcache.io.cpu.resp.fire) {
        debugDcacheErr := dcache.io.cpu.resp.bits.err
        debugDcacheAck := true.B
    }
    when(!hasDCache.B && debugDcachePending) {
        debugDcacheErr := false.B
        debugDcacheAck := true.B
    }
    lsu.io.mmio <> tracker.io.master
    dbusXbar.io.masters(0) <> dcache.io.bus
    dbusXbar.io.masters(1) <> tracker.io.tl

    if (hasICache) {
        val cache = icache.get
        dbusXbar.io.masters(2) <> cache.io.bus
        // Debug-driven I-cache maintenance shares the cache CPU port with IF.
        // Let normal fence.i and any already-issued fetch response drain before
        // taking ownership, otherwise a debug request can hide the response that
        // would complete a frontend/cache maintenance transaction.
        val debugIcacheUsesPort = debugIcachePending && !fenceIActive && !ifetch.io.cache_busy
        val debugIcacheReqValid = debugIcacheUsesPort && !debugIcacheIssued
        val debugIcacheRespReady = debugIcacheUsesPort && debugIcacheIssued
        val debugIcacheReqBits = WireInit(ifetch.io.cache.req.bits)
        debugIcacheReqBits.addr := 0.U
        debugIcacheReqBits.vaddr := 0.U
        debugIcacheReqBits.cmd := soc.memory.cache.CacheCmd.Read
        debugIcacheReqBits.wdata := 0.U
        debugIcacheReqBits.mask := 0.U
        debugIcacheReqBits.size := 0.U
        debugIcacheReqBits.signed := false.B
        debugIcacheReqBits.fence := false.B
        debugIcacheReqBits.fencei := true.B
        debugIcacheReqBits.atomic := false.B
        debugIcacheReqBits.cacheable := true.B
        debugIcacheReqBits.device := false.B
        cache.io.cpu.req.valid := Mux(debugIcacheUsesPort, debugIcacheReqValid, ifetch.io.cache.req.valid)
        cache.io.cpu.req.bits := Mux(debugIcacheUsesPort, debugIcacheReqBits, ifetch.io.cache.req.bits)
        ifetch.io.cache.req.ready := !debugIcacheUsesPort && cache.io.cpu.req.ready
        ifetch.io.cache.resp.valid := !debugIcacheUsesPort && cache.io.cpu.resp.valid
        ifetch.io.cache.resp.bits := cache.io.cpu.resp.bits
        cache.io.cpu.resp.ready := Mux(debugIcacheUsesPort, debugIcacheRespReady, ifetch.io.cache.resp.ready)
        cache.io.invalidate.valid := fenceIPending && fenceIDcacheDone && !fenceIFlushIssued
        cache.io.invalidate.bits := true.B
        fenceIInvalidateFire := cache.io.invalidate.fire
        fenceIAck := fenceIFlushIssued && cache.io.cpu.resp.fire
        when(debugIcacheReqValid && cache.io.cpu.req.fire) {
            debugIcacheIssued := true.B
        }
        when(debugIcacheRespReady && cache.io.cpu.resp.fire) {
            debugIcacheErr := cache.io.cpu.resp.bits.err
            debugIcacheAck := true.B
        }
    } else {
        ifetch.io.cache.req.ready := false.B
        ifetch.io.cache.resp.valid := false.B
        ifetch.io.cache.resp.bits.rdata := 0.U
        ifetch.io.cache.resp.bits.err := false.B
        fenceIAck := fenceIPending && fenceIDcacheDone
        when(debugIcachePending) {
            debugIcacheAck := true.B
            debugIcacheErr := false.B
        }
    }

    io.debug_cache.dcacheAck := debugDcacheAck
    io.debug_cache.icacheAck := debugIcacheAck
    io.debug_cache.dcacheBusy := debugDcachePending
    io.debug_cache.icacheBusy := debugIcachePending
    io.debug_cache.dcacheErr := debugDcacheErr
    io.debug_cache.icacheErr := debugIcacheErr

    io.DBus <> dbusXbar.io.slave
    io.IBus <> DontCare

    val aluMemOp = alu.io.alu_out.mem.op
    def isLoadLikeOp(op: MemOpType.Type): Bool =
        op === MemOpType.Load || op === MemOpType.LR || op === MemOpType.SC || op === MemOpType.AMO

    val loadScoreboardFlush = Wire(Bool())
    val aluLoadLike = alu.io.valid_out && alu.io.alu_out.reg_write && alu.io.alu_out.rd =/= 0.U &&
        isLoadLikeOp(aluMemOp)
    val loadScoreboard = Module(new LoadUseScoreboard(XLEN))
    loadScoreboard.io.flush := loadScoreboardFlush
    loadScoreboard.io.aluValid := alu.io.valid_out
    loadScoreboard.io.aluRegWrite := alu.io.alu_out.reg_write
    loadScoreboard.io.aluRd := alu.io.alu_out.rd
    loadScoreboard.io.aluPc := alu.io.pc_out
    loadScoreboard.io.aluMemOp := aluMemOp
    loadScoreboard.io.lsuLoadDataValid := lsu.io.load_data_valid
    loadScoreboard.io.lsuLoadDataRd := lsu.io.load_data_rd
    loadScoreboard.io.wbRegWrite := wb.io.reg_wb.reg_write
    loadScoreboard.io.wbRd := wb.io.reg_wb.rd
    loadScoreboard.io.decodeValid := idecode.io.valid_out
    loadScoreboard.io.decodeRs1 := idecode.io.decoded_out.rs1
    loadScoreboard.io.decodeRs2 := idecode.io.decoded_out.rs2

    val loadLikePending = loadScoreboard.io.pending
    val loadLikePendingRd = loadScoreboard.io.pendingRd
    val newAluLoadLike = loadScoreboard.io.newLoadLike
    val loadLikeComplete = loadScoreboard.io.complete
    val loadLikeIssued = loadScoreboard.io.issued
    val loadLikeIssuedRd = loadScoreboard.io.issuedRd
    val decodeUsesPending = loadScoreboard.io.decodeUsesPending
    dontTouch(loadLikePending)
    dontTouch(loadLikePendingRd)
    dontTouch(newAluLoadLike)
    dontTouch(loadLikeComplete)
    dontTouch(loadLikeIssued)
    dontTouch(loadLikeIssuedRd)
    // A decoded consumer must be held in ID while the producer load is still
    // outstanding. Only gating ALU valid lets ID overwrite its operand fields
    // with stale register-file data, which breaks load-to-branch sequences such
    // as `lbu; beqz` in firmware string loops.
    val decodeCsrOp = idecode.io.decoded_out.ctrl.csr_op
    val decodeCsrWrite = decodeCsrOp =/= CSROps.None &&
        !((decodeCsrOp === CSROps.RS || decodeCsrOp === CSROps.RC) && idecode.io.decoded_out.rs2 === 0.U) &&
        !((decodeCsrOp === CSROps.RSI || decodeCsrOp === CSROps.RCI) && idecode.io.decoded_out.rs2 === 0.U)
    val architecturalCsrCommit = Wire(Bool())

    satpBarrier.io.decodeValid := idecode.io.valid_out
    satpBarrier.io.decodeCsrWrite := decodeCsrWrite
    satpBarrier.io.decodeCsrAddr := idecode.io.decoded_out.instr(31, 20)
    satpBarrier.io.lsuMemoryIdle := lsu.io.memory_idle
    satpBarrier.io.commitValid := architecturalCsrCommit
    satpBarrier.io.commitCsrWrite := alu.io.csr_commit_write
    satpBarrier.io.commitCsrAddr := alu.io.csr_commit_addr
    satpBarrier.io.commitPc := alu.io.pc_out
    satpBarrier.io.commitInstrLen := alu.io.instr_len_out

    val decodeStall = pipe_stall || decodeUsesPending || satpBarrier.io.holdDecode || debugHalted

    pipe_stall := lsu.io.stall_req
    when(io.debug_resumereq) {
        debugHalted := false.B
    }.elsewhen(io.debug_haltreq && !pipe_stall) {
        debugHalted := true.B
    }
    io.debug_halted := debugHalted

    val debugCacheHold = debugDcachePending || debugIcachePending
    val frontend_flush    = Wire(Bool())
    val ifetchQueueReady  = Wire(Bool())
    val decodeInputValid  = Wire(Bool())
    val frontendQueueFlush = Wire(Bool())
    val frontendQueueFull = Wire(Bool())
    val frontendQueueEmpty = Wire(Bool())
    val frontendStarved   = !decodeInputValid && ifetch.io.fetch_stall
    global_stall := pipe_stall || decodeUsesPending || frontendStarved || fenceIHold || debugHalted || debugCacheHold

    // Interrupt inputs. Supervisor-level lines are reserved for the future
    // S-mode trap path and can be tied off by the SoC until a controller exists.
    csr.io.msip := io.msip
    csr.io.mtip := io.mtip
    csr.io.meip := io.meip
    csr.io.ssip := io.ssip
    csr.io.stip := io.stip
    csr.io.seip := io.seip

	    // Combine pipeline traps with frontend traps and external interrupts.
        // External interrupts are
	    // latched before redirect so CSR and PC consume the same trap PC.
	    val has_pipeline_trap = lsu.io.trap_info_out.valid
        val has_fetch_trap    = ifetch.io.trap_info.valid
	    val has_ret           = lsu.io.trap_info_out.is_ret && lsu.io.valid_out
        val retConsumed       = RegInit(false.B)
	    val ret_redirect      = has_ret && !retConsumed
        when(ret_redirect) {
            retConsumed := true.B
        }.elsewhen(!has_ret) {
            retConsumed := false.B
        }
        val interruptPending = RegInit(false.B)
        val interruptPc      = RegInit(0.U(XLEN.W))
        val interruptCause   = RegInit(0.U(XLEN.W))
        val interruptTarget  = RegInit(0.U(XLEN.W))
        val interrupt_fire =
            interruptPending && !pipe_stall && !has_pipeline_trap && !has_fetch_trap && !ret_redirect
        val interrupt_detect =
            csr.io.interrupt && !pipe_stall && !has_pipeline_trap && !has_fetch_trap && !ret_redirect && !interruptPending
        val interruptResumePc =
            Mux(alu.io.br_info.valid && alu.io.br_info.redirect, alu.io.br_info.target, pc.io.pc_out)
        when(interrupt_fire) {
            interruptPending := false.B
        }.elsewhen(interrupt_detect) {
            interruptPending := true.B
            interruptPc      := interruptResumePc
            interruptCause   := csr.io.interrupt_cause
            interruptTarget  := csr.io.tvec_out
        }
	    val combined_trap     = has_pipeline_trap || has_fetch_trap || interrupt_fire
	    val redirect_flush    = combined_trap || ret_redirect
        // The registered ALU slot is one instruction younger than the LSU slot.
        // Once that older slot traps or returns, the younger CSR must not update
        // architectural state (or trigger the satp barrier) on the redirect edge.
        // A fetch-side trap is younger than the ALU slot, so it deliberately does
        // not suppress this commit.
        architecturalCsrCommit := alu.io.csr_commit_valid && !has_pipeline_trap && !ret_redirect
        frontend_flush         := redirect_flush || fenceIActive || satpBarrier.io.frontendFlush || debugIcachePending
        val pipeline_flush    = frontend_flush
        dontTouch(pipeline_flush)
        dontTouch(frontendQueueFlush)
        dontTouch(redirect_flush)

    // pc
    io.pc            := pc.io.pc_out
    io.fetch_en      := pc.io.fetch_en
    pc.io.stall      := ifetch.io.fetch_stall || !ifetchQueueReady || fenceIHold || debugHalted || debugCacheHold
	    pc.io.trap_valid := combined_trap
    pc.io.trap_pc    := Mux(has_pipeline_trap || has_fetch_trap, csr.io.tvec_out, interruptTarget)
    pc.io.trap_ret   := ret_redirect
    pc.io.trap_epc   := csr.io.epc_out
    pc.io.instr_len  := ifetch.io.pc_step_len
    val pcBrInfo = WireInit(alu.io.br_info)
    when(satpBarrier.io.redirect.valid) {
        pcBrInfo := satpBarrier.io.redirect
    }.elsewhen(fenceIStart) {
        val fenceStep = Mux(alu.io.instr_len_out === 2.U, 2.U(XLEN.W), 4.U(XLEN.W))
        pcBrInfo.valid := false.B
        pcBrInfo.is_branch := false.B
        pcBrInfo.taken := true.B
        pcBrInfo.target := alu.io.pc_out + fenceStep
        pcBrInfo.redirect := true.B
    }
    pc.io.br_info <> pcBrInfo
    frontendQueueFlush := frontend_flush || pc.io.redirect
    loadScoreboardFlush := redirect_flush || frontendQueueFlush
    val aluResultFwdValid = RegInit(false.B)
    val aluResultFwdRd = RegInit(0.U(5.W))
    val aluResultFwdData = RegInit(0.U(XLEN.W))
    val aluResultPrevValid = RegInit(false.B)
    val aluResultPrevRd = RegInit(0.U(5.W))
    val aluResultPrevData = RegInit(0.U(XLEN.W))
    // ALU forwarding is only for short fixed-latency ALU producers. A load-like
    // instruction must invalidate only entries for its own rd; otherwise an
    // independent ALU result can be lost while the load stalls the next consumer.
    val aluForwardFlush = frontendQueueFlush || redirect_flush
    val aluLoadLikeRd = alu.io.alu_out.rd
    val keepAluFwd = !(aluLoadLike && aluResultFwdValid && aluResultFwdRd === aluLoadLikeRd)
    val keepPrevAluFwd = !(aluLoadLike && aluResultPrevValid && aluResultPrevRd === aluLoadLikeRd)
    val aluForwardUpdate = !pipe_stall && !debugHalted
    val nextAluForwardValid =
        alu.io.valid_out && alu.io.alu_out.reg_write && alu.io.alu_out.rd =/= 0.U &&
            !isLoadLikeOp(aluMemOp)
    when(aluForwardFlush) {
        aluResultFwdValid := false.B
        aluResultFwdRd := 0.U
        aluResultFwdData := 0.U
        aluResultPrevValid := false.B
        aluResultPrevRd := 0.U
        aluResultPrevData := 0.U
    }.elsewhen(aluForwardUpdate) {
        aluResultPrevValid := aluResultFwdValid && keepAluFwd
        aluResultPrevRd := Mux(aluResultFwdValid && keepAluFwd, aluResultFwdRd, 0.U)
        aluResultPrevData := Mux(aluResultFwdValid && keepAluFwd, aluResultFwdData, 0.U)
        aluResultFwdValid := nextAluForwardValid
        aluResultFwdRd := Mux(nextAluForwardValid, alu.io.alu_out.rd, 0.U)
        aluResultFwdData := Mux(nextAluForwardValid, alu.io.alu_out.result, 0.U)
    }.otherwise {
        when(!keepAluFwd) {
            aluResultFwdValid := false.B
            aluResultFwdRd := 0.U
            aluResultFwdData := 0.U
        }
        when(!keepPrevAluFwd) {
            aluResultPrevValid := false.B
            aluResultPrevRd := 0.U
            aluResultPrevData := 0.U
        }
    }
    // register
    register.io.rs1_addr   := idecode.io.reg_rd_rs1
    register.io.rs2_addr   := idecode.io.reg_rd_rs2
    register.io.write_en   := wb.io.reg_wb.reg_write
    register.io.write_addr := wb.io.reg_wb.rd
    register.io.write_data := wb.io.reg_wb.data
    register.io.debug_addr := io.debug_gpr_addr
    register.io.debug_write := io.debug_gpr_write && debugHalted
    register.io.debug_wdata := io.debug_gpr_wdata
    io.debug_gpr_rdata := register.io.debug_rdata
    io.debug_retire := wb.io.valid_in && !wb.io.trap_info.valid
    io.debug_commit_pc := wb.io.pc_in
    io.debug_commit_instr := wb.io.commit_instr
    io.debug_commit_instr_len := wb.io.commit_instr_len
    io.debug_commit_wen := wb.io.reg_wb.reg_write
    io.debug_commit_wdest := wb.io.reg_wb.rd
    io.debug_commit_wdata := wb.io.reg_wb.data
    io.debug_commit_skip := wb.io.commit_skip
    val archEventCause = Mux(
        has_pipeline_trap,
        lsu.io.trap_info_out.cause,
        Mux(has_fetch_trap, ifetch.io.trap_info.cause, interruptCause)
    )
    val archEventPc = Mux(
        has_pipeline_trap,
        lsu.io.trap_info_out.pc,
        Mux(has_fetch_trap, ifetch.io.trap_info.pc, interruptPc)
    )
    val archEventTval = Mux(
        has_pipeline_trap,
        lsu.io.trap_info_out.value,
        Mux(has_fetch_trap, ifetch.io.trap_info.value, 0.U)
    )
    val archEventInstr = Mux(
        has_pipeline_trap && lsu.io.trap_info_out.cause === MCause.IllegalInstr,
        lsu.io.trap_info_out.value(31, 0),
        Mux(has_pipeline_trap, lsu.io.mem_out.instr, 0.U)
    )
    io.debug_arch_event_valid := RegNext(combined_trap, false.B)
    io.debug_arch_event_interrupt := RegNext(interrupt_fire, false.B)
    io.debug_arch_event_cause := RegNext(archEventCause, 0.U)
    io.debug_arch_event_pc := RegNext(archEventPc, 0.U)
    io.debug_arch_event_instr := RegNext(archEventInstr, 0.U)
    io.debug_arch_event_tval := RegNext(archEventTval, 0.U)
    io.debug_gpr_snapshot := register.io.debug_snapshot
    io.debug_stall := global_stall
    io.debug_ifetch_stall := ifetch.io.fetch_stall
    io.debug_frontend_starved := frontendStarved
    io.debug_frontend_queue_full := frontendQueueFull
    io.debug_frontend_queue_empty := frontendQueueEmpty
    io.debug_lsu_stall := lsu.io.stall_req
    io.debug_lsu_load_stall := lsu.io.stall_load
    io.debug_lsu_store_stall := lsu.io.stall_store
    io.debug_lsu_mmio_stall := lsu.io.stall_mmio
    io.debug_lsu_atomic_stall := lsu.io.stall_atomic
    io.debug_lsu_fence_stall := lsu.io.stall_fence
    io.debug_fence_i_active := fenceIActive
    io.debug_branch_valid := alu.io.br_info.valid
    io.debug_branch_taken := alu.io.br_info.taken
    io.debug_branch_redirect := alu.io.br_info.redirect
    io.debug_branch_pred_taken := alu.io.br_info.valid && alu.io.pred_taken_in
    io.debug_branch_pred_correct := alu.io.br_info.valid && alu.io.pred_taken_in && alu.io.br_info.taken && !alu.io.br_info.redirect
    // CSR
    csr.io.valid      := alu.io.csr_valid
    csr.io.cmd        := alu.io.csr_cmd
    // Keep CSR reads combinational from the current EX instruction, while
    // committing writes from the registered EX slot. This preserves CSRRS-style
    // old-value reads without letting a flushed/stalled younger CSR mutate state.
    csr.io.addr       := alu.io.csr_addr
    csr.io.write      := alu.io.csr_write
    csr.io.wdata      := alu.io.csr_wdata
    csr.io.wvalid     := architecturalCsrCommit
    csr.io.wcmd       := alu.io.csr_commit_cmd
    csr.io.waddr      := alu.io.csr_commit_addr
    csr.io.wwrite     := alu.io.csr_commit_write
    csr.io.wwdata     := alu.io.csr_commit_wdata
    csr.io.debug_addr := io.debug_csr_addr
    csr.io.debug_write := io.debug_csr_write && debugHalted
    csr.io.debug_wdata := io.debug_csr_wdata
    io.debug_csr_rdata := csr.io.debug_rdata
    io.debug_csr_valid := csr.io.debug_valid
    io.debug_csr_writable := csr.io.debug_writable
    io.debug_csr_snapshot := csr.io.state_snapshot
    csr.io.trap_valid := combined_trap
    // Exceptions take priority over interrupts for pc/cause
    csr.io.trap_pc := Mux(
        has_pipeline_trap,
        lsu.io.trap_info_out.pc,
        Mux(has_fetch_trap, ifetch.io.trap_info.pc, interruptPc)
    )
    csr.io.trap_cause := Mux(
        has_pipeline_trap,
        lsu.io.trap_info_out.cause,
        Mux(has_fetch_trap, ifetch.io.trap_info.cause, interruptCause)
    )
    csr.io.trap_value := archEventTval
    csr.io.is_ret     := ret_redirect
    csr.io.ret_type   := lsu.io.trap_info_out.ret_type
    csr.io.ie_out     := DontCare
    csr.io.perf.retire := io.debug_retire
    csr.io.perf.globalStall := global_stall
    csr.io.perf.ifetchStall := ifetch.io.fetch_stall
    csr.io.perf.lsuStall := lsu.io.stall_req
    csr.io.perf.lsuLoadStall := lsu.io.stall_load
    csr.io.perf.lsuStoreStall := lsu.io.stall_store
    csr.io.perf.lsuMmioStall := lsu.io.stall_mmio
    csr.io.perf.lsuAtomicStall := lsu.io.stall_atomic
    csr.io.perf.lsuFenceStall := lsu.io.stall_fence
    csr.io.perf.branch := alu.io.br_info.valid
    csr.io.perf.branchTaken := alu.io.br_info.valid && alu.io.br_info.taken
    csr.io.perf.branchRedirect := alu.io.br_info.valid && alu.io.br_info.redirect
    csr.io.perf.branchPredTaken := alu.io.br_info.valid && alu.io.pred_taken_in
    csr.io.perf.branchPredCorrect := alu.io.br_info.valid && alu.io.pred_taken_in && alu.io.br_info.taken && !alu.io.br_info.redirect
    // ifetch
    ifetch.io.stall         := !ifetchQueueReady || debugDcachePending || (debugHalted && !debugIcachePending)
    ifetch.io.pc            := pc.io.pc_out
    ifetch.io.instr_in      := io.instr
    ifetch.io.mem_cfg       := csr.io.mem_cfg_out
    ifetch.io.pred_taken_in := pc.io.pred_taken
    ifetch.io.pred_target_in := pc.io.pred_target
    ifetch.io.redirect      := pc.io.redirect
    ifetch.io.trap_valid    := frontend_flush
    io.debug_instr          := ifetch.io.instr_out

    val fetchEntry = Wire(new FrontendQueueEntry(XLEN))
    fetchEntry.pc := ifetch.io.pc_out
    fetchEntry.instr := ifetch.io.instr_out
    fetchEntry.instrLen := ifetch.io.instr_len
    fetchEntry.predTaken := ifetch.io.pred_taken_out
    fetchEntry.predTarget := ifetch.io.pred_target_out

    val decodeEntry = Wire(new FrontendQueueEntry(XLEN))
    if (hasFrontendQueue) {
        val frontendQueue = Module(new FrontendQueue(XLEN, features.frontendQueueEntries))
        frontendQueue.io.flush := frontendQueueFlush
        frontendQueue.io.enq.valid := ifetch.io.valid && !frontendQueueFlush
        frontendQueue.io.enq.bits := fetchEntry
        frontendQueue.io.deq.ready := !frontendQueueFlush && !decodeStall
        ifetchQueueReady := frontendQueue.io.enq.ready
        decodeInputValid := frontendQueue.io.deq.valid
        frontendQueueFull := frontendQueue.io.full
        frontendQueueEmpty := frontendQueue.io.empty
        decodeEntry := frontendQueue.io.deq.bits
    } else {
        ifetchQueueReady := !(decodeStall || debugDcachePending || (debugHalted && !debugIcachePending))
        decodeInputValid := ifetch.io.valid
        frontendQueueFull := !ifetchQueueReady
        frontendQueueEmpty := !ifetch.io.valid
        decodeEntry := fetchEntry
    }

    // idcode
    idecode.io.valid_in      := decodeInputValid
    idecode.io.stall         := decodeStall
	    idecode.io.trap_valid    := frontend_flush
    idecode.io.redirect      := ifetch.io.redirect
    idecode.io.pc_in         := decodeEntry.pc
    idecode.io.instr_in      := decodeEntry.instr
    idecode.io.instr_len_in  := decodeEntry.instrLen
    idecode.io.priv          := csr.io.mem_cfg_out.priv
    idecode.io.pred_taken_in := decodeEntry.predTaken
    idecode.io.pred_target_in := decodeEntry.predTarget
    val aluBypassValid = alu.io.valid_out && alu.io.alu_out.reg_write && alu.io.alu_out.rd =/= 0.U &&
        !isLoadLikeOp(aluMemOp)
    def bypassSource(valid: Bool, rd: UInt, data: UInt): FwdSource = {
        val source = Wire(new FwdSource(XLEN))
        source.valid := valid && rd =/= 0.U
        source.rd := rd
        source.data := data
        source
    }
    val decodeBypassSources = Seq(
        bypassSource(aluBypassValid, alu.io.alu_out.rd, alu.io.alu_out.result),
        bypassSource(wb.io.reg_wb.reg_write, wb.io.reg_wb.rd, wb.io.reg_wb.data),
        bypassSource(lsu.io.mem_out.reg_write, lsu.io.mem_out.rd, lsu.io.mem_out.result),
        bypassSource(lsu.io.load_data_valid, lsu.io.load_data_rd, lsu.io.load_data)
    )
    def decodeBypass(addr: UInt, regData: UInt): UInt = {
        decodeBypassSources.foldLeft(Mux(addr === 0.U, 0.U, regData)) { (data, source) =>
            Mux(addr =/= 0.U && source.valid && addr === source.rd, source.data, data)
        }
    }
    val lsuFwd = bypassSource(lsu.io.mem_out.reg_write, lsu.io.mem_out.rd, lsu.io.mem_out.result)
    val aluFwd = bypassSource(aluResultFwdValid, aluResultFwdRd, aluResultFwdData)
    val prevAluFwd = bypassSource(aluResultPrevValid, aluResultPrevRd, aluResultPrevData)
    val wbFwd = bypassSource(wb.io.reg_wb.reg_write, wb.io.reg_wb.rd, wb.io.reg_wb.data)
    def driveFwdSource(targetValid: Bool, targetRd: UInt, targetData: UInt, source: FwdSource): Unit = {
        targetValid := source.valid
        targetRd := source.rd
        targetData := source.data
    }
    idecode.io.reg_rs1_data  := decodeBypass(idecode.io.reg_rd_rs1, register.io.rs1_data)
    idecode.io.reg_rs2_data  := decodeBypass(idecode.io.reg_rd_rs2, register.io.rs2_data)
    // alu
    val idIssuedValid = RegInit(false.B)
    val idIssuedPc = RegInit(0.U(XLEN.W))
    val idAlreadyIssued = idIssuedValid && idecode.io.valid_out && idecode.io.pc_out === idIssuedPc
    // Do not mark an ID instruction as issued while EX/MEM is applying
    // back-pressure. ALU.valid_in would otherwise be sampled during a stall,
    // then the one-shot gate would suppress the real issue when the load/store
    // path becomes ready.
    val exIssueReady = !pipe_stall && !debugHalted
    val idIssueReady = !decodeUsesPending && !satpBarrier.io.holdDecode && exIssueReady
    val issueIdToAlu = idecode.io.valid_out && idIssueReady && !idAlreadyIssued
    // The PC-only one-shot protects against a held or briefly repeated frontend
    // slot. A correctly predicted `j .`, however, is a genuinely new dynamic
    // instruction at the same PC. Release the one-shot after EX resolves that
    // exact self-loop so it can keep retiring (with one conservative bubble).
    val resolvedSelfLoop = alu.io.br_info.valid && alu.io.br_info.taken &&
        alu.io.br_info.target === alu.io.br_info.pc
    when(frontendQueueFlush || redirect_flush || !idecode.io.valid_out) {
        idIssuedValid := false.B
        idIssuedPc := 0.U
    }.elsewhen(issueIdToAlu) {
        idIssuedValid := true.B
        idIssuedPc := idecode.io.pc_out
    }.elsewhen(resolvedSelfLoop) {
        idIssuedValid := false.B
        idIssuedPc := 0.U
    }
    alu.io.valid_in       := issueIdToAlu && exIssueReady
    alu.io.stall          := pipe_stall || debugHalted
    // Any redirect invalidates the younger instruction currently arriving at
    // EX. Trap/ret redirects are covered by redirect_flush; branch and fence.i
    // redirects arrive through pc.io.redirect/frontendQueueFlush.
	    alu.io.trap_valid     := redirect_flush || frontendQueueFlush
    alu.io.pc_in          := idecode.io.pc_out
    alu.io.next_pc_in     := idecode.io.pc_in
    alu.io.pred_taken_in  := idecode.io.pred_taken_out
    alu.io.pred_target_in := idecode.io.pred_target_out
    alu.io.decoded_in     := idecode.io.decoded_out
    alu.io.trap_info_in   := idecode.io.trap_info
    alu.io.csr_illegal    := csr.io.illegal
    alu.io.fwd.load_valid := lsu.io.load_data_valid
    alu.io.fwd.load_rd    := lsu.io.load_data_rd
	alu.io.fwd.load_data  := lsu.io.load_data
    // ALU-to-ALU adjacency is handled inside ALU with a one-cycle EX bypass.
    // The delayed slots below cover one-instruction gaps such as
    // `addi s0,...; addi s1,...; beqz s0,...`. They are explicitly cleared on
    // redirects so the new control-flow path cannot consume an expired value.
    alu.io.fwd.reg_write  := aluFwd.valid || lsuFwd.valid
    alu.io.fwd.rd         := Mux(aluFwd.valid, aluFwd.rd, lsuFwd.rd)
    alu.io.fwd.alu_result := Mux(aluFwd.valid, aluFwd.data, lsuFwd.data)
    driveFwdSource(alu.io.fwd.wb_reg_write, alu.io.fwd.wb_rd, alu.io.fwd.wb_data, wbFwd)
    driveFwdSource(alu.io.fwd.prev_reg_write, alu.io.fwd.prev_rd, alu.io.fwd.prev_data, prevAluFwd)
    alu.io.csr_rdata      := csr.io.rdata
    // mem
    lsu.io.pc_in        := alu.io.pc_out
    lsu.io.valid_in     := alu.io.valid_out
    // Trap returns and LSU exceptions resolve after EX, so a younger
    // fall-through instruction can already be sitting on the ALU->LSU boundary
    // when the redirect commits. Kill that incoming MEM slot from registered
    // LSU/WB redirect state only; feeding the full frontend flush back here
    // would create a stall/flush combinational loop.
    lsu.io.trap_valid   := wb.io.trap_info.valid || has_pipeline_trap || ret_redirect
    lsu.io.alu_out      := alu.io.alu_out
    lsu.io.trap_info_in := alu.io.trap_info_out
    lsu.io.mem_cfg      := csr.io.mem_cfg_out
    // write back
    wb.io.pc_in     := lsu.io.pc_out
    wb.io.valid_in  := lsu.io.valid_out
    wb.io.mem_in    := lsu.io.mem_out
    wb.io.trap_info := lsu.io.trap_info_out
}
