package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.interrupt.ImsicCsrRequest
import soc.ip.bus.RegisterResponse

class SystemRequest(p: OooParams) extends Bundle {
    val token       = new RobToken(p)
    val pc          = UInt(64.W)
    val instruction = UInt(32.W)
    val operand     = UInt(64.W)
}
class SystemResult(p: OooParams) extends Bundle {
    val completion = new BackendCompletion(p)
    val redirect   = Bool()
    val invalidateFetch = Bool()
}
class MachineCsrPort extends Bundle {
    val request  = Decoupled(new ImsicCsrRequest)
    val response = Flipped(Decoupled(new RegisterResponse))
}
class VmCsrState extends Bundle {
    val satp = UInt(64.W)
    val sum  = Bool()
    val mxr  = Bool()
    val dataPrivilege = UInt(2.W)
}

/** One irrevocable, ROB-head-authorized system transaction. Capacity one.
  * Capture the complete command before CSR/FP decoding; minimum completion
  * latency is two cycles, with no speculative CSR state or rollback copy.
  */
class MachineSystemUnit(p: OooParams) extends Module {
    private def alignedEpc(value: UInt): UInt =
        if (p.compressedInstructions) Cat(value(63, 1), 0.U(1.W)) else Cat(value(63, 2), 0.U(2.W))
    val io = IO(new Bundle {
        val start                       = Flipped(Decoupled(new SystemRequest(p)))
        val complete                    = Decoupled(new SystemResult(p))
        val imsic                       = new MachineCsrPort
        val trap                        = Input(Valid(new HeadException(p)))
        val trapReady                   = Output(Bool())
        val fpRetire = if (p.fpEnabled) Some(Input(Valid(new RobToken(p)))) else None
        val fpMemory = if (p.fpEnabled) Some(new DataPort) else None
        val fpMemoryBusy = if (p.fpEnabled) Some(Output(Bool())) else None
        val trapTarget                  = Output(UInt(64.W))
        val externalInterrupt           = Input(Bool())
        val supervisorExternalInterrupt = Input(Bool())
        val timerInterrupt              = Input(Bool())
        val timeValue                   = Input(UInt(64.W))
        val interruptCause              = Output(UInt(4.W))
        val interruptPending            = Output(Bool())
        val fetchPrivilege              = Output(UInt(2.W))
        val dataPrivilege               = Output(UInt(2.W))
        val pmpState                    = Output(new PmpState)
        val vmState                     = if (p.virtualMemoryLevels > 0) Some(Output(new VmCsrState)) else None
        val vmFlush                     = if (p.virtualMemoryLevels > 0) Some(Output(Bool())) else None
        val vmFlushReady                = if (p.virtualMemoryLevels > 0) Some(Input(Bool())) else None
        val fenceIFlush                 = Output(Bool())
        val fenceIFlushReady            = Input(Bool())
    })
    val idle :: execute :: send :: waitResponse :: waitVmFlush :: waitFenceI :: waitFp :: finish :: Nil = Enum(8)
    val floatingPoint = if (p.fpEnabled) Some(Module(new FloatingPointSystem(p))) else None
    val fpFs = floatingPoint.map(_.io.fs).getOrElse(0.U(2.W))
    val fpFcsr = floatingPoint.map(_.io.fcsr).getOrElse(0.U(8.W))
    val fpStatus = (fpFs << 13) | ((fpFs === 3.U).asUInt << 63)
    val state                                         = RegInit(idle)
    val request                                       = Reg(new SystemRequest(p))
    val result                                        = RegInit(0.U.asTypeOf(new SystemResult(p)))
    val external                                      = RegInit(0.U.asTypeOf(new ImsicCsrRequest))
    val privilege                                     = RegInit(3.U(2.W))
    val mie                                           = RegInit(false.B)
    val mtie                                          = RegInit(false.B)
    val meie                                          = RegInit(false.B)
    val seie                                          = RegInit(false.B)
    val ssie                                          = RegInit(false.B)
    val stie                                          = RegInit(false.B)
    val ssip                                          = RegInit(false.B)
    val stipSoftware                                  = RegInit(false.B)
    val stimecmp                                      = RegInit("hffffffffffffffff".U(64.W))
    val stce                                          = RegInit(false.B)
    val mcounterenTm                                  = RegInit(false.B)
    val scounterenTm                                  = RegInit(false.B)
    val mpie                                          = RegInit(false.B)
    val mpp                                           = RegInit(0.U(2.W))
    val mprv                                          = RegInit(false.B)
    val sum                                           = RegInit(false.B)
    val mxr                                           = RegInit(false.B)
    val satp                                          = RegInit(0.U(64.W))
    val pmpCfg                                        = RegInit(VecInit(Seq.fill(16)(0.U(8.W))))
    val pmpAddr                                       = RegInit(VecInit(Seq.fill(16)(0.U(54.W))))
    val sie                                           = RegInit(false.B)
    val spie                                          = RegInit(false.B)
    val spp                                           = RegInit(false.B)
    val medeleg                                       = RegInit(0.U(64.W))
    val seideleg                                      = RegInit(false.B)
    val ssideleg                                      = RegInit(false.B)
    val stideleg                                      = RegInit(false.B)
    val stvec                                         = RegInit(0.U(64.W))
    val sepc                                          = RegInit(0.U(64.W))
    val scause                                        = RegInit(0.U(64.W))
    val stval                                         = RegInit(0.U(64.W))
    val sscratch                                      = RegInit(0.U(64.W))
    val mtvec                                         = RegInit(0.U(64.W))
    val mepc                                          = RegInit(0.U(64.W))
    val mcause                                        = RegInit(0.U(64.W))
    val mtval                                         = RegInit(0.U(64.W))
    val mscratch                                      = RegInit(0.U(64.W))
    val miselect                                      = RegInit(0.U(12.W))
    val siselect                                      = RegInit(0.U(12.W))
    val mstatus                                       = "h0000000a00000000".U(64.W) | fpStatus | (mprv.asUInt << 17) |
        (sum.asUInt << 18) | (mxr.asUInt << 19) |
        (mpp << 11) | (spp.asUInt << 8) |
        (mpie.asUInt << 7) | (spie.asUInt << 5) | (mie.asUInt << 3) | (sie.asUInt << 1)
    val misa = p.misaValue.U(64.W)
    val sstatus              = "h0000000200000000".U(64.W) | fpStatus | (sum.asUInt << 18) | (mxr.asUInt << 19) |
        (spp.asUInt << 8) | (spie.asUInt << 5) | (sie.asUInt << 1)
    io.vmState.foreach { state =>
        state.satp := satp
        state.sum := sum
        state.mxr := mxr
        state.dataPrivilege := io.dataPrivilege
    }
    io.vmFlush.foreach(_ := state === waitVmFlush)
    io.fenceIFlush := state === waitFenceI
    io.fetchPrivilege := privilege
    io.dataPrivilege  := Mux(privilege === 3.U && mprv, mpp, privilege)
    for (i <- 0 until 16) {
        io.pmpState.cfg(i)  := pmpCfg(i)
        io.pmpState.addr(i) := pmpAddr(i)
    }
    PmpState.decodeRegions(io.pmpState)
    val machineGlobalEnable  = privilege =/= 3.U || mie
    val machineExternalReady = io.externalInterrupt && meie && machineGlobalEnable
    val machineTimerReady    = io.timerInterrupt && mtie && machineGlobalEnable
    // Register the wide timer comparison before it enters interrupt arbitration.
    val stipHardware = RegNext(io.timeValue >= stimecmp, false.B)
    val stip         = Mux(stce, stipHardware, stipSoftware)
    val supervisorExternalReady = io.supervisorExternalInterrupt && seie && Mux(
        seideleg,
        privilege === 0.U || (privilege === 1.U && sie),
        machineGlobalEnable
    )
    val supervisorSoftwareReady = ssip && ssie && Mux(
        ssideleg,
        privilege === 0.U || (privilege === 1.U && sie),
        machineGlobalEnable
    )
    val supervisorTimerReady = stip && stie && Mux(
        stideleg,
        privilege === 0.U || (privilege === 1.U && sie),
        machineGlobalEnable
    )
    io.interruptPending := machineExternalReady || machineTimerReady ||
        supervisorExternalReady || supervisorSoftwareReady || supervisorTimerReady
    io.interruptCause := Mux(machineExternalReady, 11.U,
        Mux(machineTimerReady, 7.U,
            Mux(supervisorExternalReady, 9.U, Mux(supervisorSoftwareReady, 1.U, 5.U))))
    val delegated = privilege =/= 3.U && Mux(
        io.trap.bits.cause(63),
        (io.trap.bits.cause(62, 0) === 9.U && seideleg) ||
            (io.trap.bits.cause(62, 0) === 1.U && ssideleg) ||
            (io.trap.bits.cause(62, 0) === 5.U && stideleg),
        io.trap.bits.cause(62, 6) === 0.U && medeleg(io.trap.bits.cause(5, 0))
    )
    val trapVector = Mux(delegated, stvec, mtvec)
    io.trapTarget := (trapVector & "hfffffffffffffffc".U) + Mux(
        io.trap.bits.cause(63) && trapVector(1, 0) === 1.U,
        io.trap.bits.cause(3, 0) << 2,
        0.U
    )
    io.start.ready          := state === idle && !floatingPoint.map(_.io.busy).getOrElse(false.B)
    when(io.start.fire) {
        assert(!io.trap.valid, "trap cannot also authorize a new system command")
        request := io.start.bits
        state := execute
    }
    // A faulted FP command stays busy until its precise trap. Trap admission must
    // not depend on new-command credit, or that exception would deadlock.
    io.trapReady := state === idle
    io.complete.valid       := state === finish
    io.complete.bits        := result
    io.imsic.request.valid  := state === send
    io.imsic.request.bits   := external
    io.imsic.response.ready := state === waitResponse
    when(io.complete.fire) { state := idle }
    when(io.imsic.request.fire) { state := waitResponse }
    when(io.imsic.response.fire) {
        result.completion.data      := io.imsic.response.bits.data
        result.completion.exception := io.imsic.response.bits.error
        state                       := finish
    }
    if (p.virtualMemoryLevels > 0) {
        when(state === waitVmFlush && io.vmFlushReady.get) { state := finish }
    }
    when(state === waitFenceI && io.fenceIFlushReady) { state := finish }
    val inst            = request.instruction
    val address         = inst(31, 20)
    val csr             = inst(6, 0) === "h73".U && inst(14, 12) =/= 0.U
    val operation       = inst(13, 12)
    val source          = Mux(inst(14), Cat(0.U(59.W), inst(19, 15)), request.operand)
    val write           = operation === 1.U || inst(19, 15) =/= 0.U
    val read            = operation =/= 1.U || inst(11, 7) =/= 0.U
    val imsic           = address === "h351".U || address === "h35c".U || address === "h151".U || address === "h15c".U
    val supervisorImsic = address === "h151".U || address === "h15c".U
    val readValue       = MuxLookup(address, 0.U(64.W))(
        Seq(
            "h300".U -> mstatus,
            "h301".U -> misa,
            "h302".U -> medeleg,
            "h303".U -> ((seideleg.asUInt << 9) | (stideleg.asUInt << 5) | (ssideleg.asUInt << 1)),
            "h100".U -> sstatus,
            "h104".U -> (Mux(seideleg, seie.asUInt << 9, 0.U) | Mux(stideleg, stie.asUInt << 5, 0.U) |
                Mux(ssideleg, ssie.asUInt << 1, 0.U)),
            "h105".U -> stvec,
            "h140".U -> sscratch,
            "h141".U -> sepc,
            "h142".U -> scause,
            "h143".U -> stval,
            "h144".U -> (Mux(seideleg, io.supervisorExternalInterrupt.asUInt << 9, 0.U) |
                Mux(stideleg, stip.asUInt << 5, 0.U) |
                Mux(ssideleg, ssip.asUInt << 1, 0.U)),
            "h14d".U -> stimecmp,
            "h106".U -> (scounterenTm.asUInt << 1),
            "h150".U -> siselect,
            "h305".U -> mtvec,
            "h304".U -> ((meie.asUInt << 11) | (seie.asUInt << 9) | (mtie.asUInt << 7) |
                (stie.asUInt << 5) | (ssie.asUInt << 1)),
            "h344".U -> ((io.externalInterrupt.asUInt << 11) | (io.supervisorExternalInterrupt.asUInt << 9) |
                (io.timerInterrupt.asUInt << 7) | (stip.asUInt << 5) | (ssip.asUInt << 1)),
            "h306".U -> (mcounterenTm.asUInt << 1),
            "h30a".U -> (stce.asUInt << 63),
            "hc01".U -> io.timeValue,
            "h340".U -> mscratch,
            "h341".U -> mepc,
            "h342".U -> mcause,
            "h343".U -> mtval,
            "h350".U -> miselect
        ) ++
        (if (p.fpEnabled) Seq(
            1.U -> fpFcsr(4, 0).pad(64), 2.U -> fpFcsr(7, 5).pad(64), 3.U -> fpFcsr.pad(64)
        ) else Seq.empty) ++
        (if (p.virtualMemoryLevels > 0) Seq("h180".U -> satp) else Seq.empty) ++
        (if (p.pmpEntries > 0) Seq(
            "h3a0".U -> Cat((0 until 8).reverse.map(pmpCfg(_))),
            "h3a2".U -> Cat((8 until 16).reverse.map(pmpCfg(_)))
        ) ++ (0 until p.pmpEntries).map(i => (0x3b0 + i).U -> Cat(0.U(10.W), pmpAddr(i))) else Seq.empty)
    )
    val exists = (Seq(0x100, 0x104, 0x105, 0x106, 0x140, 0x141, 0x142, 0x143, 0x144, 0x14d, 0x150, 0x151, 0x15c,
        0x300, 0x301, 0x302, 0x303, 0x304, 0x305, 0x306, 0x30a, 0x340, 0x341, 0x342, 0x343, 0x344, 0x350,
        0x351, 0x35c, 0xc01, 0xf11, 0xf12, 0xf13, 0xf14) ++
        (if (p.fpEnabled) Seq(1, 2, 3) else Seq.empty) ++
        (if (p.virtualMemoryLevels > 0) Seq(0x180) else Seq.empty) ++
        (if (p.pmpEntries > 0) Seq(0x3a0, 0x3a2) ++ (0 until p.pmpEntries).map(0x3b0 + _) else Seq.empty))
        .map(a => address === a.U)
        .reduce(_ || _)
    val timeAccessAllowed = privilege === 3.U || (mcounterenTm && (privilege === 1.U || scounterenTm))
    val stimecmpAccessAllowed = privilege === 3.U || (stce && mcounterenTm)
    val fpCsr = address === 1.U || address === 2.U || address === 3.U
    val legalCsr = (!fpCsr || fpFs =/= 0.U) && exists && privilege >= address(9, 8) && !(write && address(11, 10) === 3.U) &&
        (address =/= "hc01".U || timeAccessAllowed) && (address =/= "h14d".U || stimecmpAccessAllowed)
    val newValue = MuxLookup(operation, source)(Seq(2.U -> (readValue | source), 3.U -> (readValue & ~source)))
    val sfenceVma = inst(31, 25) === "b0001001".U && inst(14, 7) === 0.U && inst(6, 0) === "h73".U
    val pmpPermissionsChange = if (p.pmpEntries > 0) {
        val changed = (0 until p.pmpEntries).flatMap { i =>
            val cfgAddress = if (i < 8) "h3a0".U else "h3a2".U
            val raw = newValue(8 * (i % 8) + 7, 8 * (i % 8))
            val nextCfg = Cat(raw(7), 0.U(2.W), raw(4, 2), raw(1) && raw(0), raw(0))
            val nextTor = if (i + 1 < p.pmpEntries) pmpCfg(i + 1)(4, 3) === 1.U else false.B
            val nextTorLocked = if (i + 1 < p.pmpEntries) nextTor && pmpCfg(i + 1)(7) else false.B
            Seq(address === cfgAddress && !pmpCfg(i)(7) && nextCfg =/= pmpCfg(i),
                address === (0x3b0 + i).U && !pmpCfg(i)(7) && !nextTorLocked &&
                    (pmpCfg(i)(4, 3) =/= 0.U || nextTor) && pmpAddr(i) =/= newValue(53, 0))
        }
        VecInit(changed).asUInt.orR
    } else false.B
    floatingPoint.foreach { fp =>
        io.fpMemory.get <> fp.io.memory
        io.fpMemoryBusy.get := fp.io.memoryBusy
        fp.io.pmpState := io.pmpState
        fp.io.dataPrivilege := io.dataPrivilege
        fp.io.virtualized := (if (p.virtualMemoryLevels > 0)
            io.dataPrivilege =/= 3.U && satp(63, 60) =/= 0.U else false.B)
        fp.io.start.valid := state === execute && FloatingPointDecode.supported(inst, p.fpConfig)
        fp.io.start.bits := request
        fp.io.retire := io.fpRetire.get
        fp.io.trap := io.trap.valid
        fp.io.complete.ready := state === waitFp
        fp.io.csr.valid := state === execute && csr && legalCsr && fpCsr
        fp.io.csr.bits.address := address
        fp.io.csr.bits.operation := operation - 1.U
        fp.io.csr.bits.write := write
        fp.io.csr.bits.value := source
        fp.io.setFs.valid := state === execute && csr && legalCsr && write &&
            (address === "h300".U || address === "h100".U)
        fp.io.setFs.bits := newValue(14, 13)
        when(fp.io.start.valid) { assert(fp.io.start.ready, "FP head command credit") }
        when(fp.io.csr.valid) { assert(fp.io.csr.ready, "FP CSR serialization") }
        when(fp.io.setFs.valid) { assert(fp.io.setFs.ready, "FP context serialization") }
        when(fp.io.complete.fire) {
            result.completion := fp.io.complete.bits
            state := finish
        }
    }
    when(state === execute) {
        state                    := finish
        result                   := 0.U.asTypeOf(new SystemResult(p))
        result.completion.token  := request.token
        result.completion.nextPc := request.pc + 4.U
        result.completion.cause  := 2.U
        result.completion.tval   := inst
        when(p.fpEnabled.B && FloatingPointDecode.supported(inst, p.fpConfig)) {
            state := waitFp
        }.elsewhen(inst(6, 0) === "h0f".U && (inst(14, 12) === 0.U || inst(14, 12) === 1.U)) {
            // The backend authorizes this full barrier only after older memory has drained.
            result.completion.data := 0.U
            result.redirect := inst(14, 12) === 1.U
            result.invalidateFetch := inst(14, 12) === 1.U
            when(inst(14, 12) === 1.U) { state := waitFenceI }
        }.elsewhen(inst === "h10500073".U) {
            // WFI is allowed to resume immediately; this implementation treats it as a hint.
            result.completion.data := 0.U
        }.elsewhen(sfenceVma && (p.virtualMemoryLevels > 0).B && privilege >= 1.U) {
            // The ROB-head barrier has drained older data and fetches before this transaction starts.
            result.redirect := true.B
            result.invalidateFetch := true.B
            state := waitVmFlush
        }.elsewhen(csr) {
            result.completion.exception := !legalCsr
            result.completion.data      := Mux(read, readValue, 0.U)
            when(legalCsr) {
                // A permission update refetches all younger instructions under the new policy.
                when(write && pmpPermissionsChange) {
                    result.redirect := true.B
                    result.invalidateFetch := true.B
                    if (p.virtualMemoryLevels > 0) { state := waitVmFlush }
                }
                when(imsic) {
                    external.file      := Mux(supervisorImsic, 1.U, 0.U)
                    external.selector  := Mux(supervisorImsic, siselect, miselect)
                    external.topei     := address === "h35c".U || address === "h15c".U
                    external.operation := Mux(write, operation, 0.U)
                    external.data      := source
                    state              := send
                }.elsewhen(write) {
                    switch(address) {
                        is("h300".U) {
                            mie  := newValue(3)
                            mpie := newValue(7)
                            mpp  := Mux(newValue(12, 11) === 2.U, 3.U, newValue(12, 11))
                            sie  := newValue(1)
                            spie := newValue(5)
                            spp  := newValue(8)
                            mprv := newValue(17)
                            if (p.virtualMemoryLevels > 0) {
                                sum := newValue(18)
                                mxr := newValue(19)
                            }
                        }
                        is("h302".U) { medeleg := newValue & "hb3ff".U }
                        is("h303".U) {
                            seideleg := newValue(9)
                            stideleg := newValue(5)
                            ssideleg := newValue(1)
                        }
                        is("h100".U) {
                            sie := newValue(1); spie := newValue(5); spp := newValue(8)
                            if (p.virtualMemoryLevels > 0) {
                                sum := newValue(18); mxr := newValue(19)
                            }
                        }
                        is("h104".U) {
                            when(seideleg) { seie := newValue(9) }
                            when(stideleg) { stie := newValue(5) }
                            when(ssideleg) { ssie := newValue(1) }
                        }
                        is("h144".U) { when(ssideleg) { ssip := newValue(1) } }
                        is("h14d".U) { stimecmp := newValue }
                        is("h106".U) { scounterenTm := newValue(1) }
                        is("h105".U) { stvec := Cat(newValue(63, 2), Mux(newValue(1, 0) === 1.U, 1.U(2.W), 0.U(2.W))) }
                        is("h140".U) { sscratch := newValue }
                        is("h141".U) { sepc := alignedEpc(newValue) }
                        is("h142".U) { scause := newValue }
                        is("h143".U) { stval := newValue }
                        is("h150".U) { siselect := newValue(11, 0) }
                        is("h180".U) {
                            if (p.virtualMemoryLevels > 0) {
                                val mode = newValue(63, 60)
                                when(mode === 0.U || (mode >= 8.U && mode <= (p.virtualMemoryLevels + 5).U)) {
                                    satp := Mux(mode === 0.U, 0.U, newValue)
                                    result.redirect := true.B
                                    result.invalidateFetch := true.B
                                }
                            }
                        }
                        is("h305".U) { mtvec := Cat(newValue(63, 2), Mux(newValue(1, 0) === 1.U, 1.U(2.W), 0.U(2.W))) }
                        is("h304".U) {
                            meie := newValue(11)
                            seie := newValue(9)
                            mtie := newValue(7)
                            stie := newValue(5)
                            ssie := newValue(1)
                        }
                        is("h344".U) {
                            ssip := newValue(1)
                            when(!stce) { stipSoftware := newValue(5) }
                        }
                        is("h306".U) { mcounterenTm := newValue(1) }
                        is("h30a".U) { stce := newValue(63) }
                        is("h340".U) { mscratch := newValue }
                        is("h341".U) { mepc := alignedEpc(newValue) }
                        is("h342".U) { mcause := newValue }
                        is("h343".U) { mtval := newValue }
                        is("h350".U) { miselect := newValue(11, 0) }
                    }
                    if (p.pmpEntries > 0) {
                        when(address === "h3a0".U) {
                            for (i <- 0 until math.min(8, p.pmpEntries)) {
                                val raw = newValue(8 * i + 7, 8 * i)
                                when(!pmpCfg(i)(7)) {
                                    pmpCfg(i) := Cat(raw(7), 0.U(2.W), raw(4, 2), raw(1) && raw(0), raw(0))
                                }
                            }
                        }
                        when(address === "h3a2".U) {
                            for (i <- 8 until p.pmpEntries) {
                                val raw = newValue(8 * (i - 8) + 7, 8 * (i - 8))
                                when(!pmpCfg(i)(7)) {
                                    pmpCfg(i) := Cat(raw(7), 0.U(2.W), raw(4, 2), raw(1) && raw(0), raw(0))
                                }
                            }
                        }
                        for (i <- 0 until p.pmpEntries) {
                            when(address === (0x3b0 + i).U) {
                                val nextTorLocked = if (i + 1 < p.pmpEntries)
                                    pmpCfg(i + 1)(7) && pmpCfg(i + 1)(4, 3) === 1.U else false.B
                                when(!pmpCfg(i)(7) && !nextTorLocked) { pmpAddr(i) := newValue(53, 0) }
                            }
                        }
                    }
                }
            }
        }.elsewhen(inst === "h30200073".U && privilege === 3.U) {
            result.redirect          := true.B
            result.invalidateFetch   := (p.pmpEntries > 0).B
            result.completion.nextPc := mepc
            privilege                := mpp
            mie                      := mpie
            mpie                     := true.B
            mpp                      := 0.U
            when(mpp =/= 3.U) { mprv := false.B }
        }.elsewhen(inst === "h10200073".U && privilege >= 1.U) {
            result.redirect          := true.B
            result.invalidateFetch   := (p.pmpEntries > 0).B
            result.completion.nextPc := sepc
            privilege                := Mux(spp, 1.U, 0.U)
            sie                      := spie
            spie                     := true.B
            spp                      := false.B
        }.otherwise {
            result.completion.exception := true.B
            when(inst === "h00000073".U) {
                result.completion.cause := Mux(privilege === 3.U, 11.U, Mux(privilege === 1.U, 9.U, 8.U))
                result.completion.tval  := 0.U
            }.elsewhen(inst === "h00100073".U) {
                result.completion.cause := 3.U
                result.completion.tval  := request.pc
            }
        }
    }
    when(io.trap.valid) {
        assert(state === idle, "trap overlapped an irrevocable system transaction")
        when(delegated) {
            sepc      := alignedEpc(io.trap.bits.pc)
            scause    := io.trap.bits.cause
            stval     := io.trap.bits.tval
            spie      := sie
            sie       := false.B
            spp       := privilege === 1.U
            privilege := 1.U
        }.otherwise {
            mepc      := alignedEpc(io.trap.bits.pc)
            mcause    := io.trap.bits.cause
            mtval     := io.trap.bits.tval
            mpie      := mie
            mie       := false.B
            mpp       := privilege
            privilege := 3.U
        }
    }
}
