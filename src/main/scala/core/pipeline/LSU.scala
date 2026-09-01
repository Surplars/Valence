package soc.core.pipeline

import chisel3._
import chisel3.util._

import soc.core.pipeline.ALUOut
import soc.bus.tilelink.TLParams
import soc.bus.tilelink.TLOpcode
import soc.config.Config
import soc.config.SoCFeatures
import soc.isa.Funct3
import soc.isa.MCause
import soc.memory.CacheReq
import soc.memory.CacheResp
import soc.memory.MmioMaster
import soc.memory.cache.CacheCmd

class LSU(XLEN: Int = 64, features: SoCFeatures = Config.features) extends Module {
    val io = IO(new Bundle {
        val pc_in        = Input(UInt(XLEN.W))
        val valid_in     = Input(Bool())
        val trap_valid   = Input(Bool())
        val alu_out      = Input(new ALUOut(XLEN))
        val trap_info_in = Input(new TrapInfo(XLEN))
        val mem_cfg      = Input(new MemorySystemConfig(XLEN))

        val dcache = new Bundle {
            val req  = Decoupled(new CacheReq(XLEN, XLEN))
            val resp = Flipped(Decoupled(new CacheResp(XLEN)))
        }
        val mmio = new MmioMaster(TLParams())

        val pc_out        = Output(UInt(XLEN.W))
        val valid_out     = Output(Bool())
        val mem_out       = Output(new MemOut(XLEN))
        val trap_info_out = Output(new TrapInfo(XLEN))

        val stall_req       = Output(Bool())
        val stall_load      = Output(Bool())
        val stall_store     = Output(Bool())
        val stall_mmio      = Output(Bool())
        val stall_atomic    = Output(Bool())
        val stall_fence     = Output(Bool())
        val memory_idle     = Output(Bool())
        val load_data_valid = Output(Bool())
        val load_data_rd    = Output(UInt(5.W))
        val load_data       = Output(UInt(XLEN.W))
    })

    private val beatOffsetBits = log2Ceil(XLEN / 8)

    private def formatLoadData(rawData: UInt, access: MemoryAccessInfo): UInt = {
        val shiftBytes = access.paddr(beatOffsetBits - 1, 0)
        val shiftBits  = Cat(shiftBytes, 0.U(3.W))
        val shifted    = (rawData >> shiftBits)(XLEN - 1, 0)
        val byteData   = shifted(7, 0)
        val halfData   = shifted(15, 0)
        val wordData   = shifted(31, 0)

        MuxLookup(access.size, shifted)(
            Seq(
                0.U -> Mux(access.signed, Cat(Fill(XLEN - 8, byteData(7)), byteData), Cat(0.U((XLEN - 8).W), byteData)),
                1.U -> Mux(access.signed, Cat(Fill(XLEN - 16, halfData(15)), halfData), Cat(0.U((XLEN - 16).W), halfData)),
                2.U -> Mux(access.signed, Cat(Fill(XLEN - 32, wordData(31)), wordData), Cat(0.U((XLEN - 32).W), wordData)),
                3.U -> shifted
            )
        )
    }

    private def formatSplitLoadData(lowData: UInt, highData: UInt, access: MemoryAccessInfo): UInt = {
        val shiftBits = Cat(access.paddr(beatOffsetBits - 1, 0), 0.U(3.W))
        val highShift = (XLEN.U(7.W) - shiftBits)(5, 0)
        val combined  = (lowData >> shiftBits) | (highData << highShift)
        val shifted = Mux(shiftBits === 0.U, lowData, combined(XLEN - 1, 0))
        val byteData = shifted(7, 0)
        val halfData = shifted(15, 0)
        val wordData = shifted(31, 0)
        MuxLookup(access.size, shifted)(
            Seq(
                0.U -> Mux(access.signed, Cat(Fill(XLEN - 8, byteData(7)), byteData), Cat(0.U((XLEN - 8).W), byteData)),
                1.U -> Mux(access.signed, Cat(Fill(XLEN - 16, halfData(15)), halfData), Cat(0.U((XLEN - 16).W), halfData)),
                2.U -> Mux(access.signed, Cat(Fill(XLEN - 32, wordData(31)), wordData), Cat(0.U((XLEN - 32).W), wordData)),
                3.U -> shifted
            )
        )
    }

    private def alignBeat(addr: UInt): UInt = Cat(addr(XLEN - 1, beatOffsetBits), 0.U(beatOffsetBits.W))

    private def shiftedData(rawData: UInt, access: MemoryAccessInfo): UInt = {
        val shiftBytes = access.paddr(beatOffsetBits - 1, 0)
        val shiftBits  = Cat(shiftBytes, 0.U(3.W))
        (rawData >> shiftBits)(XLEN - 1, 0)
    }

    private def formatAtomicReadData(rawData: UInt, access: MemoryAccessInfo): UInt = {
        val shifted = shiftedData(rawData, access)
        Mux(access.size === 2.U, Cat(Fill(XLEN - 32, shifted(31)), shifted(31, 0)), shifted)
    }

    private def formatAtomicWdata(value: UInt, access: MemoryAccessInfo): UInt = {
        val shiftBits = Cat(access.paddr(beatOffsetBits - 1, 0), 0.U(3.W))
        Mux(access.size === 2.U, Fill(2, value(31, 0)), value) << shiftBits
    }

    private def computeAtomicWrite(oldValue: UInt, access: MemoryAccessInfo): UInt = {
        val srcValue = shiftedData(access.wdata, access)
        val result64 = Wire(UInt(XLEN.W))
        val oldS64 = oldValue.asSInt
        val srcS64 = srcValue.asSInt
        result64 := MuxLookup(access.atomic, srcValue)(
            Seq(
                AtomicOpType.Swap -> srcValue,
                AtomicOpType.Add  -> (oldValue + srcValue),
                AtomicOpType.Xor  -> (oldValue ^ srcValue),
                AtomicOpType.And  -> (oldValue & srcValue),
                AtomicOpType.Or   -> (oldValue | srcValue),
                AtomicOpType.Min  -> Mux(oldS64 < srcS64, oldValue, srcValue),
                AtomicOpType.Max  -> Mux(oldS64 >= srcS64, oldValue, srcValue),
                AtomicOpType.MinU -> Mux(oldValue < srcValue, oldValue, srcValue),
                AtomicOpType.MaxU -> Mux(oldValue >= srcValue, oldValue, srcValue)
            )
        )

        val oldWord = oldValue(31, 0)
        val srcWord = srcValue(31, 0)
        val result32 = Wire(UInt(32.W))
        result32 := MuxLookup(access.atomic, srcWord)(
            Seq(
                AtomicOpType.Swap -> srcWord,
                AtomicOpType.Add  -> (oldWord + srcWord),
                AtomicOpType.Xor  -> (oldWord ^ srcWord),
                AtomicOpType.And  -> (oldWord & srcWord),
                AtomicOpType.Or   -> (oldWord | srcWord),
                AtomicOpType.Min  -> Mux(oldWord.asSInt < srcWord.asSInt, oldWord, srcWord),
                AtomicOpType.Max  -> Mux(oldWord.asSInt >= srcWord.asSInt, oldWord, srcWord),
                AtomicOpType.MinU -> Mux(oldWord < srcWord, oldWord, srcWord),
                AtomicOpType.MaxU -> Mux(oldWord >= srcWord, oldWord, srcWord)
            )
        )

        Mux(access.size === 2.U, Cat(Fill(XLEN - 32, result32(31)), result32), result64)
    }

