package soc.core.ooo

import chisel3._
import chisel3.util._

class HypervisorFault extends Bundle {
    val pc = UInt(64.W)
    val cause = UInt(64.W)
    val tval = UInt(64.W)
    val guestAddress = Bool()
    val guestPhysicalAddress = UInt(64.W) // Raw owner GPA; shift only at the CSR boundary.
    val implicitPte = Bool()
}

/** Additional RV64 H/VS architectural state. All writes are irrevocable ROB-head events.
  * The host M/S bank remains in MachineSystemUnit. ASIDLEN/VMIDLEN=0, VSXL=64, Svade.
  * Integration is experimental until owner-context, G-stage and H memory instructions qualify.
  */
class HypervisorState(compressed: Boolean, guestFiles: Int, floatingPoint: Boolean = false) extends Module {
    private val floatingPointEnabled = floatingPoint
    val io = IO(new Bundle {
        // Optional component contract only; actual H+FP cores remain rejected.
        // FS lives here, while the one physical FPR/fcsr bank stays in FP state.
        val floatingPoint = if (floatingPointEnabled) Some(new Bundle {
            val fs = Output(UInt(2.W))
            val sd = Output(Bool())
            val mutation = Input(Valid(new FloatingPointMutation))
        }) else None
        val privilege = Input(UInt(2.W))
        val mpp = Input(UInt(2.W))
        val mprv = Input(Bool())
        val hsGlobalEnable = Input(Bool())
        val readAddress = Input(UInt(12.W))
        val write = Flipped(Valid(new GuestInterruptCsrWrite))
        val readKnown = Output(Bool())
        val readData = Output(UInt(64.W))
        val shadow = Output(Bool())
        val virtualCsr = Output(Bool())
        val mieBits = Output(UInt(64.W))
        val mipBits = Output(UInt(64.W))
        val machineStatus = Output(UInt(64.W))
        val virtualized = Output(Bool())
        val dataVirtualized = Output(Bool())
        val vsatp = Output(UInt(64.W))
        val hgatp = Output(UInt(64.W))
        val vsSum = Output(Bool())
        val vsMxr = Output(Bool())
        val hu = Output(Bool())
        val spvp = Output(Bool())
        val tvm = Output(Bool())
        val tw = Output(Bool())
        val tsr = Output(Bool())
        val vtvm = Output(Bool())
        val vtw = Output(Bool())
        val vtsr = Output(Bool())
        val counterEnable = Output(UInt(3.W))
        val machineStce = Input(Bool())
        val stce = Output(Bool())
        val time = Input(UInt(64.W))
        val guestTime = Output(UInt(64.W))
        val guestExternal = Input(UInt(math.max(1, guestFiles).W))
        val hideleg = Output(UInt(64.W))
        val vsip = Output(UInt(64.W))
        val vsie = Output(UInt(64.W))
        val vsGlobalEnable = Output(Bool())
        val nominatedGuestInterrupt = Input(Bool())
        val nominatedGuestCause = Input(UInt(6.W))
        val hsPending = Output(Bool())
        val hsCause = Output(UInt(4.W))
        val vsPending = Output(Bool())
        val vsCause = Output(UInt(4.W)) // Raw 2/6/10 for the shared trap interface.
        val vgein = Output(UInt(6.W))
        val vsiselect = Output(UInt(12.W))
        val mret = Input(Bool())
        val sret = Input(Bool())
        val trap = Flipped(Valid(new HypervisorFault))
        val delegated = Input(Bool())
        val guestTrap = Output(Bool())
        val guestTrapPc = Output(UInt(64.W))
        val guestReturnPc = Output(UInt(64.W))
        val guestReturnPrivilege = Output(UInt(2.W))
    })
    val v = RegInit(false.B)
    val mpv = RegInit(false.B)
    val mgva = RegInit(false.B)
    val spv = RegInit(false.B)
    val spvp = RegInit(false.B)
    val hgva = RegInit(false.B)
    val hu = RegInit(false.B)
    val tvm = RegInit(false.B); val tw = RegInit(false.B); val tsr = RegInit(false.B)
    val vtvm = RegInit(false.B); val vtw = RegInit(false.B); val vtsr = RegInit(false.B)
    val hedeleg = RegInit(0.U(64.W))
    val hideleg = RegInit(0.U(64.W))
    val ie = RegInit(0.U(64.W))
    val hcounteren = RegInit(0.U(3.W))
    val htimedelta = RegInit(0.U(64.W))
    val hstce = RegInit(false.B)
    val vstimecmp = RegInit("hffffffffffffffff".U(64.W))
    val hgatp = RegInit(0.U(64.W))
    val htval = RegInit(0.U(64.W)); val htinst = RegInit(0.U(64.W))
    val mtval2 = RegInit(0.U(64.W)); val mtinst = RegInit(0.U(64.W))
    val vsie = RegInit(false.B); val vspie = RegInit(false.B); val vspp = RegInit(false.B)
    val vssum = RegInit(false.B); val vsmxr = RegInit(false.B)
    val vsfs = if (floatingPoint) RegInit(0.U(2.W)) else 0.U(2.W)
    io.floatingPoint.foreach { fp =>
        fp.fs := vsfs
        fp.sd := vsfs === 3.U
    }
    val vstvec = RegInit(0.U(64.W)); val vsscratch = RegInit(0.U(64.W))
    val vsepc = RegInit(0.U(64.W)); val vscause = RegInit(0.U(64.W)); val vstval = RegInit(0.U(64.W))
    val vsatp = RegInit(0.U(64.W)); val vsiselect = RegInit(0.U(12.W))
    val guest = Module(new HypervisorGuestInterrupts(guestFiles))
    private val interruptMask = (if (guestFiles == 0) 0x444 else 0x1444).U(64.W)
    private val shadows = Seq(0x100, 0x104, 0x105, 0x140, 0x141, 0x142, 0x143, 0x144, 0x14d,
        0x150, 0x151, 0x15c, 0x180)
    def shadow(address: UInt): Bool = v && shadows.map(a => address === a.U).reduce(_ || _)
    def mapped(address: UInt): UInt = Mux(shadow(address), address + 0x100.U, address)
    def epc(data: UInt): UInt = if (compressed) Cat(data(63, 1), 0.U(1.W)) else Cat(data(63, 2), 0.U(2.W))
    val address = mapped(io.readAddress)
    val writeAddress = mapped(io.write.bits.address)
    val hstatus = (BigInt(2) << 32).U(64.W) | (hgva.asUInt << 6) | (spv.asUInt << 7) |
        (spvp.asUInt << 8) | (hu.asUInt << 9) | (guest.io.vgein << 12) |
        (vtvm.asUInt << 20) | (vtw.asUInt << 21) | (vtsr.asUInt << 22)
    val vsstatus = (BigInt(2) << 32).U(64.W) | (vsie.asUInt << 1) | (vspie.asUInt << 5) |
        (vspp.asUInt << 8) | FloatingPointStatus.bits(vsfs) |
        (vssum.asUInt << 18) | (vsmxr.asUInt << 19)
    val reads = Seq(0x600.U -> hstatus, 0x602.U -> hedeleg, 0x603.U -> hideleg,
        0x604.U -> ie, 0x605.U -> htimedelta, 0x606.U -> hcounteren.pad(64),
        0x608.U -> 0.U(64.W), 0x646.U -> 0.U(64.W), 0x647.U -> 0.U(64.W),
        0x60a.U -> ((io.machineStce && hstce).asUInt << 63), 0x643.U -> htval, 0x64a.U -> htinst, 0x680.U -> hgatp,
        0x34a.U -> mtinst, 0x34b.U -> mtval2, 0x200.U -> vsstatus,
        0x204.U -> ((ie & hideleg) >> 1), 0x205.U -> vstvec, 0x240.U -> vsscratch,
        0x241.U -> vsepc, 0x242.U -> vscause, 0x243.U -> vstval, 0x244.U -> guest.io.vsip, 0x24d.U -> vstimecmp,
        0x250.U -> vsiselect.pad(64), 0x251.U -> 0.U(64.W), 0x25c.U -> 0.U(64.W), 0x280.U -> vsatp)
    guest.io.readAddress := address
    io.readKnown := guest.io.readKnown || reads.map { case (a, _) => address === a }.reduce(_ || _)
    io.readData := Mux(guest.io.readKnown, guest.io.readData,
        Mux1H(reads.map { case (a, data) => (address === a) -> data }))
    io.shadow := shadow(io.readAddress)
    io.virtualCsr := v && ((io.readAddress(9, 8) === 2.U && io.readKnown) ||
        (io.readAddress === 0x180.U && vtvm))
    io.virtualized := v
    io.dataVirtualized := Mux(io.privilege === 3.U && io.mprv, mpv && io.mpp =/= 3.U, v)
    io.machineStatus := (mpv.asUInt << 39) | (mgva.asUInt << 38) |
        (tvm.asUInt << 20) | (tw.asUInt << 21) | (tsr.asUInt << 22)
    io.mieBits := ie; io.mipBits := guest.io.hip
    io.vsatp := vsatp; io.hgatp := hgatp; io.vsSum := vssum; io.vsMxr := vsmxr
    io.hu := hu; io.spvp := spvp; io.tvm := tvm; io.tw := tw; io.tsr := tsr
    io.vtvm := vtvm; io.vtw := vtw; io.vtsr := vtsr; io.counterEnable := hcounteren
    io.stce := io.machineStce && hstce
    io.guestTime := io.time + htimedelta
    // Unsigned modulo-64 guest time; compare updates become pending one cycle later.
    val timerPending = RegNext(io.guestTime >= vstimecmp, false.B)
    io.vgein := guest.io.vgein; io.vsiselect := vsiselect
    guest.io.guestExternal := io.guestExternal
    guest.io.platformVirtualExternal := false.B
    guest.io.virtualTimer := io.stce && timerPending
    guest.io.commit := true.B
    guest.io.setVgein.valid := io.write.valid && writeAddress === 0x600.U
    guest.io.setVgein.bits := io.write.bits.data(17, 12)
    guest.io.write.valid := io.write.valid && (writeAddress =/= 0x244.U || hideleg(2))
    guest.io.write.bits.address := Mux(writeAddress === 0x344.U || writeAddress === 0x244.U, 0x644.U, writeAddress)
    guest.io.write.bits.data := Mux(writeAddress === 0x244.U, io.write.bits.data << 1, io.write.bits.data)
    guest.io.hie := ie; guest.io.hideleg := hideleg; guest.io.privilege := io.privilege
    guest.io.virtualized := v; guest.io.hsGlobalEnable := io.hsGlobalEnable; guest.io.vsGlobalEnable := vsie
    io.hideleg := hideleg; io.vsip := guest.io.vsip; io.vsie := (ie & hideleg) >> 1
    io.vsGlobalEnable := vsie
    io.hsPending := guest.io.hsPending; io.hsCause := guest.io.hsCause
    io.vsPending := guest.io.vsPending; io.vsCause := guest.io.vsCause + 1.U
    val cause = io.trap.bits.cause
    val interrupt = cause(63)
    val inRange = cause(62, 6) === 0.U
    io.guestTrap := v && ((interrupt && io.nominatedGuestInterrupt) || (io.delegated && inRange &&
        Mux(interrupt, hideleg(cause(5, 0)), hedeleg(cause(5, 0)))))
    val guestCause = Mux(interrupt && io.nominatedGuestInterrupt,
        (BigInt(1) << 63).U(64.W) | io.nominatedGuestCause,
        Mux(interrupt, cause - 1.U, cause))
    io.guestTrapPc := Cat(vstvec(63, 2), 0.U(2.W)) +
        Mux(interrupt && vstvec(1, 0) === 1.U, guestCause(5, 0) << 2, 0.U)
    io.guestReturnPc := vsepc; io.guestReturnPrivilege := Mux(vspp, 1.U, 0.U)
    when(io.write.valid) {
        val data = io.write.bits.data
        switch(writeAddress) {
            is(0x300.U) { mpv := data(39); mgva := data(38); tvm := data(20); tw := data(21); tsr := data(22) }
            is(0x600.U) { hgva := data(6); spv := data(7); spvp := data(8); hu := data(9)
                vtvm := data(20); vtw := data(21); vtsr := data(22) }
            // ecall U/VU may delegate. HS/VS/M ecalls and guest-page/virtual-instruction faults may not.
            is(0x602.U) { hedeleg := data & "hcb1ff".U }
            is(0x603.U) { hideleg := data & 0x444.U }
            is(0x304.U, 0x604.U) { ie := data & interruptMask }
            is(0x204.U) { ie := (ie & ~hideleg) | ((data << 1) & hideleg) }
            is(0x605.U) { htimedelta := data }
            is(0x606.U) { hcounteren := data(2, 0) }
            is(0x60a.U) { hstce := io.machineStce && data(63) }
            is(0x643.U) { htval := data }
            is(0x64a.U) { htinst := Mux(data === 0x3000.U, data, 0.U) }
            is(0x34a.U) { mtinst := Mux(data === 0x3000.U, data, 0.U) }
            is(0x34b.U) { mtval2 := data }
            is(0x200.U) { vsie := data(1); vspie := data(5); vspp := data(8)
                vssum := data(18); vsmxr := data(19)
            }
            is(0x205.U) { vstvec := Cat(data(63, 2), 0.U(1.W), data(1, 0) === 1.U) }
            is(0x240.U) { vsscratch := data }
            is(0x241.U) { vsepc := epc(data) }
            is(0x242.U) { vscause := data }
            is(0x243.U) { vstval := data }
            is(0x24d.U) { vstimecmp := data }
            is(0x250.U) { vsiselect := data(11, 0) }
        }
        when(writeAddress === 0x280.U && (data(63, 60) === 0.U || data(63, 60) === 8.U)) {
            vsatp := Mux(data(63, 60) === 8.U, Cat(8.U(4.W), 0.U(16.W), data(43, 0)), 0.U)
        }
        when(writeAddress === 0x680.U) {
            hgatp := Mux(data(63, 60) === 8.U, Cat(8.U(4.W), 0.U(16.W), data(43, 2), 0.U(2.W)), 0.U)
        }
    }
    io.floatingPoint.foreach { fp =>
        when(io.write.valid && FloatingPointStatus.writesGuest(io.write.bits.address, v)) {
            vsfs := io.write.bits.data(14, 13)
        }
        // The producer captured ownership on issue, or uses the accepting CSR
        // cycle. Never select an owner from live V at FP retirement. Serialized
        // status writes and FP mutations must not coincide; Dirty wins if they do.
        when(fp.mutation.valid && fp.mutation.bits.guest) { vsfs := 3.U }
    }
    // Choose zero for H STCE whenever M STCE disables the field, including the disabling write.
    when(!io.machineStce || (io.write.valid && writeAddress === 0x30a.U && !io.write.bits.data(63))) {
        hstce := false.B
    }
    when(io.mret) { v := mpv && io.mpp =/= 3.U; mpv := false.B }
    when(io.sret) {
        when(v) { vsie := vspie; vspie := true.B; vspp := false.B }
            .otherwise { v := spv; spv := false.B }
    }
    when(io.trap.valid) {
        when(io.guestTrap) {
            vsepc := epc(io.trap.bits.pc); vscause := guestCause; vstval := io.trap.bits.tval
            vspp := io.privilege === 1.U; vspie := vsie; vsie := false.B
        }.otherwise {
            v := false.B
            val guestFault = !interrupt && (cause === 20.U || cause === 21.U || cause === 23.U)
            val secondary = Mux(guestFault, io.trap.bits.guestPhysicalAddress >> 2, 0.U)
            val transformed = Mux(guestFault && io.trap.bits.implicitPte, 0x3000.U, 0.U)
            when(io.delegated) {
                spv := v; when(v) { spvp := io.privilege === 1.U }
                hgva := io.trap.bits.guestAddress; htval := secondary; htinst := transformed
            }.otherwise {
                mpv := v; mgva := io.trap.bits.guestAddress; mtval2 := secondary; mtinst := transformed
            }
        }
    }
}
