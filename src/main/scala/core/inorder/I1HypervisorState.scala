package soc.core.inorder

import chisel3._
import chisel3.util._

/** Guest address context travels with one accepted translation owner. */
class I1GuestContext extends Bundle {
    val virtualized = Bool()
    val dataVirtualized = Bool()
    val guestPrivilege = UInt(2.W)
    val vsatp = UInt(64.W)
    val hgatp = UInt(64.W)
    val sum = Bool()
    val mxr = Bool()
}

class I1HypervisorControls extends Bundle {
    val virtualized = Bool(); val hu = Bool(); val tvm = Bool()
    val csrVirtual = Bool(); val sretVirtual = Bool(); val sfenceVirtual = Bool(); val wfiVirtual = Bool()
}

class I1GuestFault extends Bundle {
    val pageFault = Bool()
    val physical = UInt(39.W) // supported Sv39x4 GPA[40:2], or zero for an out-of-range GPA
    val implicitPte = Bool()
}

class I1GuestAccess extends Bundle {
    val vector = Bool() // CPU service checks the translated PA against normal RAM.
    val force = Bool() // HLV/HLVX/HSV use SPVP and two-stage translation even in M/HS/U.
    val execute = Bool() // HLVX substitutes execute permission for read permission.
    val fetch = Bool() // Internal G-stage request: instruction fetch needs X, HLVX needs R and X in PMP.
}

class I1HypervisorDecodeControl extends Bundle {
    val memory = Bool(); val execute = Bool(); val fence = Bool()
}

/** Additional H/VS state. The existing machine-state module retains the
  * host M/S banks, counters, PMP and shared FCSR. All changes occur at WB.
  * RV64 only, VSXL=64, ASIDLEN=VMIDLEN=GEILEN=0, little endian, Svade.
  */