    val valid_inst  = io.valid_in && !io.trap_valid && !io.trap_info_in.valid
    val accessStage = Module(new MemoryAccessStage(XLEN, features))
    accessStage.io.in  := io.alu_out.mem
    accessStage.io.cfg := io.mem_cfg

    val rawMemAccess  = accessStage.io.out
    val rawStageFault = accessStage.io.fault

    private def inPaddrRegion(addr: UInt, region: soc.config.AddressRegion): Bool =
        region.contains(addr, XLEN)
    private def paddrInSram(addr: UInt): Bool =
        Config.sramRegionFor(features).contains(addr, XLEN)
    private def paddrInDevice(addr: UInt): Bool =
        Config.deviceRegions.map(region => inPaddrRegion(addr, region)).reduce(_ || _)
    private def paddrInRom(addr: UInt): Bool =
        Config.RomRegion.contains(addr, XLEN)

    val ptw = Module(new Sv39PageTableWalker(XLEN))
    val xlatePending = RegInit(false.B)
    val xlateDone = RegInit(false.B)
    val xlateAccess = RegInit(0.U.asTypeOf(new MemoryAccessInfo(XLEN)))
    val xlateFault = RegInit(0.U.asTypeOf(new MemoryFaultInfo(XLEN)))
    val xlatePc = RegInit(0.U(XLEN.W))
    val xlateRd = RegInit(0.U(5.W))
    val xlateAtomic = RegInit(AtomicOpType.None)

    val sameTranslatedInput = xlateDone &&
        xlatePc === io.pc_in &&
        xlateRd === io.alu_out.rd &&
        xlateAtomic === rawMemAccess.atomic &&
        xlateAccess.op === rawMemAccess.op &&
        xlateAccess.vaddr === rawMemAccess.vaddr

    val memAccess = Wire(new MemoryAccessInfo(XLEN))
    val stageFault = Wire(new MemoryFaultInfo(XLEN))
    memAccess := Mux(sameTranslatedInput, xlateAccess, rawMemAccess)
    stageFault := Mux(sameTranslatedInput, xlateFault, rawStageFault)

    val is_load       = valid_inst && memAccess.op === MemOpType.Load
    val is_store      = valid_inst && memAccess.op === MemOpType.Store
    val is_lr         = valid_inst && memAccess.op === MemOpType.LR
    val is_sc         = valid_inst && memAccess.op === MemOpType.SC
    val is_amo        = valid_inst && memAccess.op === MemOpType.AMO
    val is_fence      = valid_inst && memAccess.op === MemOpType.Fence
    val is_atomic     = is_lr || is_sc || is_amo
    val is_device     = memAccess.attrs.device
    val addr          = memAccess.paddr
    val strb          = memAccess.mask
    val wdata_aligned = memAccess.wdata

    val misaligned = MuxLookup(memAccess.size, false.B)(
        Seq(
            0.U -> false.B,
            1.U -> (addr(0) =/= 0.U(1.W)),
            2.U -> (addr(1, 0) =/= 0.U(2.W)),
            3.U -> (addr(2, 0) =/= 0.U(3.W))
        )
    )
    val accessBytes = 1.U(XLEN.W) << memAccess.size
    val accessEnd = memAccess.paddr + accessBytes - 1.U
    val crossesBeat = alignBeat(memAccess.paddr) =/= alignBeat(accessEnd)
    val cacheableMisalignedLoad = is_load && !is_device && memAccess.attrs.cacheable && misaligned
    val cacheableMisalignedStore = is_store && !is_device && memAccess.attrs.cacheable && misaligned
    val split_cache_load = cacheableMisalignedLoad && crossesBeat
    val split_cache_store = cacheableMisalignedStore && crossesBeat
    val mem_addr_exception = valid_inst && memAccess.valid && (is_load || is_store || is_atomic) && misaligned &&
        !cacheableMisalignedLoad && !cacheableMisalignedStore
    val atomic_device_fault = valid_inst && memAccess.valid && is_atomic && is_device
    val access_fault = stageFault.valid
    val rawNeedsTranslation = valid_inst && rawMemAccess.valid && rawMemAccess.attrs.translate &&
        (rawMemAccess.op === MemOpType.Load || rawMemAccess.op === MemOpType.Store ||
            rawMemAccess.op === MemOpType.LR || rawMemAccess.op === MemOpType.SC || rawMemAccess.op === MemOpType.AMO)
    val translationNotReady = rawNeedsTranslation && !sameTranslatedInput

    // Only a real ALU/MEM pipeline slot may carry architectural trap metadata.
    // During load-use or memory back-pressure the upstream ALU bundle can hold
    // stale sideband values while valid_in is low; propagating those values
    // creates false traps and can redirect S-mode code to an uninitialized stvec.
    val trap_info = WireInit(0.U.asTypeOf(io.trap_info_in))
    when(io.valid_in && !io.trap_valid) {
        trap_info := io.trap_info_in
    }
    when(mem_addr_exception && !io.trap_info_in.valid) {
        trap_info.valid  := true.B
        trap_info.pc     := io.pc_in
        trap_info.cause  := Mux(is_store || is_sc || is_amo, MCause.StoreAddrMisaligned, MCause.LoadAddrMisaligned)
        trap_info.value  := memAccess.vaddr
        trap_info.is_ret := false.B
        trap_info.ret_type := TrapReturnType.None
    }.elsewhen(atomic_device_fault && !io.trap_info_in.valid) {
        trap_info.valid  := true.B
        trap_info.pc     := io.pc_in
        trap_info.cause  := Mux(is_lr, MCause.LoadAccessFault, MCause.StoreAccessFault)
        trap_info.value  := memAccess.vaddr
        trap_info.is_ret := false.B
        trap_info.ret_type := TrapReturnType.None
    }.elsewhen(stageFault.valid && !io.trap_info_in.valid) {
        trap_info.valid  := true.B
        trap_info.pc     := io.pc_in
        trap_info.cause  := stageFault.cause
        trap_info.value  := stageFault.value
        trap_info.is_ret := false.B
        trap_info.ret_type := TrapReturnType.None
    }

    val mmio_err_valid  = RegInit(false.B)
    val mmio_err_pc     = RegInit(0.U(XLEN.W))
    val mmio_err_cause  = RegInit(0.U(XLEN.W))
    val mmio_err_value  = RegInit(0.U(XLEN.W))
    val cache_err_valid = RegInit(false.B)
    val cache_err_pc    = RegInit(0.U(XLEN.W))
    val cache_err_cause = RegInit(MCause.LoadAccessFault)
    val cache_err_value = RegInit(0.U(XLEN.W))
    val store_err_valid = RegInit(false.B)
    val store_err_pc    = RegInit(0.U(XLEN.W))
    val store_err_value = RegInit(0.U(XLEN.W))
    val pending_mem_trap = mmio_err_valid || cache_err_valid || store_err_valid

