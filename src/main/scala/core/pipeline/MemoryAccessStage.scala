package soc.core.pipeline

import chisel3._
import chisel3.util._

import soc.config.Config
import soc.config.SoCFeatures
import soc.isa.MCause
import soc.isa.PrivilegeLevel

class PmpAccessChecker(XLEN: Int = 64) extends Module {
    val io = IO(new Bundle {
        val valid = Input(Bool())
        val addr = Input(UInt(XLEN.W))
        val size = Input(UInt(3.W))
        val isStore = Input(Bool())
        val priv = Input(UInt(2.W))
        val pmpcfg0 = Input(UInt(XLEN.W))
        val pmpaddr = Input(Vec(8, UInt(XLEN.W)))

        val fault = Output(Bool())
    })

    val accessBytes = 1.U(XLEN.W) << io.size
    val accessEnd = io.addr + accessBytes - 1.U

    private def pmpCfg(index: Int): UInt = io.pmpcfg0(8 * index + 7, 8 * index)
    private def pmpAddrBytes(index: Int): UInt = (io.pmpaddr(index) << 2)(XLEN - 1, 0)

    val matches = Wire(Vec(8, Bool()))
    val permissionsOk = Wire(Vec(8, Bool()))
    val locked = Wire(Vec(8, Bool()))

    for (i <- 0 until 8) {
        val cfg = pmpCfg(i)
        val mode = cfg(4, 3)
        val lower = if (i == 0) 0.U(XLEN.W) else pmpAddrBytes(i - 1)
        val upper = pmpAddrBytes(i)
        val torMatch = io.addr >= lower && accessEnd < upper
        val na4Match = io.addr >= upper && accessEnd < upper + 4.U
        val napotMask = (((io.pmpaddr(i) ^ (io.pmpaddr(i) + 1.U)) << 2) | 3.U)(XLEN - 1, 0)
        val napotBase = upper & ~napotMask
        val napotMatch = (io.addr & ~napotMask) === napotBase && (accessEnd & ~napotMask) === napotBase

        matches(i) := MuxLookup(mode, false.B)(Seq(1.U -> torMatch, 2.U -> na4Match, 3.U -> napotMatch))
        permissionsOk(i) := Mux(io.isStore, cfg(1), cfg(0))
        locked(i) := cfg(7)
    }

    val matchedEntry = PriorityEncoder(matches)
    val anyMatch = matches.asUInt.orR
    val matchedPermissionOk = permissionsOk(matchedEntry)
    val matchedLocked = locked(matchedEntry)
    io.fault := io.valid && Mux(
        io.priv === PrivilegeLevel.Machine,
        anyMatch && matchedLocked && !matchedPermissionOk,
        !anyMatch || !matchedPermissionOk
    )
}

class MemoryAccessStage(XLEN: Int = 64, features: SoCFeatures = Config.features) extends Module {
    val io = IO(new Bundle {
        val in    = Input(new MemoryAccessInfo(XLEN))
        val cfg   = Input(new MemorySystemConfig(XLEN))
        val out   = Output(new MemoryAccessInfo(XLEN))
        val fault = Output(new MemoryFaultInfo(XLEN))
    })

    private def inRegion(region: soc.config.AddressRegion): Bool = region.contains(io.in.vaddr, XLEN)

    val inRom    = inRegion(Config.RomRegion)
    val inSram   = Config.sramRegionFor(features).contains(io.in.vaddr, XLEN)
    val inDevice = Config.deviceRegions.map(inRegion).reduce(_ || _)

    val satpModeSv39 = io.cfg.satp(63, 60) === 8.U
    val translateEnabled = io.in.valid && io.cfg.mmu_en && satpModeSv39 &&
        io.cfg.data_priv =/= PrivilegeLevel.Machine && !io.in.attrs.device
    val isLoad = io.in.op === MemOpType.Load || io.in.op === MemOpType.LR
    val isStore = io.in.op === MemOpType.Store || io.in.op === MemOpType.SC || io.in.op === MemOpType.AMO

    val pmp = Module(new PmpAccessChecker(XLEN))
    // PMP is defined over physical addresses. A virtual access is checked by
    // LSU after page-table translation, not against its pre-translation VA.
    pmp.io.valid := io.in.valid && (isLoad || isStore) && !translateEnabled
    pmp.io.addr := io.in.vaddr
    pmp.io.size := io.in.size
    pmp.io.isStore := isStore
    pmp.io.priv := io.cfg.data_priv
    pmp.io.pmpcfg0 := io.cfg.pmpcfg0
    pmp.io.pmpaddr := io.cfg.pmpaddr

    io.out := io.in
    io.out.paddr := io.in.vaddr
    io.out.attrs.cacheable  := inSram
    io.out.attrs.device     := inDevice
    io.out.attrs.bufferable := inSram
    io.out.attrs.allocate   := inSram
    io.out.attrs.translate  := translateEnabled
    io.out.attrs.executable := inRom

    io.fault.valid := pmp.io.fault
    io.fault.cause := Mux(isStore, MCause.StoreAccessFault, MCause.LoadAccessFault)
    io.fault.value := io.in.vaddr
}