class I1HypervisorState(p: FiveStageConfig) extends Module {
    require(p.xlen == 64 && p.withSupervisor && p.withSv39)
    val io = IO(new Bundle {
        val privilege = Input(UInt(2.W)); val mpp = Input(UInt(2.W)); val mprv = Input(Bool())
        val readAddress = Input(UInt(12.W))
        val write = Flipped(Valid(new Bundle { val address = UInt(12.W); val data = UInt(64.W) }))
        val readKnown = Output(Bool()); val readData = Output(UInt(64.W))
        val readDataForWrite = Output(UInt(64.W)); val readVirtual = Output(Bool())
        val shadowWrite = Output(Bool())
        val mie = Input(UInt(12.W)); val hideleg = Output(UInt(12.W))
        val virtualPending = Output(UInt(12.W)); val guestInterruptEnable = Output(Bool())
        val guestIeWrite = Valid(UInt(12.W))
        val time = Input(UInt(64.W)); val guestTime = Output(UInt(64.W))
        val fpDirty = Input(Bool()); val vectorDirty = Input(Bool())
        val guestFpEnabled = Output(Bool()); val guestVectorEnabled = Output(Bool())
        val mret = Input(Bool()); val sret = Input(Bool())
        val trap = Flipped(Valid(new Bundle {
            val pc = UInt(64.W); val cause = UInt(64.W); val tval = UInt(64.W)
            val guestAddress = Bool(); val guestPhysical = UInt(64.W); val implicitPte = Bool()
        }))
        val delegated = Input(Bool()); val guestTrap = Output(Bool())
        val guestTrapPc = Output(UInt(64.W)); val guestReturnPc = Output(UInt(64.W))
        val guestReturnPrivilege = Output(UInt(2.W))
        val virtualized = Output(Bool()); val machineStatus = Output(UInt(64.W))
        val hu = Output(Bool()); val spvp = Output(Bool())
        val vtvm = Output(Bool()); val vtw = Output(Bool()); val vtsr = Output(Bool())
        val counterEnable = Output(UInt(3.W))
        val context = Output(new I1GuestContext)
    })
    val virtualized = RegInit(false.B)
    val mpv = RegInit(false.B); val machineGva = RegInit(false.B)
    val spv = RegInit(false.B); val spvp = RegInit(false.B); val supervisorGva = RegInit(false.B)
    val hu = RegInit(false.B); val vtvm = RegInit(false.B)
    val vtw = RegInit(false.B); val vtsr = RegInit(false.B)
    val hedeleg = RegInit(0.U(32.W)); val hideleg = RegInit(0.U(12.W))
    val hvip = RegInit(0.U(12.W)); val hcounteren = RegInit(0.U(3.W))
    val htimedelta = RegInit(0.U(64.W)); val hgatp = RegInit(0.U(64.W))
    val htval = RegInit(0.U(64.W)); val htinst = RegInit(0.U(64.W))
    val mtval2 = RegInit(0.U(64.W)); val mtinst = RegInit(0.U(64.W))
    val vsieGlobal = RegInit(false.B); val vspie = RegInit(false.B); val vspp = RegInit(false.B)
    val vssum = RegInit(false.B); val vsmxr = RegInit(false.B)
    val vsfs = if (p.withF) RegInit(0.U(2.W)) else 0.U(2.W)
    val vsvs = if (p.spinor) RegInit(0.U(2.W)) else 0.U(2.W)
    val vstvec = RegInit(0.U(64.W)); val vsscratch = RegInit(0.U(64.W))
    val vsepc = RegInit(0.U(64.W)); val vscause = RegInit(0.U(64.W))
    val vstval = RegInit(0.U(64.W)); val vsatp = RegInit(0.U(64.W))
    val supervisorAddresses = Seq(0x100, 0x104, 0x105, 0x140, 0x141, 0x142, 0x143, 0x144, 0x180)
    def shadows(address: UInt): Bool = virtualized &&
        supervisorAddresses.map(n => address === n.U).reduce(_ || _)
    def mapped(address: UInt): UInt = Mux(shadows(address), address + 0x100.U, address)
    val address = mapped(io.readAddress)
    val writeAddress = mapped(io.write.bits.address)
    io.shadowWrite := shadows(io.write.bits.address)
    val vsstatus = (BigInt(2) << 32).U(64.W) | (vsieGlobal.asUInt << 1) |
        (vspie.asUInt << 5) | (vspp.asUInt << 8) | (vssum.asUInt << 18) | (vsmxr.asUInt << 19) |
        (vsfs << 13) | (vsvs << 9) | ((vsfs === 3.U || vsvs === 3.U).asUInt << 63)
    val hstatus = (BigInt(2) << 32).U(64.W) | (supervisorGva.asUInt << 6) |
        (spv.asUInt << 7) | (spvp.asUInt << 8) | (hu.asUInt << 9) |
        (vtvm.asUInt << 20) | (vtw.asUInt << 21) | (vtsr.asUInt << 22)
    val pairs = Seq(
        0x600.U -> hstatus, 0x602.U -> hedeleg.pad(64), 0x603.U -> hideleg.pad(64),
        0x604.U -> (io.mie & 0x444.U).pad(64), 0x605.U -> htimedelta,
        0x606.U -> hcounteren.pad(64), 0x607.U -> 0.U(64.W), 0x60a.U -> 0.U(64.W),
        0x643.U -> htval, 0x644.U -> hvip.pad(64), 0x645.U -> hvip.pad(64),
        0x64a.U -> htinst, 0x680.U -> hgatp, 0xe12.U -> 0.U(64.W),
        0x34a.U -> mtinst, 0x34b.U -> mtval2,
        0x200.U -> vsstatus, 0x204.U -> ((io.mie & hideleg) >> 1).pad(64),
        0x205.U -> vstvec, 0x240.U -> vsscratch, 0x241.U -> vsepc,
        0x242.U -> vscause, 0x243.U -> vstval, 0x244.U -> ((hvip & hideleg) >> 1).pad(64),
        0x280.U -> vsatp)
    io.readKnown := pairs.map { case (a, _) => address === a }.reduce(_ || _)
    io.readData := Mux1H(pairs.map { case (a, v) => (address === a) -> v })
    io.readDataForWrite := io.readData
    io.readVirtual := virtualized && io.readKnown &&
        (io.readAddress(9, 8) === 2.U || io.readAddress(9, 8) === 1.U && io.privilege === 0.U)
    io.virtualized := virtualized
    io.machineStatus := (mpv.asUInt << 39) | (machineGva.asUInt << 38)
    io.hu := hu; io.spvp := spvp; io.vtvm := vtvm; io.vtw := vtw; io.vtsr := vtsr
    io.counterEnable := hcounteren
    io.hideleg := hideleg; io.virtualPending := hvip
    io.guestInterruptEnable := vsieGlobal
    io.guestIeWrite.valid := io.write.valid && writeAddress === 0x204.U
    io.guestIeWrite.bits := (io.write.bits.data << 1)(11, 0) & hideleg
    io.guestTime := io.time + htimedelta
    io.guestFpEnabled := !virtualized || vsfs =/= 0.U
    io.guestVectorEnabled := !virtualized || vsvs =/= 0.U
    io.context.virtualized := virtualized
    io.context.dataVirtualized := Mux(io.privilege === 3.U && io.mprv, mpv && io.mpp =/= 3.U, virtualized)
    io.context.guestPrivilege := Mux(spvp, 1.U, 0.U)
    io.context.vsatp := vsatp; io.context.hgatp := hgatp
    io.context.sum := vssum; io.context.mxr := vsmxr
    val trapId = io.trap.bits.cause(4, 0)
    val interrupt = io.trap.bits.cause(63)
    io.guestTrap := virtualized && io.delegated && Mux(interrupt, hideleg.pad(32)(trapId), hedeleg(trapId))
    // Only IRQ 2/6/10 can pass hideleg. Their remapped 1/5/9 IDs need
    // no borrow into the upper cause bits, removing a late XLEN subtractor.
    val guestCause = Mux(interrupt,
        Cat(io.trap.bits.cause(63, 4), io.trap.bits.cause(3, 0) - 1.U(4.W)), io.trap.bits.cause)
    val architecturalVector = Cat(vstvec(63, 2), 0.U(2.W)) +
        Mux(interrupt && vstvec(1, 0) === 1.U, guestCause(4, 0) << 2, 0.U)
    if (p.fpgaTimingCuts) {
        val low = vstvec(5, 2) +& guestCause(3, 0)
        val high = vstvec(63, 6)
        val highPlusOne = I1TimingMath.incrementPowerOfTwo(high, 0, 8)
        val indexed = Cat(Mux(low(4), highPlusOne, high), low(3, 0), 0.U(2.W))
        io.guestTrapPc := Mux(interrupt && vstvec(1, 0) === 1.U, indexed, Cat(vstvec(63, 2), 0.U(2.W)))
        when(!reset.asBool && io.trap.valid && io.guestTrap) {
            assert(io.guestTrapPc === architecturalVector, "prepared VS vector changed BASE/cause")
        }
    } else io.guestTrapPc := architecturalVector
    when(!reset.asBool && io.trap.valid && io.guestTrap && interrupt) {
        assert(guestCause === io.trap.bits.cause - 1.U, "VS interrupt cause remapping changed")
    }
    io.guestReturnPc := vsepc; io.guestReturnPrivilege := Mux(vspp, 1.U, 0.U)
    def epc(data: UInt): UInt = Cat(data(63, if (p.withC) 1 else 2), 0.U((if (p.withC) 1 else 2).W))
    if (p.withF) when(virtualized && io.fpDirty) { vsfs := 3.U }
    if (p.spinor) when(virtualized && io.vectorDirty) { vsvs := 3.U }
    when(io.write.valid) {
        val data = io.write.bits.data
        switch(writeAddress) {
            is(0x300.U) { mpv := data(39); machineGva := data(38) }
            is(0x600.U) {
                supervisorGva := data(6); spv := data(7); spvp := data(8); hu := data(9)
                vtvm := data(20); vtw := data(21); vtsr := data(22)
            }
            is(0x602.U) { hedeleg := data(31, 0) & 0xcb1ff.U }
            is(0x603.U) { hideleg := data(11, 0) & 0x444.U }
            is(0x605.U) { htimedelta := data }
            is(0x606.U) { hcounteren := data(2, 0) }
            is(0x643.U) { htval := data }
            is(0x344.U, 0x644.U) { hvip := (hvip & ~4.U(12.W)) | (data(11, 0) & 4.U) }
            is(0x645.U) { hvip := data(11, 0) & 0x444.U }
            is(0x64a.U) { htinst := Mux(data === 0x3000.U, data, 0.U) }
            is(0x34a.U) { mtinst := Mux(data === 0x3000.U, data, 0.U) }
            is(0x34b.U) { mtval2 := data }
            is(0x200.U) {
                vsieGlobal := data(1); vspie := data(5); vspp := data(8)
                vssum := data(18); vsmxr := data(19)
                if (p.withF) vsfs := data(14, 13)
                if (p.spinor) vsvs := data(10, 9)
            }
            is(0x205.U) { vstvec := Cat(data(63, 2), 0.U(1.W), data(1, 0) === 1.U) }
            is(0x240.U) { vsscratch := data }
            is(0x241.U) { vsepc := epc(data) }
            is(0x242.U) { vscause := data }
            is(0x243.U) { vstval := data }
            is(0x244.U) { when(hideleg(2)) { hvip := (hvip & ~4.U(12.W)) | (data(1).asUInt << 2) } }
        }
        when(writeAddress === 0x280.U && (data(63, 60) === 0.U || data(63, 60) === 8.U)) {
            vsatp := Mux(data(63, 60) === 8.U, Cat(8.U(4.W), 0.U(31.W), data(28, 0)), 0.U)
        }
        when(writeAddress === 0x680.U) {
            hgatp := Mux(data(63, 60) === 8.U, Cat(8.U(4.W),
                0.U((72 - p.physicalBits).W), data(p.physicalBits - 13, 2), 0.U(2.W)), 0.U)
        }
    }
    when(io.mret) { virtualized := mpv && io.mpp =/= 3.U; mpv := false.B }
    when(io.sret) {
        when(virtualized) { vsieGlobal := vspie; vspie := true.B; vspp := false.B }
            .otherwise { virtualized := spv; spv := false.B }
    }
    when(io.trap.valid) {
        when(io.guestTrap) {
            vsepc := epc(io.trap.bits.pc); vscause := guestCause; vstval := io.trap.bits.tval
            vspp := io.privilege === 1.U; vspie := vsieGlobal; vsieGlobal := false.B
        }.otherwise {
            virtualized := false.B
            val guestFault = !interrupt && (trapId === 20.U || trapId === 21.U || trapId === 23.U)
            val value = Mux(guestFault, io.trap.bits.guestPhysical, 0.U)
            val inst = Mux(guestFault && io.trap.bits.implicitPte, 0x3000.U, 0.U)
            when(io.delegated) {
                spv := virtualized
                when(virtualized) { spvp := io.privilege === 1.U }
                supervisorGva := io.trap.bits.guestAddress; htval := value; htinst := inst
            }.otherwise {
                mpv := virtualized; machineGva := io.trap.bits.guestAddress
                mtval2 := value; mtinst := inst
            }
        }
    }
}