    val storeBuffer = Module(new StoreBuffer(4, XLEN, XLEN))
    // Multi-cycle memory operations hold the upstream pipeline stage while the
    // request is outstanding. This bit prevents the held instruction from being
    // accepted again on the release cycle.
    val inputConsumed = RegInit(false.B)
    val consumedPc = RegInit(0.U(XLEN.W))
    val consumedOp = RegInit(MemOpType.None)
    val consumedAddr = RegInit(0.U(XLEN.W))
    val consumedAtomic = RegInit(AtomicOpType.None)
    val consumedRd = RegInit(0.U(5.W))
    val loadWbSlotValid = RegInit(false.B)
    val loadWbSlotRd = RegInit(0.U(5.W))
    val loadWbSlotRegWrite = RegInit(false.B)
    val loadWbSlotData = RegInit(0.U(XLEN.W))
    val loadWbSlotPc = RegInit(0.U(XLEN.W))
    val loadWbSlotInstr = RegInit(0.U(32.W))
    val loadWbSlotInstrLen = RegInit(0.U(2.W))
    val loadWbSlotDiffSkip = RegInit(false.B)
    val sameConsumedInput = inputConsumed &&
        consumedPc === io.pc_in &&
        consumedOp === memAccess.op &&
        consumedAddr === memAccess.paddr &&
        consumedAtomic === memAccess.atomic &&
        consumedRd === io.alu_out.rd

    val splitStorePending = RegInit(false.B)
    val splitStorePc = RegInit(0.U(XLEN.W))
    val splitStoreInstr = RegInit(0.U(32.W))
    val splitStoreInstrLen = RegInit(0.U(2.W))
    val splitStoreVaddr = RegInit(0.U(XLEN.W))
    val splitStoreAddr = RegInit(0.U(XLEN.W))
    val splitStoreData = RegInit(0.U(XLEN.W))
    val splitStoreMask = RegInit(0.U((XLEN / 8).W))
    val splitStoreSize = RegInit(0.U(3.W))
    val splitStoreRetireValid = RegInit(false.B)
    val splitStoreRetirePc = RegInit(0.U(XLEN.W))
    val splitStoreRetireInstr = RegInit(0.U(32.W))
    val splitStoreRetireInstrLen = RegInit(0.U(2.W))

    val storeOffset = addr(beatOffsetBits - 1, 0)
    val storeShiftBits = Cat(storeOffset, 0.U(3.W))
    val storeBaseMask = MuxLookup(memAccess.size, 0.U((XLEN / 8).W))(
        Seq(
            0.U -> 1.U,
            1.U -> 3.U,
            2.U -> 15.U,
            3.U -> 255.U
        )
    )
    val storeLowMask = (storeBaseMask << storeOffset)((XLEN / 8) - 1, 0)
    val storeLowData = io.alu_out.result << storeShiftBits
    val storeHighShiftBytes = (XLEN / 8).U - storeOffset
    val storeHighMask = storeBaseMask >> storeHighShiftBytes
    val storeHighData = io.alu_out.result >> Cat(storeHighShiftBytes, 0.U(3.W))
    val storeLowAddr = Mux(split_cache_store, alignBeat(addr), addr)
    val storeLowVaddr = Mux(split_cache_store, alignBeat(memAccess.vaddr), memAccess.vaddr)

    val currentStoreValid = is_store && !is_device && !translationNotReady && !mem_addr_exception && !access_fault &&
        !pending_mem_trap && !sameConsumedInput
    storeBuffer.io.enq_valid := splitStorePending || currentStoreValid
    storeBuffer.io.enq_pc    := Mux(splitStorePending, splitStorePc, io.pc_in)
    storeBuffer.io.enq_vaddr := Mux(splitStorePending, splitStoreVaddr, storeLowVaddr)
    storeBuffer.io.enq_addr  := Mux(splitStorePending, splitStoreAddr, storeLowAddr)
    storeBuffer.io.enq_data  := Mux(splitStorePending, splitStoreData, Mux(memAccess.attrs.cacheable, storeLowData, wdata_aligned))
    storeBuffer.io.enq_mask  := Mux(splitStorePending, splitStoreMask, Mux(memAccess.attrs.cacheable, storeLowMask, strb))
    storeBuffer.io.enq_size  := Mux(splitStorePending, splitStoreSize, memAccess.size)
    val storeEnqFire = storeBuffer.io.enq_valid && storeBuffer.io.enq_ready

    when(storeEnqFire && splitStorePending) {
        splitStorePending := false.B
        splitStoreRetireValid := true.B
        splitStoreRetirePc := splitStorePc
        splitStoreRetireInstr := splitStoreInstr
        splitStoreRetireInstrLen := splitStoreInstrLen
    }.elsewhen(storeEnqFire && split_cache_store) {
        splitStorePending := true.B
        splitStorePc := io.pc_in
        splitStoreInstr := io.alu_out.instr
        splitStoreInstrLen := io.alu_out.instr_len
        splitStoreVaddr := alignBeat(memAccess.vaddr) + (XLEN / 8).U
        splitStoreAddr := alignBeat(addr) + (XLEN / 8).U
        splitStoreData := storeHighData
        splitStoreMask := storeHighMask
        splitStoreSize := memAccess.size
    }

    when(storeEnqFire && split_cache_store) {
        inputConsumed := true.B
        consumedPc := io.pc_in
        consumedOp := memAccess.op
        consumedAddr := memAccess.paddr
        consumedAtomic := memAccess.atomic
        consumedRd := io.alu_out.rd
    }

    storeBuffer.io.search_addr := Mux(is_load && !is_device && !translationNotReady && !split_cache_load && !access_fault, addr, 0.U)
    storeBuffer.io.search_mask := Mux(is_load && !is_device && !translationNotReady && !split_cache_load && !access_fault, memAccess.mask, 0.U)

    val raw_load_hit_sb = is_load && !is_device && !split_cache_load && !access_fault && storeBuffer.io.search_hit
    val load_conflicts_sb = is_load && !is_device && !split_cache_load && !access_fault && storeBuffer.io.search_conflict
    val load_hit_sb    = raw_load_hit_sb && !loadWbSlotValid
    val load_miss_sb   = is_load && !is_device && !storeBuffer.io.search_hit && !storeBuffer.io.search_conflict
    val sb_has_data    = storeBuffer.io.deq_valid
    val cacheLoadPending = RegInit(false.B)
    val cacheLoadSent    = RegInit(false.B)
    val cacheLoadAccess  = RegInit(0.U.asTypeOf(new MemoryAccessInfo(XLEN)))
    val cacheLoadPc      = RegInit(0.U(XLEN.W))
    val cacheLoadInstr   = RegInit(0.U(32.W))
    val cacheLoadInstrLen = RegInit(0.U(2.W))
    val cacheLoadRd      = RegInit(0.U(5.W))
    val cacheLoadRegWrite = RegInit(false.B)
    val cacheLoadSplit   = RegInit(false.B)
    val cacheLoadSecond  = RegInit(false.B)
    val cacheLoadLowData = RegInit(0.U(XLEN.W))

