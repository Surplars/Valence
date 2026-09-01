package soc.core.csr

import chisel3._
import chisel3.util._
import soc.isa.CSR
import soc.isa.InterruptCauseCode
import soc.core.pipeline.CSROps
import soc.core.pipeline.MemorySystemConfig
import soc.core.pipeline.TrapReturnType
import soc.isa.PrivilegeLevel
import soc.isa.Extension
import soc.config.Config
import soc.config.SoCFeatures

object MStatus {
	    val MIE  = 3
	    val MPIE = 7
	    val MPP  = 11
        val MPRV = 17
        val SUM  = 18
        val MXR  = 19

	    def setMIE(mstatus: UInt, enable: Bool): UInt = {
	        val mask = (BigInt(1) << MIE).U(mstatus.getWidth.W)
	        Mux(enable, mstatus | mask, mstatus & ~mask)
	    }
	    def setMPIE(mstatus: UInt, enable: Bool): UInt = {
	        val mask = (BigInt(1) << MPIE).U(mstatus.getWidth.W)
	        Mux(enable, mstatus | mask, mstatus & ~mask)
	    }
	    def setMPP(mstatus: UInt, level: UInt): UInt = {
	        val mask = (BigInt(3) << MPP).U(mstatus.getWidth.W)
	        (mstatus & ~mask) | ((level & 3.U) << MPP)
	    }
        def getMPP(mstatus: UInt): UInt = mstatus(MPP + 1, MPP)
}

object SStatus {
    val SIE  = 1
    val SPIE = 5
    val SPP  = 8
    val SUM  = 18
    val MXR  = 19

    def setSIE(mstatus: UInt, enable: Bool): UInt = {
        val mask = (BigInt(1) << SIE).U(mstatus.getWidth.W)
        Mux(enable, mstatus | mask, mstatus & ~mask)
    }
    def setSPIE(mstatus: UInt, enable: Bool): UInt = {
        val mask = (BigInt(1) << SPIE).U(mstatus.getWidth.W)
        Mux(enable, mstatus | mask, mstatus & ~mask)
    }
    def setSPP(mstatus: UInt, level: UInt): UInt = {
        val mask = (BigInt(1) << SPP).U(mstatus.getWidth.W)
        Mux(level === PrivilegeLevel.Supervisor, mstatus | mask, mstatus & ~mask)
    }
}

object HpmEventId {
    val None = 0
    val Retire = 1
    val GlobalStall = 2
    val IFetchStall = 3
    val LSUStall = 4
    val Branch = 5
    val BranchTaken = 6
    val BranchRedirect = 7
    val BranchPredTaken = 8
    val BranchPredCorrect = 9
    val LSULoadStall = 10
    val LSUStoreStall = 11
    val LSUFenceStall = 12
    val LSUAtomicStall = 13
    val LSUMmioStall = 14
}

class CsrPerfEvents extends Bundle {
    val retire = Bool()
    val globalStall = Bool()
    val ifetchStall = Bool()
    val lsuStall = Bool()
    val branch = Bool()
    val branchTaken = Bool()
    val branchRedirect = Bool()
    val branchPredTaken = Bool()
    val branchPredCorrect = Bool()
    val lsuLoadStall = Bool()
    val lsuStoreStall = Bool()
    val lsuFenceStall = Bool()
    val lsuAtomicStall = Bool()
    val lsuMmioStall = Bool()
}

class CsrStateSnapshot(XLEN: Int) extends Bundle {
    val privilegeMode = UInt(XLEN.W)
    val mstatus = UInt(XLEN.W)
    val sstatus = UInt(XLEN.W)
    val mepc = UInt(XLEN.W)
    val sepc = UInt(XLEN.W)
    val mtval = UInt(XLEN.W)
    val stval = UInt(XLEN.W)
    val mtvec = UInt(XLEN.W)
    val stvec = UInt(XLEN.W)
    val mcause = UInt(XLEN.W)
    val scause = UInt(XLEN.W)
    val satp = UInt(XLEN.W)
    val mip = UInt(XLEN.W)
    val mie = UInt(XLEN.W)
    val mscratch = UInt(XLEN.W)
    val sscratch = UInt(XLEN.W)
    val mideleg = UInt(XLEN.W)
    val medeleg = UInt(XLEN.W)
}