    val mmioPending = RegInit(false.B)
    val mmioSent    = RegInit(false.B)
    val mmioAccess  = RegInit(0.U.asTypeOf(new MemoryAccessInfo(XLEN)))
    val mmioPc      = RegInit(0.U(XLEN.W))
    val mmioInstr   = RegInit(0.U(32.W))
    val mmioInstrLen = RegInit(0.U(2.W))
    val mmioRd      = RegInit(0.U(5.W))
    val mmioRegWrite = RegInit(false.B)

    val storeDrainPending = RegInit(false.B)
    val storeDrainPc      = RegInit(0.U(XLEN.W))
    val storeDrainVaddr   = RegInit(0.U(XLEN.W))
    val fenceRetireValid = RegInit(false.B)
    val fenceRetirePc    = RegInit(0.U(XLEN.W))
    val fenceRetireInstr = RegInit(0.U(32.W))
    val fenceRetireInstrLen = RegInit(0.U(2.W))

    // Single-hart LR/SC reservation. Coherence-aware invalidation can replace this when multi-hart support lands.
    val reservationValid = RegInit(false.B)
    val reservationAddr  = RegInit(0.U(XLEN.W))
    val reservationSize  = RegInit(0.U(3.W))

    // Atomics are serialized here as cache read plus optional cache write; TileLink Atomic opcodes are not used yet.
    val atomicPending = RegInit(false.B)
    val atomicReadSent = RegInit(false.B)
    val atomicWriteSent = RegInit(false.B)
    val atomicDoWrite = RegInit(false.B)
    val atomicAccess = RegInit(0.U.asTypeOf(new MemoryAccessInfo(XLEN)))
    val atomicPc = RegInit(0.U(XLEN.W))
    val atomicInstr = RegInit(0.U(32.W))
    val atomicInstrLen = RegInit(0.U(2.W))
    val atomicRd = RegInit(0.U(5.W))
    val atomicRegWrite = RegInit(false.B)
    val atomicOldData = RegInit(0.U(XLEN.W))
    val atomicWriteData = RegInit(0.U(XLEN.W))
    val atomicRespValid = RegInit(false.B)
    val atomicRespData = RegInit(0.U(XLEN.W))
    val atomicRespErr = RegInit(false.B)

    val memoryOpsIdle = !sb_has_data && !storeDrainPending && !cacheLoadPending && !mmioPending && !atomicPending
    io.memory_idle := memoryOpsIdle && !splitStorePending && !xlatePending && !xlateDone && !pending_mem_trap
    val startTranslation = rawNeedsTranslation && !sameTranslatedInput && !xlatePending && !xlateDone &&
        !rawStageFault.valid && memoryOpsIdle && !pending_mem_trap
    val translationBusy = startTranslation || xlatePending
    val translatedAccessType = Mux(
        xlateAccess.op === MemOpType.Load || xlateAccess.op === MemOpType.LR,
        Sv39AccessType.Load,
        Sv39AccessType.Store
    )
    val translatedPmp = Module(new PmpAccessChecker(XLEN))
    translatedPmp.io.valid := xlatePending && ptw.io.resp.fire && !ptw.io.resp.bits.fault.valid
    translatedPmp.io.addr := ptw.io.resp.bits.paddr
    translatedPmp.io.size := xlateAccess.size
    translatedPmp.io.isStore := translatedAccessType === Sv39AccessType.Store
    translatedPmp.io.priv := io.mem_cfg.data_priv
    translatedPmp.io.pmpcfg0 := io.mem_cfg.pmpcfg0
    translatedPmp.io.pmpaddr := io.mem_cfg.pmpaddr

    ptw.io.req.valid := xlatePending
    ptw.io.req.bits.vaddr := xlateAccess.vaddr
    ptw.io.req.bits.satp := io.mem_cfg.satp
    ptw.io.req.bits.access := translatedAccessType
    ptw.io.req.bits.priv := io.mem_cfg.data_priv
    ptw.io.req.bits.mxr := io.mem_cfg.mxr
    ptw.io.req.bits.sum := io.mem_cfg.sum
    ptw.io.resp.ready := true.B

    when(startTranslation) {
        xlatePending := true.B
        xlateDone := false.B
        xlateAccess := rawMemAccess
        xlateFault := 0.U.asTypeOf(xlateFault)
        xlatePc := io.pc_in
        xlateRd := io.alu_out.rd
        xlateAtomic := rawMemAccess.atomic
    }.elsewhen(xlatePending && ptw.io.resp.fire) {
        val translatedPaddr = ptw.io.resp.bits.paddr
        val translatedInSram = paddrInSram(translatedPaddr)
        xlatePending := false.B
        xlateDone := true.B
        xlateAccess.paddr := translatedPaddr
        xlateAccess.attrs.cacheable := translatedInSram
        xlateAccess.attrs.device := paddrInDevice(translatedPaddr)
        xlateAccess.attrs.bufferable := translatedInSram
        xlateAccess.attrs.allocate := translatedInSram
        xlateAccess.attrs.translate := false.B
        xlateAccess.attrs.executable := paddrInRom(translatedPaddr)
        xlateFault := ptw.io.resp.bits.fault
        when(!ptw.io.resp.bits.fault.valid && translatedPmp.io.fault) {
            xlateFault.valid := true.B
            xlateFault.cause := Mux(
                translatedAccessType === Sv39AccessType.Store,
                MCause.StoreAccessFault,
                MCause.LoadAccessFault
            )
            xlateFault.value := xlateAccess.vaddr
        }
    }.elsewhen(xlateDone && !sameTranslatedInput) {
        xlateDone := false.B
        xlateFault := 0.U.asTypeOf(xlateFault)
    }

    val raw_cache_load = is_load && !is_device && !translationNotReady && !translationBusy &&
        !raw_load_hit_sb && !load_conflicts_sb && !mem_addr_exception && !access_fault && !sameConsumedInput
    val raw_mmio_req   = memAccess.valid && !translationBusy && !mem_addr_exception && !access_fault && is_device && (is_load || is_store) && !sameConsumedInput
    val raw_atomic_req = memAccess.valid && !translationBusy && !mem_addr_exception && !atomic_device_fault && !access_fault && !is_device && is_atomic && !sameConsumedInput
    val raw_fence_req = memAccess.valid && !translationBusy && !mem_addr_exception && !access_fault && is_fence && !sameConsumedInput

    val new_fence_req = raw_fence_req && !sb_has_data && !storeDrainPending && !cacheLoadPending && !mmioPending && !atomicPending && !pending_mem_trap
    val new_atomic_req = raw_atomic_req && !atomicPending && !sb_has_data && !storeDrainPending && !cacheLoadPending && !mmioPending && !pending_mem_trap
    // Split misaligned loads are serialized behind the store buffer because a
    // single store-buffer CAM hit cannot prove both cache beats are covered.
    val new_cache_load = raw_cache_load && !loadWbSlotValid && !cacheLoadPending && !atomicPending &&
        !sb_has_data && !storeDrainPending && !pending_mem_trap
    val new_mmio_req   = raw_mmio_req && !mmioPending && !atomicPending && !pending_mem_trap

    when(!cacheLoadPending && new_cache_load) {
        cacheLoadPending := true.B
        cacheLoadSent    := false.B
        cacheLoadAccess  := memAccess
        cacheLoadPc      := io.pc_in
        cacheLoadInstr   := io.alu_out.instr
        cacheLoadInstrLen := io.alu_out.instr_len
        cacheLoadRd      := io.alu_out.rd
        cacheLoadRegWrite := io.alu_out.reg_write
        cacheLoadSplit   := split_cache_load
        cacheLoadSecond  := false.B
        cacheLoadLowData := 0.U
        inputConsumed := true.B
        consumedPc := io.pc_in
        consumedOp := memAccess.op
        consumedAddr := memAccess.paddr
        consumedAtomic := memAccess.atomic
        consumedRd := io.alu_out.rd
    }

    when(!mmioPending && new_mmio_req) {
        mmioPending := true.B
        mmioSent    := false.B
        mmioAccess  := memAccess
        mmioPc      := io.pc_in
        mmioInstr   := io.alu_out.instr
        mmioInstrLen := io.alu_out.instr_len
        mmioRd      := io.alu_out.rd
        mmioRegWrite := io.alu_out.reg_write
        inputConsumed := true.B
        consumedPc := io.pc_in
        consumedOp := memAccess.op
        consumedAddr := memAccess.paddr
        consumedAtomic := memAccess.atomic
        consumedRd := io.alu_out.rd
    }

    when(!atomicPending && new_atomic_req) {
        atomicPending   := true.B
        atomicReadSent  := false.B
        atomicWriteSent := false.B
        atomicDoWrite   := false.B
        atomicAccess    := memAccess
        atomicPc        := io.pc_in
        atomicInstr     := io.alu_out.instr
        atomicInstrLen  := io.alu_out.instr_len
        atomicRd        := io.alu_out.rd
        atomicRegWrite  := io.alu_out.reg_write
        inputConsumed   := true.B
        consumedPc      := io.pc_in
        consumedOp      := memAccess.op
        consumedAddr    := memAccess.paddr
        consumedAtomic  := memAccess.atomic
        consumedRd      := io.alu_out.rd
    }
    when(new_fence_req) {
        fenceRetireValid := true.B
        fenceRetirePc := io.pc_in
        fenceRetireInstr := io.alu_out.instr
        fenceRetireInstrLen := io.alu_out.instr_len
        reservationValid := false.B
        inputConsumed := true.B
        consumedPc := io.pc_in
        consumedOp := memAccess.op
        consumedAddr := memAccess.paddr
        consumedAtomic := memAccess.atomic
        consumedRd := io.alu_out.rd
    }

    val issue_new_cache_load = new_cache_load && !cacheLoadPending && !split_cache_load
    val do_cache_load_req = issue_new_cache_load || (cacheLoadPending && !cacheLoadSent)
    val do_mmio_req       = mmioPending && !mmioSent
    val do_atomic_read_req = atomicPending && !atomicReadSent
    val do_atomic_write_req = atomicPending && atomicReadSent && atomicDoWrite && !atomicWriteSent
    val do_store_drain    =
        sb_has_data && !storeDrainPending && !cacheLoadPending && !mmioPending && !atomicPending &&
            !splitStorePending && !new_cache_load && !new_mmio_req && !new_atomic_req && !new_fence_req && !pending_mem_trap

    val loadReqBaseAddr = Mux(issue_new_cache_load, memAccess.paddr, cacheLoadAccess.paddr)
    val loadReqBeatAddr = Mux(
        cacheLoadSplit,
        Mux(cacheLoadSecond, alignBeat(cacheLoadAccess.paddr) + (XLEN / 8).U, alignBeat(loadReqBaseAddr)),
        loadReqBaseAddr
    )
    val cacheReqAddr = Mux(
        do_cache_load_req,
        loadReqBeatAddr,
        Mux(do_atomic_read_req || do_atomic_write_req, atomicAccess.paddr, storeBuffer.io.deq_addr)
    )
    val cacheReqVaddr = Mux(
        do_cache_load_req,
        Mux(issue_new_cache_load, memAccess.vaddr, cacheLoadAccess.vaddr),
        Mux(do_atomic_read_req || do_atomic_write_req, atomicAccess.vaddr, storeBuffer.io.deq_vaddr)
    )
    val cacheReqIsWrite = do_store_drain || do_atomic_write_req

    val normalDcacheReqValid = do_cache_load_req || do_store_drain || do_atomic_read_req || do_atomic_write_req
    val normalDcacheReqBits = Wire(new CacheReq(XLEN, XLEN))
    normalDcacheReqBits.addr      := cacheReqAddr
    normalDcacheReqBits.vaddr     := cacheReqVaddr
    normalDcacheReqBits.cmd       := Mux(cacheReqIsWrite, CacheCmd.Write, CacheCmd.Read)
    normalDcacheReqBits.wdata     := Mux(do_atomic_write_req, atomicWriteData, storeBuffer.io.deq_data)
    normalDcacheReqBits.mask      := Mux(do_atomic_read_req || do_atomic_write_req, atomicAccess.mask, storeBuffer.io.deq_mask)
    normalDcacheReqBits.size      := Mux(do_cache_load_req, Mux(issue_new_cache_load, memAccess.size, cacheLoadAccess.size), Mux(do_atomic_read_req || do_atomic_write_req, atomicAccess.size, storeBuffer.io.deq_size))
    normalDcacheReqBits.signed    := Mux(do_cache_load_req, Mux(issue_new_cache_load, memAccess.signed, cacheLoadAccess.signed), false.B)
    normalDcacheReqBits.fence     := false.B
    normalDcacheReqBits.fencei    := false.B
    normalDcacheReqBits.atomic    := false.B
    normalDcacheReqBits.cacheable := true.B
    normalDcacheReqBits.device    := false.B

    ptw.io.mem.req.ready := xlatePending && io.dcache.req.ready
    ptw.io.mem.resp.valid := xlatePending && io.dcache.resp.valid
    ptw.io.mem.resp.bits := io.dcache.resp.bits

    io.dcache.req.valid := Mux(xlatePending, ptw.io.mem.req.valid, normalDcacheReqValid)
    io.dcache.req.bits  := Mux(xlatePending, ptw.io.mem.req.bits, normalDcacheReqBits)

    io.mmio.req_valid := do_mmio_req
    io.mmio.req_addr  := mmioAccess.paddr
    io.mmio.req_cmd   := Mux(mmioAccess.op === MemOpType.Load, TLOpcode.Get, TLOpcode.PutPartialData)
    io.mmio.req_data  := mmioAccess.wdata
    io.mmio.req_mask  := mmioAccess.mask
    io.mmio.req_size  := mmioAccess.size