class CSRFile(
    XLEN: Int = 64,
    hartID: Int,
    enabledExt: Set[Extension.Value] = Config.enabledExt,
    features: SoCFeatures = Config.features
) extends Module {
    val io = IO(new Bundle {
        // 读写接口
        val valid   = Input(Bool())
        val cmd     = Input(UInt(4.W))
        val addr    = Input(UInt(12.W))
        val write   = Input(Bool())
        val wdata   = Input(UInt(XLEN.W))
        val wvalid  = Input(Bool())
        val wcmd    = Input(UInt(4.W))
        val waddr   = Input(UInt(12.W))
        val wwrite  = Input(Bool())
        val wwdata  = Input(UInt(XLEN.W))
        val rdata   = Output(UInt(XLEN.W))
        val illegal = Output(Bool())
        // Debug abstract commands access CSRs while the core is halted.
        val debug_addr = Input(UInt(12.W))
        val debug_rdata = Output(UInt(XLEN.W))
        val debug_valid = Output(Bool())
        val debug_writable = Output(Bool())
        val debug_write = Input(Bool())
        val debug_wdata = Input(UInt(XLEN.W))
        val perf = Input(new CsrPerfEvents)
        // 硬件直接交互接口
        val trap_valid = Input(Bool())
        val trap_pc    = Input(UInt(XLEN.W))
        val trap_cause = Input(UInt(XLEN.W))
        val trap_value = Input(UInt(XLEN.W))
        val is_ret     = Input(Bool())
        val ret_type   = Input(TrapReturnType.Type())
        // 中断信号
        val msip = Input(Bool())
        val mtip = Input(Bool())
        val meip = Input(Bool())
        val ssip = Input(Bool())
        val stip = Input(Bool())
        val seip = Input(Bool())
        // 输出给Core的状态
        val epc_out         = Output(UInt(XLEN.W))
        val tvec_out        = Output(UInt(XLEN.W))
        val interrupt_cause = Output(UInt(XLEN.W))
        val ie_out          = Output(Bool()) // MIE全局中断使能
        val interrupt       = Output(Bool()) // 是否有待处理的中断
        val mem_cfg_out = Output(new MemorySystemConfig(XLEN))
        val state_snapshot = Output(new CsrStateSnapshot(XLEN))
    })

    val CurrentPrivLevel = RegInit(PrivilegeLevel.Machine)
    private def misaExtensionMask(enabled: Set[Extension.Value]): BigInt = {
        def bit(letter: Char): BigInt = BigInt(1) << (letter.toLower - 'a')
        val base = BigInt(0) |
            (if (enabled.contains(Extension.RV32I) || enabled.contains(Extension.RV64I)) bit('i') else BigInt(0)) |
            (if (enabled.contains(Extension.RV32M) || enabled.contains(Extension.RV64M)) bit('m') else BigInt(0)) |
            (if (enabled.contains(Extension.RV32A) || enabled.contains(Extension.RV64A)) bit('a') else BigInt(0)) |
            (if (enabled.contains(Extension.C)) bit('c') else BigInt(0)) |
            (if (enabled.contains(Extension.Zba) || enabled.contains(Extension.Zbb) || enabled.contains(Extension.Zbs))
                 bit('b')
             else BigInt(0)) |
            (if (enabled.contains(Extension.RV32F) || enabled.contains(Extension.RV64F)) bit('f') else BigInt(0)) |
            (if (enabled.contains(Extension.RV32D) || enabled.contains(Extension.RV64D)) bit('d') else BigInt(0)) |
            (if (enabled.contains(Extension.RV32Q) || enabled.contains(Extension.RV64Q)) bit('q') else BigInt(0))
        base
    }

    val misa_val = ((BigInt(2) << (XLEN - 2)) | misaExtensionMask(enabledExt)).U(XLEN.W)

    val mstatus   = RegInit(0.U(XLEN.W))
    val mideleg   = RegInit(0.U(XLEN.W))
    val medeleg   = RegInit(0.U(XLEN.W))
    val mtvec     = RegInit(0.U(XLEN.W))
    val mepc      = RegInit(0.U(XLEN.W))
    val mcause    = RegInit(0.U(XLEN.W))
    val mtval     = RegInit(0.U(XLEN.W))
    val mscratch  = RegInit(0.U(XLEN.W))
    val pmpcfg0   = RegInit(0.U(XLEN.W))
    val pmpaddr   = RegInit(VecInit(Seq.fill(8)(0.U(XLEN.W))))
    val mcounteren = RegInit(0.U(XLEN.W))
    val scounteren = RegInit(0.U(XLEN.W))
    val menvcfg    = RegInit(0.U(XLEN.W))
    val mcountinhibit = RegInit(0.U(XLEN.W))
    val timeCounter = RegInit(0.U(XLEN.W))
    val mcycle     = RegInit(0.U(XLEN.W))
    val minstret   = RegInit(0.U(XLEN.W))
    val mhpmcounter = RegInit(VecInit(Seq.fill(29)(0.U(XLEN.W))))
    val mhpmevent = RegInit(VecInit(Seq.fill(29)(0.U(XLEN.W))))
    val mnscratch = RegInit(0.U(XLEN.W))
    val mnepc     = RegInit(0.U(XLEN.W))
    val mncause   = RegInit(0.U(XLEN.W))
    val mnstatus  = RegInit(0.U(XLEN.W))
    val satp      = RegInit(0.U(XLEN.W))
    val mie       = RegInit(0.U(XLEN.W))       // 中断使能寄存器 (MSIE=3, MTIE=7, MEIE=11)
    val stvec     = RegInit(0.U(XLEN.W))
    val sepc      = RegInit(0.U(XLEN.W))
    val scause    = RegInit(0.U(XLEN.W))
    val stval     = RegInit(0.U(XLEN.W))
    val sscratch  = RegInit(0.U(XLEN.W))
    val ssipSw    = RegInit(false.B)
    val mip       = WireInit(0.U(XLEN.W))      // 中断 pending，部分由硬件连线

    private def hpmEventPulse(eventId: UInt): Bool = MuxLookup(eventId, false.B)(
        Seq(
            HpmEventId.Retire.U -> io.perf.retire,
            HpmEventId.GlobalStall.U -> io.perf.globalStall,
            HpmEventId.IFetchStall.U -> io.perf.ifetchStall,
            HpmEventId.LSUStall.U -> io.perf.lsuStall,
            HpmEventId.Branch.U -> io.perf.branch,
            HpmEventId.BranchTaken.U -> io.perf.branchTaken,
            HpmEventId.BranchRedirect.U -> io.perf.branchRedirect,
            HpmEventId.BranchPredTaken.U -> io.perf.branchPredTaken,
            HpmEventId.BranchPredCorrect.U -> io.perf.branchPredCorrect,
            HpmEventId.LSULoadStall.U -> io.perf.lsuLoadStall,
            HpmEventId.LSUStoreStall.U -> io.perf.lsuStoreStall,
            HpmEventId.LSUFenceStall.U -> io.perf.lsuFenceStall,
            HpmEventId.LSUAtomicStall.U -> io.perf.lsuAtomicStall,
            HpmEventId.LSUMmioStall.U -> io.perf.lsuMmioStall
        )
    )

    // Keep the base performance counters architecturally visible. time is a
    // monotonic counter independent of mcountinhibit; minstret uses the core
    // retire pulse, while mhpmcounter3..31 count selected IonSoC events.
    timeCounter := timeCounter + 1.U
    when(!mcountinhibit(0)) {
        mcycle := mcycle + 1.U
    }
    when(!mcountinhibit(2) && io.perf.retire) {
        minstret := minstret + 1.U
    }
    for (i <- 0 until 29) {
        val inhibitBit = i + 3
        when(!mcountinhibit(inhibitBit) && hpmEventPulse(mhpmevent(i)(7, 0))) {
            mhpmcounter(i) := mhpmcounter(i) + 1.U
        }
    }

    private def bitMask(bit: Int): UInt = (BigInt(1) << bit).U(XLEN.W)
    private def interruptCause(code: Int): UInt = ((BigInt(1) << (XLEN - 1)) | code).U(XLEN.W)
    private def causeBit(cause: UInt): UInt = {
        val index = cause(log2Ceil(XLEN) - 1, 0)
        (1.U(XLEN.W) << index)(XLEN - 1, 0)
    }
    private def trapVector(baseAndMode: UInt, cause: UInt): UInt = {
        val base = baseAndMode & ~3.U(XLEN.W)
        val mode = baseAndMode(1, 0)
        val code = cause(XLEN - 2, 0)
        Mux(cause(XLEN - 1) && mode === 1.U, base + (code << 2), base)
    }
    private def legalizeTrapVector(value: UInt): UInt = {
        val base = value & ~3.U(XLEN.W)
        val mode = Mux(value(1, 0) === 1.U, 1.U(XLEN.W), 0.U(XLEN.W))
        base | mode
    }
    private def legalizeSatp(value: UInt, current: UInt): UInt = {
        if (XLEN == 64) {
            val mode = value(63, 60)
            val supportedMode = mode === 0.U || (features.mmu.B && mode === 8.U)
            Mux(supportedMode, value, current)
        } else {
            val mode = value(31)
            val supportedMode = mode === 0.U || features.mmu.B
            Mux(supportedMode, value, current)
        }
    }

    val supervisorInterruptMask =
        bitMask(InterruptCauseCode.SupervisorSoft) |
            bitMask(InterruptCauseCode.SupervisorTimer) |
            bitMask(InterruptCauseCode.SupervisorExt)
    val writableMieMask =
        supervisorInterruptMask |
            bitMask(InterruptCauseCode.MachineSoft) |
            bitMask(InterruptCauseCode.MachineTimer) |
            bitMask(InterruptCauseCode.MachineExt)

    mip :=
        Mux(io.ssip || ssipSw, bitMask(InterruptCauseCode.SupervisorSoft), 0.U) |
            Mux(io.msip, bitMask(InterruptCauseCode.MachineSoft), 0.U) |
            Mux(io.stip, bitMask(InterruptCauseCode.SupervisorTimer), 0.U) |
            Mux(io.mtip, bitMask(InterruptCauseCode.MachineTimer), 0.U) |
            Mux(io.seip, bitMask(InterruptCauseCode.SupervisorExt), 0.U) |
            Mux(io.meip, bitMask(InterruptCauseCode.MachineExt), 0.U)

    val supervisorEnabled = enabledExt.contains(Extension.S).B
    val supervisorAndUserMask = ((BigInt(1) << ('s' - 'a')) | (BigInt(1) << ('u' - 'a'))).U(XLEN.W)
    val misa_val_with_s = Mux(supervisorEnabled, misa_val | supervisorAndUserMask, misa_val)

    private def sstatusView(status: UInt): UInt =
        (status & (bitMask(SStatus.SIE) | bitMask(SStatus.SPIE) | bitMask(SStatus.SPP))) |
            (status & (bitMask(13) | bitMask(14) | bitMask(15) | bitMask(18) | bitMask(19))) |
            (status & bitMask(63))

    val sstatus = sstatusView(mstatus)
    val sie = mie & mideleg & supervisorInterruptMask
    val sip = mip & mideleg & supervisorInterruptMask

    val mapping = Map(
        CSR.SSTATUS   -> sstatus,
        CSR.SIE       -> sie,
        CSR.STVEC     -> stvec,
        CSR.SSCRATCH  -> sscratch,
        CSR.SEPC      -> sepc,
        CSR.SCAUSE    -> scause,
        CSR.STVAL     -> stval,
        CSR.SIP       -> sip,
        CSR.MVENDORID  -> 0.U(XLEN.W),
        CSR.MARCHID    -> 0.U(XLEN.W),
        CSR.MIMPID     -> 0.U(XLEN.W),
        CSR.MHARTID    -> hartID.U(XLEN.W),
        CSR.MSTATUS    -> mstatus,
        CSR.MISA       -> misa_val_with_s,
        CSR.MEDELEG    -> medeleg,
        CSR.MIDELEG    -> mideleg,
        CSR.MIE        -> mie,
        CSR.MTVEC      -> mtvec,
        CSR.MCOUNTEREN -> mcounteren,
        CSR.MENVCFG    -> menvcfg,
        CSR.MCOUNTINHIBIT -> mcountinhibit,
        CSR.SCOUNTEREN -> scounteren,
        CSR.MSCRATCH   -> mscratch,
        CSR.MEPC       -> mepc,
        CSR.MCAUSE     -> mcause,
        CSR.MTVAL      -> mtval,
        CSR.MIP        -> mip,
        CSR.PMPcfg0    -> pmpcfg0,
        CSR.PMPcfg2    -> 0.U(XLEN.W),
        CSR.MCYCLE     -> mcycle,
        CSR.MINSTRET   -> minstret,
        CSR.CYCLE      -> mcycle,
        CSR.TIME       -> timeCounter,
        CSR.INSTRET    -> minstret,
        CSR.MNSCRATCH  -> mnscratch,
        CSR.MNEPC      -> mnepc,
        CSR.MNCAUSE    -> mncause,
        CSR.MNSTATUS   -> mnstatus,
        CSR.SATP       -> satp
    )

    private def isPmpAddr(addr: UInt): Bool = addr >= CSR.PMPaddr0 && addr <= CSR.PMPaddr15
    private def isActivePmpAddr(addr: UInt): Bool = addr >= CSR.PMPaddr0 && addr <= CSR.PMPaddr7
    private def pmpAddrIndex(addr: UInt): UInt = (addr - CSR.PMPaddr0)(2, 0)
    private def pmpAddrRead(addr: UInt): UInt =
        Mux(isActivePmpAddr(addr), pmpaddr(pmpAddrIndex(addr)), 0.U(XLEN.W))
    private val pmpAddrMask = ((BigInt(1) << (32 - 2)) - 1).U(XLEN.W)
    private def isMhpmCounter(addr: UInt): Bool = addr >= CSR.MHPMCOUNTER3 && addr <= CSR.MHPMCOUNTER31
    private def mhpmCounterIndex(addr: UInt): UInt = (addr - CSR.MHPMCOUNTER3)(4, 0)
    private def isMhpmEvent(addr: UInt): Bool = addr >= CSR.MHPMEVENT3 && addr <= CSR.MHPMEVENT31
    private def mhpmEventIndex(addr: UInt): UInt = (addr - CSR.MHPMEVENT3)(4, 0)
    private def counterEnableBit(addr: UInt): UInt = MuxLookup(addr, 0.U(log2Ceil(XLEN).W))(
        Seq(
            CSR.CYCLE -> 0.U,
            CSR.TIME -> 1.U,
            CSR.INSTRET -> 2.U
        )
    )
    private def isCounterView(addr: UInt): Bool = addr === CSR.CYCLE || addr === CSR.TIME || addr === CSR.INSTRET
    private def counterAccessOk(addr: UInt): Bool = {
        val bit = counterEnableBit(addr)
        Mux(
            !isCounterView(addr) || CurrentPrivLevel === PrivilegeLevel.Machine,
            true.B,
            Mux(
                CurrentPrivLevel === PrivilegeLevel.Supervisor,
                mcounteren(bit),
                mcounteren(bit) && scounteren(bit)
            )
        )
    }

    val rdata_pre = Mux(
        isPmpAddr(io.addr),
        pmpAddrRead(io.addr),
        Mux(
            isMhpmCounter(io.addr),
            mhpmcounter(mhpmCounterIndex(io.addr)),
            Mux(isMhpmEvent(io.addr), mhpmevent(mhpmEventIndex(io.addr)), MuxLookup(io.addr, 0.U)(mapping.toSeq))
        )
    )
    val wdata_read_pre = Mux(
        isPmpAddr(io.waddr),
        pmpAddrRead(io.waddr),
        Mux(
            isMhpmCounter(io.waddr),
            mhpmcounter(mhpmCounterIndex(io.waddr)),
            Mux(isMhpmEvent(io.waddr), mhpmevent(mhpmEventIndex(io.waddr)), MuxLookup(io.waddr, 0.U)(mapping.toSeq))
        )
    )
    val debug_rdata_pre = Mux(
        isPmpAddr(io.debug_addr),
        pmpAddrRead(io.debug_addr),
        Mux(
            isMhpmCounter(io.debug_addr),
            mhpmcounter(mhpmCounterIndex(io.debug_addr)),
            Mux(isMhpmEvent(io.debug_addr), mhpmevent(mhpmEventIndex(io.debug_addr)), MuxLookup(io.debug_addr, 0.U)(mapping.toSeq))
        )
    )

    val addr_valid = mapping.keys.map(_ === io.addr).reduce(_ || _) || isPmpAddr(io.addr) || isMhpmCounter(io.addr) || isMhpmEvent(io.addr)
    val waddr_valid =
        mapping.keys.map(_ === io.waddr).reduce(_ || _) || isPmpAddr(io.waddr) || isMhpmCounter(io.waddr) || isMhpmEvent(io.waddr)
    val debug_addr_valid =
        mapping.keys.map(_ === io.debug_addr).reduce(_ || _) || isPmpAddr(io.debug_addr) || isMhpmCounter(io.debug_addr) || isMhpmEvent(io.debug_addr)
    val csrRequiredPriv = io.addr(9, 8)
    val wcsrRequiredPriv = io.waddr(9, 8)
    val csrReadOnly = io.addr(11, 10) === 3.U
    val wcsrReadOnly = io.waddr(11, 10) === 3.U
    val debugCsrReadOnly = io.debug_addr(11, 10) === 3.U
    val csrPrivOk = CurrentPrivLevel >= csrRequiredPriv
    val wcsrPrivOk = CurrentPrivLevel >= wcsrRequiredPriv
    val csrReadonlyWrite = io.write && csrReadOnly
    val wcsrReadonlyWrite = io.wwrite && wcsrReadOnly

    val wdata_final = MuxLookup(io.wcmd, 0.U)(
        Seq(
            CSROps.RW.asUInt  -> io.wwdata,                // 直接写入
            CSROps.RS.asUInt  -> (wdata_read_pre | io.wwdata),  // 读
            CSROps.RC.asUInt  -> (wdata_read_pre & ~io.wwdata), // 清除
            CSROps.RWI.asUInt -> io.wwdata,                // 直接写入，rs2编码为zimm
            CSROps.RSI.asUInt -> (wdata_read_pre | io.wwdata),  // 读，rs2编码为zimm
            CSROps.RCI.asUInt -> (wdata_read_pre & ~io.wwdata)  // 清除，rs2编码为zimm
        )
    )

    val writeIllegal = !waddr_valid || !wcsrPrivOk || wcsrReadonlyWrite
	    val do_write = io.wvalid && !writeIllegal && io.wwrite &&
	        (io.wcmd === CSROps.RW.asUInt || io.wcmd === CSROps.RS.asUInt || io.wcmd === CSROps.RC.asUInt ||
	            io.wcmd === CSROps.RWI.asUInt || io.wcmd === CSROps.RSI.asUInt || io.wcmd === CSROps.RCI.asUInt)

    val writeAddr = Mux(io.debug_write, io.debug_addr, io.waddr)
    val writeData = Mux(io.debug_write, io.debug_wdata, wdata_final)
    val satpWriteData = legalizeSatp(writeData, satp)
    val visibleWriteData = Mux(writeAddr === CSR.SATP, satpWriteData, writeData)
    val writeEnable = io.debug_write || do_write
    val directWriteBypass =
        writeEnable && writeAddr === io.addr &&
            (writeAddr === CSR.MCOUNTEREN || writeAddr === CSR.SCOUNTEREN ||
                writeAddr === CSR.MENVCFG || writeAddr === CSR.MCOUNTINHIBIT ||
                writeAddr === CSR.MCYCLE || writeAddr === CSR.MINSTRET ||
                writeAddr === CSR.MSCRATCH || writeAddr === CSR.MEPC ||
                writeAddr === CSR.MCAUSE || writeAddr === CSR.MTVAL ||
                writeAddr === CSR.SSCRATCH || writeAddr === CSR.SEPC ||
                writeAddr === CSR.SCAUSE || writeAddr === CSR.STVAL ||
                writeAddr === CSR.SATP || writeAddr === CSR.MNSCRATCH ||
                writeAddr === CSR.MNSTATUS)

    io.rdata := Mux(directWriteBypass, visibleWriteData, rdata_pre)
    io.debug_rdata := debug_rdata_pre
    io.debug_valid := debug_addr_valid
    io.debug_writable := debug_addr_valid && !debugCsrReadOnly
    io.illegal := io.valid && (!addr_valid || !csrPrivOk || csrReadonlyWrite || !counterAccessOk(io.addr))

    when(writeEnable) {
        switch(writeAddr) {
            is(CSR.MSTATUS) {
                mstatus := writeData
            }
            is(CSR.SSTATUS) {
                val sMask = bitMask(SStatus.SIE) | bitMask(SStatus.SPIE) | bitMask(SStatus.SPP) |
                    bitMask(SStatus.SUM) | bitMask(SStatus.MXR)
                mstatus := (mstatus & ~sMask) | (writeData & sMask)
            }
            is(CSR.MEDELEG) {
                medeleg := writeData
            }
            is(CSR.MIDELEG) {
                mideleg := writeData & supervisorInterruptMask
            }
            is(CSR.MIE) {
                mie := writeData & writableMieMask
            }
            is(CSR.SIE) {
                mie := (mie & ~(mideleg & supervisorInterruptMask)) | (writeData & mideleg & supervisorInterruptMask)
            }
            is(CSR.MTVEC) {
                mtvec := legalizeTrapVector(writeData)
            }
            is(CSR.MCOUNTEREN) {
                mcounteren := writeData
            }
            is(CSR.SCOUNTEREN) {
                scounteren := writeData
            }
            is(CSR.MENVCFG) {
                menvcfg := writeData
            }
            is(CSR.MCOUNTINHIBIT) {
                mcountinhibit := writeData
            }
            is(CSR.MCYCLE) {
                mcycle := writeData
            }
            is(CSR.MINSTRET) {
                minstret := writeData
            }
            is(CSR.STVEC) {
                stvec := legalizeTrapVector(writeData)
            }
            is(CSR.MEPC) {
                mepc := writeData
            }
            is(CSR.SEPC) {
                sepc := writeData
            }
            is(CSR.MCAUSE) {
                mcause := writeData
            }
            is(CSR.SCAUSE) {
                scause := writeData
            }
            is(CSR.MTVAL) {
                mtval := writeData
            }
            is(CSR.STVAL) {
                stval := writeData
            }
            is(CSR.MSCRATCH) {
                mscratch := writeData
            }
            is(CSR.SSCRATCH) {
                sscratch := writeData
            }
            is(CSR.SIP) {
                when(mideleg(InterruptCauseCode.SupervisorSoft)) {
                    ssipSw := writeData(InterruptCauseCode.SupervisorSoft)
                }
            }
            is(CSR.PMPcfg0) {
                pmpcfg0 := writeData
            }
            is(CSR.MNSCRATCH) {
                mnscratch := writeData
            }
            is(CSR.MNSTATUS) {
                mnstatus := writeData
            }
            is(CSR.SATP) {
                satp := satpWriteData
            }
        }
        when(isActivePmpAddr(writeAddr)) {
            // TileLink carries 32-bit physical addresses. pmpaddr stores
            // address bits [PADDR-1:2], so higher bits are WARL-zero.
            pmpaddr(pmpAddrIndex(writeAddr)) := writeData & pmpAddrMask
        }
        when(isMhpmCounter(writeAddr)) {
            mhpmcounter(mhpmCounterIndex(writeAddr)) := writeData
        }
        when(isMhpmEvent(writeAddr)) {
            mhpmevent(mhpmEventIndex(writeAddr)) := writeData
        }
    }

    val pendingEnabled = mie & mip
    val machineVisiblePending = pendingEnabled & ~mideleg
    val supervisorVisiblePending = pendingEnabled & mideleg & supervisorInterruptMask
    val machineInterruptCause = Wire(UInt(XLEN.W))
    machineInterruptCause := 0.U
    when(machineVisiblePending(InterruptCauseCode.MachineExt)) {
        machineInterruptCause := interruptCause(InterruptCauseCode.MachineExt)
    }.elsewhen(machineVisiblePending(InterruptCauseCode.MachineSoft)) {
        machineInterruptCause := interruptCause(InterruptCauseCode.MachineSoft)
    }.elsewhen(machineVisiblePending(InterruptCauseCode.MachineTimer)) {
        machineInterruptCause := interruptCause(InterruptCauseCode.MachineTimer)
    }.elsewhen(machineVisiblePending(InterruptCauseCode.SupervisorExt)) {
        machineInterruptCause := interruptCause(InterruptCauseCode.SupervisorExt)
    }.elsewhen(machineVisiblePending(InterruptCauseCode.SupervisorSoft)) {
        machineInterruptCause := interruptCause(InterruptCauseCode.SupervisorSoft)
    }.elsewhen(machineVisiblePending(InterruptCauseCode.SupervisorTimer)) {
        machineInterruptCause := interruptCause(InterruptCauseCode.SupervisorTimer)
    }
    val machineInterruptGlobalEnable = (CurrentPrivLevel < PrivilegeLevel.Machine) || mstatus(MStatus.MIE)
    val machineInterruptPending = machineVisiblePending =/= 0.U
    val machineInterrupt = machineInterruptPending && machineInterruptGlobalEnable

    val supervisorInterruptCause = Wire(UInt(XLEN.W))
    supervisorInterruptCause := 0.U
    when(supervisorVisiblePending(InterruptCauseCode.SupervisorExt)) {
        supervisorInterruptCause := interruptCause(InterruptCauseCode.SupervisorExt)
    }.elsewhen(supervisorVisiblePending(InterruptCauseCode.SupervisorSoft)) {
        supervisorInterruptCause := interruptCause(InterruptCauseCode.SupervisorSoft)
    }.elsewhen(supervisorVisiblePending(InterruptCauseCode.SupervisorTimer)) {
        supervisorInterruptCause := interruptCause(InterruptCauseCode.SupervisorTimer)
    }
    val supervisorInterruptGlobalEnable =
        (CurrentPrivLevel < PrivilegeLevel.Supervisor) ||
            (CurrentPrivLevel === PrivilegeLevel.Supervisor && mstatus(SStatus.SIE))
    val supervisorInterruptPending = supervisorVisiblePending =/= 0.U
    val supervisorInterrupt = supervisorInterruptPending && supervisorInterruptGlobalEnable

    val selectedInterruptIsSupervisor = !machineInterrupt && supervisorInterrupt
    val selectedInterruptCause = Mux(selectedInterruptIsSupervisor, supervisorInterruptCause, machineInterruptCause)
    val selectedInterruptVector = Mux(selectedInterruptIsSupervisor, trapVector(stvec, selectedInterruptCause), trapVector(mtvec, selectedInterruptCause))

    val trapCauseBit = causeBit(io.trap_cause)
    val trapToSupervisor = supervisorEnabled && io.trap_valid && CurrentPrivLevel =/= PrivilegeLevel.Machine &&
        Mux(io.trap_cause(XLEN - 1), (mideleg & trapCauseBit) =/= 0.U, (medeleg & trapCauseBit) =/= 0.U)
    val requestedTrapVector = Mux(trapToSupervisor, trapVector(stvec, io.trap_cause), trapVector(mtvec, io.trap_cause))

    // 处理中断和异常
    when(io.trap_valid) {
        when(trapToSupervisor) {
            val curSie = mstatus(SStatus.SIE)
            val trapSstatus = SStatus.setSPP(SStatus.setSIE(SStatus.setSPIE(mstatus, curSie), false.B), CurrentPrivLevel)
            sepc    := io.trap_pc
            scause  := io.trap_cause
            stval   := io.trap_value
            mstatus := trapSstatus
            CurrentPrivLevel := PrivilegeLevel.Supervisor
        }.otherwise {
            val curMie = mstatus(MStatus.MIE)
            val trapMstatus = MStatus.setMPP(MStatus.setMIE(MStatus.setMPIE(mstatus, curMie), false.B), CurrentPrivLevel)
            mepc    := io.trap_pc
            mcause  := io.trap_cause
            mtval   := io.trap_value
            mstatus := trapMstatus
            CurrentPrivLevel := PrivilegeLevel.Machine
        }
    }.elsewhen(io.is_ret) {
        when(io.ret_type === TrapReturnType.SRET && supervisorEnabled) {
            mstatus := SStatus.setSPP(SStatus.setSPIE(SStatus.setSIE(mstatus, mstatus(SStatus.SPIE)), true.B), PrivilegeLevel.User)
            CurrentPrivLevel := Mux(mstatus(SStatus.SPP), PrivilegeLevel.Supervisor, PrivilegeLevel.User)
        }.otherwise {
            mstatus := MStatus.setMPIE(MStatus.setMPP(MStatus.setMIE(mstatus, mstatus(MStatus.MPIE)), 0.U), true.B)
            CurrentPrivLevel := MStatus.getMPP(mstatus)
        }
    }

    io.epc_out  := Mux(io.is_ret && io.ret_type === TrapReturnType.SRET && supervisorEnabled, sepc, mepc)
    io.tvec_out := Mux(io.trap_valid, requestedTrapVector, selectedInterruptVector)
    io.interrupt_cause := selectedInterruptCause
    io.ie_out   := mstatus(MStatus.MIE)
    io.interrupt := machineInterrupt || supervisorInterrupt
    val effectiveDataPriv = Mux(
        mstatus(MStatus.MPRV) && CurrentPrivLevel === PrivilegeLevel.Machine,
        MStatus.getMPP(mstatus),
        CurrentPrivLevel
    )
    io.mem_cfg_out.priv := CurrentPrivLevel
    io.mem_cfg_out.data_priv := effectiveDataPriv
    io.mem_cfg_out.mmu_en := features.mmu.B
    io.mem_cfg_out.satp := satp
    io.mem_cfg_out.pmpcfg0 := pmpcfg0
    io.mem_cfg_out.pmpaddr := pmpaddr
    io.mem_cfg_out.mxr := mstatus(MStatus.MXR)
    io.mem_cfg_out.sum := mstatus(MStatus.SUM)
    io.mem_cfg_out.mprv := mstatus(MStatus.MPRV)

    val snapshotSret = io.is_ret && io.ret_type === TrapReturnType.SRET && supervisorEnabled
    val snapshotMstatus = Mux(
        io.is_ret,
        Mux(
            snapshotSret,
            SStatus.setSPP(SStatus.setSPIE(SStatus.setSIE(mstatus, mstatus(SStatus.SPIE)), true.B), PrivilegeLevel.User),
            MStatus.setMPIE(MStatus.setMPP(MStatus.setMIE(mstatus, mstatus(MStatus.MPIE)), 0.U), true.B)
        ),
        mstatus
    )
    val snapshotPriv = Mux(
        io.is_ret,
        Mux(snapshotSret, Mux(mstatus(SStatus.SPP), PrivilegeLevel.Supervisor, PrivilegeLevel.User), MStatus.getMPP(mstatus)),
        CurrentPrivLevel
    )

    io.state_snapshot.privilegeMode := snapshotPriv
    io.state_snapshot.mstatus := snapshotMstatus
    io.state_snapshot.sstatus := sstatusView(snapshotMstatus)
    io.state_snapshot.mepc := mepc
    io.state_snapshot.sepc := sepc
    io.state_snapshot.mtval := mtval
    io.state_snapshot.stval := stval
    io.state_snapshot.mtvec := mtvec
    io.state_snapshot.stvec := stvec
    io.state_snapshot.mcause := mcause
    io.state_snapshot.scause := scause
    io.state_snapshot.satp := satp
    io.state_snapshot.mip := mip
    io.state_snapshot.mie := mie
    io.state_snapshot.mscratch := mscratch
    io.state_snapshot.sscratch := sscratch
    io.state_snapshot.mideleg := mideleg
    io.state_snapshot.medeleg := medeleg
}