    val cache_load_fire  = do_cache_load_req && io.dcache.req.ready
    val pending_cache_load_fire = cacheLoadPending && !cacheLoadSent && io.dcache.req.ready
    val store_drain_fire = do_store_drain && io.dcache.req.ready
    val atomic_read_fire = do_atomic_read_req && io.dcache.req.ready
    val atomic_write_fire = do_atomic_write_req && io.dcache.req.ready
    val mmio_req_fire    = do_mmio_req && io.mmio.req_ready
    val instant_atomic_read_resp = atomic_read_fire && io.dcache.resp.valid

    // Cache ready 时，才能真实出队 Store 数据
    storeBuffer.io.deq_ready := store_drain_fire

    io.dcache.resp.ready := Mux(xlatePending, ptw.io.mem.resp.ready, true.B)

    when(cache_load_fire) {
        cacheLoadSent := true.B
    }
    when(store_drain_fire) {
        storeDrainPending := true.B
        storeDrainPc      := storeBuffer.io.deq_pc
        storeDrainVaddr   := storeBuffer.io.deq_vaddr
        reservationValid  := false.B
    }
    when(atomic_read_fire) {
        atomicReadSent := true.B
    }
    when(atomic_write_fire) {
        atomicWriteSent := true.B
        reservationValid := false.B
    }
    when(fenceRetireValid) {
        fenceRetireValid := false.B
    }
    when(splitStoreRetireValid) {
        splitStoreRetireValid := false.B
    }
    when(mmio_req_fire) {
        mmioSent := true.B
    }

    val instant_cache_load_resp = issue_new_cache_load && cache_load_fire && io.dcache.resp.valid

    // L1 can answer a held load request in the same cycle it is accepted
    // through its hit buffer. Treat that like an already-sent pending response
    // so the one-cycle response is not lost.
    val instant_pending_cache_load_resp = pending_cache_load_fire && io.dcache.resp.valid
    val pending_cache_load_resp = cacheLoadPending && (cacheLoadSent || instant_pending_cache_load_resp) && io.dcache.resp.valid
    val split_first_load_resp = pending_cache_load_resp && cacheLoadSplit && !cacheLoadSecond
    val split_first_load_ok = split_first_load_resp && !io.dcache.resp.bits.err
    val completing_pending_cache_load = pending_cache_load_resp && (!cacheLoadSplit || cacheLoadSecond || io.dcache.resp.bits.err)

    when(instant_cache_load_resp) {
        cacheLoadPending := false.B
        cacheLoadSent    := false.B
        cacheLoadSplit   := false.B
        cacheLoadSecond  := false.B
    }.elsewhen(split_first_load_ok) {
        cacheLoadLowData := io.dcache.resp.bits.rdata
        cacheLoadSent    := false.B
        cacheLoadSecond  := true.B
    }.elsewhen(completing_pending_cache_load) {
        cacheLoadPending := false.B
        cacheLoadSent    := false.B
        cacheLoadSplit   := false.B
        cacheLoadSecond  := false.B
    }
    when(storeDrainPending && io.dcache.resp.valid) {
        storeDrainPending := false.B
    }
    when((atomicPending && atomicReadSent && io.dcache.resp.valid && !atomicDoWrite) || instant_atomic_read_resp) {
        val atomicReadAccess = Mux(instant_atomic_read_resp, memAccess, atomicAccess)
        val oldValue = formatAtomicReadData(io.dcache.resp.bits.rdata, atomicReadAccess)
        val reservationHit = reservationValid &&
            reservationAddr === atomicReadAccess.paddr &&
            reservationSize === atomicReadAccess.size
        atomicOldData := oldValue
        atomicRespErr := io.dcache.resp.bits.err
        atomicRespValid := true.B
        when(io.dcache.resp.bits.err) {
            atomicRespData := 0.U
            atomicPending := false.B
            atomicReadSent := false.B
        }.elsewhen(atomicReadAccess.op === MemOpType.LR) {
            reservationValid := true.B
            reservationAddr  := atomicReadAccess.paddr
            reservationSize  := atomicReadAccess.size
            atomicRespData   := oldValue
            atomicPending    := false.B
            atomicReadSent   := false.B
        }.elsewhen(atomicReadAccess.op === MemOpType.SC) {
            when(reservationHit) {
                atomicWriteData := atomicReadAccess.wdata
                atomicDoWrite := true.B
                atomicRespValid := false.B
            }.otherwise {
                atomicRespData := 1.U
                atomicPending := false.B
                atomicReadSent := false.B
                reservationValid := false.B
            }
        }.otherwise {
            val newValue = computeAtomicWrite(oldValue, atomicReadAccess)
            atomicWriteData := formatAtomicWdata(newValue, atomicReadAccess)
            atomicRespData := oldValue
            atomicDoWrite := true.B
            atomicRespValid := false.B
        }
    }
    when(atomicPending && atomicReadSent && atomicDoWrite && atomicWriteSent && io.dcache.resp.valid) {
        atomicRespErr := io.dcache.resp.bits.err
        atomicRespValid := true.B
        when(atomicAccess.op === MemOpType.SC) {
            atomicRespData := Mux(io.dcache.resp.bits.err, 1.U, 0.U)
        }.otherwise {
            atomicRespData := atomicOldData
        }
        atomicPending := false.B
        atomicReadSent := false.B
        atomicWriteSent := false.B
        atomicDoWrite := false.B
    }
    when(mmioPending && mmioSent && io.mmio.resp_valid) {
        mmioPending := false.B
        mmioSent    := false.B
    }
    val completing_cache_load  = completing_pending_cache_load || instant_cache_load_resp
    val completing_store_drain = storeDrainPending && io.dcache.resp.valid
    val completing_mmio        = mmioPending && mmioSent && io.mmio.resp_valid

    val stall_sb_full          = (is_store || splitStorePending) && !mem_addr_exception && !access_fault && !storeBuffer.io.enq_ready
    val stall_wait_split_store = (split_cache_store && !sameConsumedInput) || splitStorePending
    val stall_wait_store_drain = (raw_cache_load && (storeDrainPending || sb_has_data)) ||
        load_conflicts_sb || (is_load && !is_device && split_cache_load && sb_has_data)
    val stall_wait_atomic_store_drain = raw_atomic_req && (sb_has_data || storeDrainPending)
    val stall_wait_load_slot   = (raw_load_hit_sb || raw_cache_load) && loadWbSlotValid
    val stall_wait_cache_load  =
        (new_cache_load && !instant_cache_load_resp) || (cacheLoadPending && !completing_cache_load) ||
            stall_wait_store_drain || stall_wait_load_slot
    val stall_wait_mmio        = new_mmio_req || mmioPending
    val stall_wait_atomic      = new_atomic_req || atomicPending
    val stall_wait_fence       = raw_fence_req

    val stall_wait_translation = translationNotReady
    io.stall_req := stall_wait_translation || translationBusy || stall_sb_full || stall_wait_split_store || stall_wait_cache_load ||
        stall_wait_mmio || stall_wait_atomic || stall_wait_atomic_store_drain || stall_wait_fence
    io.stall_load := (is_load && stall_wait_translation) || translationBusy || stall_wait_cache_load
    io.stall_store := stall_sb_full || stall_wait_split_store || storeDrainPending || (sb_has_data && !storeDrainPending)
    io.stall_mmio := stall_wait_mmio
    io.stall_atomic := stall_wait_atomic || stall_wait_atomic_store_drain
    io.stall_fence := stall_wait_fence
    val consumingNewInput = new_cache_load || new_mmio_req || new_atomic_req || new_fence_req
    when(inputConsumed && !sameConsumedInput && !consumingNewInput) {
        inputConsumed := false.B
    }

    val wb_data        = Wire(UInt(XLEN.W))
    val default_result = io.alu_out.result
    wb_data := 0.U

    val is_load_resp      = completing_cache_load
    val is_mmio_load_resp = completing_mmio && mmioAccess.op === MemOpType.Load
    val is_mmio_store_resp = completing_mmio && mmioAccess.op === MemOpType.Store
    val is_cache_resp_err = completing_cache_load && io.dcache.resp.bits.err
    val is_store_resp_err = completing_store_drain && io.dcache.resp.bits.err
    val is_mmio_resp_err  = completing_mmio && io.mmio.resp_err
    val is_atomic_resp = atomicRespValid
    val loadRespAccess = Mux(instant_cache_load_resp, memAccess, cacheLoadAccess)
    val loadRespPc = Mux(instant_cache_load_resp, io.pc_in, cacheLoadPc)
    val loadRespInstr = Mux(instant_cache_load_resp, io.alu_out.instr, cacheLoadInstr)
    val loadRespInstrLen = Mux(instant_cache_load_resp, io.alu_out.instr_len, cacheLoadInstrLen)
    val loadRespRd = Mux(instant_cache_load_resp, io.alu_out.rd, cacheLoadRd)
    val loadRespRegWrite = Mux(instant_cache_load_resp, io.alu_out.reg_write, cacheLoadRegWrite)
    val cacheRespLoadData = Mux(
        cacheLoadSplit && cacheLoadSecond,
        formatSplitLoadData(cacheLoadLowData, io.dcache.resp.bits.rdata, loadRespAccess),
        formatLoadData(io.dcache.resp.bits.rdata, loadRespAccess)
    )
    val slotRespValid = (completing_pending_cache_load && !is_cache_resp_err) ||
        (is_mmio_load_resp && !is_mmio_resp_err) ||
        (is_mmio_store_resp && !is_mmio_resp_err) ||
        (is_atomic_resp && !atomicRespErr)
	    val load_data_valid   = load_hit_sb || (is_load_resp && !is_cache_resp_err) || (is_mmio_load_resp && !is_mmio_resp_err) || (is_atomic_resp && !atomicRespErr)
	    val slotLoadDataValid = loadWbSlotValid || (is_mmio_load_resp && !is_mmio_resp_err) || (is_atomic_resp && !atomicRespErr)
	    val load_data_rd      = Mux(
	        load_hit_sb,
	        io.alu_out.rd,
	        Mux(is_load_resp, loadRespRd, Mux(is_mmio_load_resp, mmioRd, Mux(is_atomic_resp, atomicRd, 0.U)))
	    )
    val load_data         = Mux(
        load_hit_sb,
        formatLoadData(storeBuffer.io.search_data, memAccess),
        Mux(
            is_load_resp,
            cacheRespLoadData,
	            Mux(is_mmio_load_resp, formatLoadData(io.mmio.resp_data, mmioAccess), Mux(is_atomic_resp, atomicRespData, 0.U))
	        )
	    )
	    val update_en = !io.stall_req
	    val writeback_en = update_en || load_data_valid
	    val normalStageValid = valid_inst && !sameConsumedInput
	    val normalOutputBusy = RegNext(normalStageValid && writeback_en && !is_load_resp && !slotRespValid, false.B)
	    val loadHitSbSlot = load_hit_sb && normalOutputBusy
	    // Variable-latency responses can arrive while the original LSU input is no
	    // longer the architectural instruction being retired. Capture both data and
	    // sideband so WB/DiffTest see a coherent commit packet on the next cycle.
	    when(loadWbSlotValid) {
	        loadWbSlotValid := false.B
	    }.elsewhen(loadHitSbSlot) {
	        loadWbSlotValid := true.B
	        loadWbSlotRd := io.alu_out.rd
	        loadWbSlotRegWrite := io.alu_out.reg_write
	        loadWbSlotData := formatLoadData(storeBuffer.io.search_data, memAccess)
	        loadWbSlotPc := io.pc_in
	        loadWbSlotInstr := io.alu_out.instr
	        loadWbSlotInstrLen := io.alu_out.instr_len
	        loadWbSlotDiffSkip := false.B
	    }.elsewhen(is_load_resp && !is_cache_resp_err) {
	        loadWbSlotValid := true.B
	        loadWbSlotRd := loadRespRd
        loadWbSlotRegWrite := loadRespRegWrite
        loadWbSlotData := cacheRespLoadData
        loadWbSlotPc := loadRespPc
        loadWbSlotInstr := loadRespInstr
        loadWbSlotInstrLen := loadRespInstrLen
        loadWbSlotDiffSkip := false.B
    }.elsewhen(is_mmio_load_resp && !is_mmio_resp_err) {
        loadWbSlotValid := true.B
        loadWbSlotRd := mmioRd
        loadWbSlotRegWrite := mmioRegWrite
        loadWbSlotData := formatLoadData(io.mmio.resp_data, mmioAccess)
        loadWbSlotPc := mmioPc
        loadWbSlotInstr := mmioInstr
        loadWbSlotInstrLen := mmioInstrLen
        loadWbSlotDiffSkip := true.B
    }.elsewhen(is_mmio_store_resp && !is_mmio_resp_err) {
        loadWbSlotValid := true.B
        loadWbSlotRd := 0.U
        loadWbSlotRegWrite := false.B
        loadWbSlotData := 0.U
        loadWbSlotPc := mmioPc
        loadWbSlotInstr := mmioInstr
        loadWbSlotInstrLen := mmioInstrLen
        loadWbSlotDiffSkip := true.B
    }.elsewhen(is_atomic_resp && !atomicRespErr) {
        loadWbSlotValid := true.B
        loadWbSlotRd := atomicRd
        loadWbSlotRegWrite := atomicRegWrite
        loadWbSlotData := atomicRespData
        loadWbSlotPc := atomicPc
        loadWbSlotInstr := atomicInstr
        loadWbSlotInstrLen := atomicInstrLen
        loadWbSlotDiffSkip := false.B
    }
    val stall_valid      = RegInit(false.B)
    val stall_wb_data    = RegInit(0.U(XLEN.W))
    val stall_load_valid = RegInit(false.B)
    val stall_load_rd    = RegInit(0.U(5.W))

    when(is_load_resp && !is_cache_resp_err) {
        wb_data := cacheRespLoadData
    }.elsewhen(is_mmio_load_resp && !is_mmio_resp_err) {
        wb_data := formatLoadData(io.mmio.resp_data, mmioAccess)
    }.elsewhen(is_atomic_resp && !atomicRespErr) {
        wb_data := atomicRespData
    }.elsewhen(load_hit_sb) {
        wb_data := formatLoadData(storeBuffer.io.search_data, memAccess)
    }.elsewhen(!io.stall_req && stall_valid) {
        wb_data := stall_wb_data
    }.otherwise {
        wb_data := default_result
    }

    val stallResultValid = !is_load || load_data_valid
    when(io.stall_req && stallResultValid) {
        stall_valid      := true.B
        stall_wb_data    := wb_data
        stall_load_valid := load_data_valid
        stall_load_rd    := load_data_rd
    }.otherwise {
        stall_valid      := false.B
        stall_wb_data    := 0.U
        stall_load_valid := false.B
        stall_load_rd    := 0.U
    }

    when(is_mmio_resp_err) {
        mmio_err_valid := true.B
        mmio_err_pc    := mmioPc
        mmio_err_cause := Mux(mmioAccess.op === MemOpType.Store, MCause.StoreAccessFault, MCause.LoadAccessFault)
        mmio_err_value := mmioAccess.vaddr
    }.elsewhen(!io.stall_req && mmio_err_valid) {
        mmio_err_valid := false.B
    }

    when(is_cache_resp_err) {
        cache_err_valid := true.B
        cache_err_pc    := loadRespPc
        cache_err_cause := MCause.LoadAccessFault
        cache_err_value := loadRespAccess.vaddr
    }.elsewhen(!io.stall_req && cache_err_valid) {
        cache_err_valid := false.B
    }

    when(is_store_resp_err) {
        store_err_valid := true.B
        store_err_pc    := storeDrainPc
        store_err_value := storeDrainVaddr
    }.elsewhen(!io.stall_req && store_err_valid) {
        store_err_valid := false.B
    }
    when(atomicRespValid && atomicRespErr) {
        cache_err_valid := true.B
        cache_err_pc    := atomicPc
        cache_err_cause := Mux(atomicAccess.op === MemOpType.LR, MCause.LoadAccessFault, MCause.StoreAccessFault)
        cache_err_value := atomicAccess.vaddr
    }
    when(!atomicPending && atomicRespValid) {
        atomicRespValid := false.B
    }

	    val response_rd = Mux(
	        is_load_resp,
	        loadRespRd,
	        Mux(is_mmio_load_resp, mmioRd, Mux(is_atomic_resp, atomicRd, io.alu_out.rd))
	    )
    val response_reg_write = Mux(
        is_load_resp,
        loadRespRegWrite,
        Mux(is_mmio_load_resp, mmioRegWrite, Mux(is_atomic_resp, atomicRegWrite, io.alu_out.reg_write))
    )
    val out_reg_rd    = RegNext(response_rd, 0.U)
	    val normalLoadDataValid = load_data_valid && !is_load_resp && !slotLoadDataValid && !loadHitSbSlot
    val out_reg_write = RegNext(response_reg_write && writeback_en && !is_load_resp, false.B)
    val out_result    = RegNext(wb_data, 0.U)
    // val out_result    = RegNext(Mux(load_data_valid, load_data, wb_data), 0.U)
    val final_trap_info = WireInit(trap_info)
    when(cache_err_valid) {
        final_trap_info.valid  := true.B
        final_trap_info.pc     := cache_err_pc
        final_trap_info.cause  := cache_err_cause
        final_trap_info.value  := cache_err_value
        final_trap_info.is_ret := false.B
        final_trap_info.ret_type := TrapReturnType.None
    }.elsewhen(store_err_valid) {
        final_trap_info.valid  := true.B
        final_trap_info.pc     := store_err_pc
        final_trap_info.cause  := MCause.StoreAccessFault
        final_trap_info.value  := store_err_value
        final_trap_info.is_ret := false.B
        final_trap_info.ret_type := TrapReturnType.None
    }.elsewhen(mmio_err_valid) {
        final_trap_info.valid  := true.B
        final_trap_info.pc     := mmio_err_pc
        final_trap_info.cause  := mmio_err_cause
        final_trap_info.value  := mmio_err_value
        final_trap_info.is_ret := false.B
        final_trap_info.ret_type := TrapReturnType.None
    }

    val out_trap      = RegEnable(final_trap_info, 0.U.asTypeOf(io.trap_info_in), update_en)
    val out_pc        = RegEnable(io.pc_in, 0.U, update_en)
    val out_instr     = RegEnable(io.alu_out.instr, 0.U, update_en)
    val out_instr_len = RegEnable(io.alu_out.instr_len, 0.U, update_en)

	    val normalValidOut = RegNext(
	        (normalStageValid && writeback_en && !is_load_resp && !slotRespValid || normalLoadDataValid) &&
            !final_trap_info.valid,
        false.B
    )
    io.valid_out         := loadWbSlotValid || fenceRetireValid || splitStoreRetireValid || normalValidOut
    io.mem_out.instr     := Mux(loadWbSlotValid, loadWbSlotInstr, Mux(fenceRetireValid, fenceRetireInstr, Mux(splitStoreRetireValid, splitStoreRetireInstr, Mux(is_mmio_load_resp, mmioInstr, Mux(is_atomic_resp, atomicInstr, out_instr)))))
    io.mem_out.instr_len := Mux(loadWbSlotValid, loadWbSlotInstrLen, Mux(fenceRetireValid, fenceRetireInstrLen, Mux(splitStoreRetireValid, splitStoreRetireInstrLen, Mux(is_mmio_load_resp, mmioInstrLen, Mux(is_atomic_resp, atomicInstrLen, out_instr_len)))))
    io.mem_out.rd        := Mux(loadWbSlotValid, loadWbSlotRd, Mux(fenceRetireValid || splitStoreRetireValid, 0.U, Mux(normalLoadDataValid, response_rd, out_reg_rd)))
    io.mem_out.reg_write := Mux(loadWbSlotValid, loadWbSlotRegWrite, Mux(fenceRetireValid || splitStoreRetireValid, false.B, Mux(normalLoadDataValid, response_reg_write, out_reg_write)))
    io.mem_out.result    := Mux(loadWbSlotValid, loadWbSlotData, Mux(fenceRetireValid || splitStoreRetireValid, 0.U, Mux(normalLoadDataValid, load_data, out_result)))
    io.mem_out.diff_skip := loadWbSlotValid && loadWbSlotDiffSkip
    io.pc_out            := Mux(loadWbSlotValid, loadWbSlotPc, Mux(fenceRetireValid, fenceRetirePc, Mux(splitStoreRetireValid, splitStoreRetirePc, out_pc)))
    io.trap_info_out     := out_trap

    io.load_data_valid := loadWbSlotValid || load_data_valid || (!io.stall_req && stall_valid && stall_load_valid)
    io.load_data_rd    := Mux(loadWbSlotValid, loadWbSlotRd, Mux(!io.stall_req && stall_valid && stall_load_valid, stall_load_rd, load_data_rd))
    io.load_data       := Mux(loadWbSlotValid, loadWbSlotData, Mux(!io.stall_req && stall_valid && stall_load_valid, stall_wb_data, load_data))

    dontTouch(io.mem_cfg)
}
