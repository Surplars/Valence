package soc.isa

import chisel3._

object PrivilegeLevel {
    val User       = 0.U(2.W)
    val Supervisor = 1.U(2.W)
    val Hypervisor = 2.U(2.W) // reserved for future use, not implemented in this design
    val Machine    = 3.U(2.W)
}

object CSR {
    // Supervisor Trap Setup
    val SSTATUS = 0x100.U(12.W)
    val SIE     = 0x104.U(12.W)
    val STVEC   = 0x105.U(12.W)
    // Supervisor Trap Handling
    val SSCRATCH = 0x140.U(12.W)
    val SEPC     = 0x141.U(12.W)
    val SCAUSE   = 0x142.U(12.W)
    val STVAL    = 0x143.U(12.W)
    val SIP      = 0x144.U(12.W)
    // Supervisor Protection and Translation
    val SATP = 0x180.U(12.W)
    // Machine Information Registers
    val MVENDORID = 0xf11.U(12.W)
    val MARCHID   = 0xf12.U(12.W)
    val MIMPID    = 0xf13.U(12.W)
    val MHARTID   = 0xf14.U(12.W)
    // Machine Trap Setup
    val MSTATUS    = 0x300.U(12.W)
    val MISA       = 0x301.U(12.W)
    val MEDELEG    = 0x302.U(12.W)
    val MIDELEG    = 0x303.U(12.W)
    val MIE        = 0x304.U(12.W)
    val MTVEC      = 0x305.U(12.W)
    val MCOUNTEREN = 0x306.U(12.W)
    val MENVCFG    = 0x30a.U(12.W)
    val MCOUNTINHIBIT = 0x320.U(12.W)
    val MHPMEVENT3 = 0x323.U(12.W)
    val MHPMEVENT31 = 0x33f.U(12.W)
    // Machine Trap Handling
    val MSCRATCH = 0x340.U(12.W)
    val MEPC     = 0x341.U(12.W)
    val MCAUSE   = 0x342.U(12.W)
    val MTVAL    = 0x343.U(12.W)
    val MIP      = 0x344.U(12.W)
    // Machine Memory Protection
    val PMPcfg0  = 0x3a0.U(12.W)
    val PMPcfg2  = 0x3a2.U(12.W)
    val PMPaddr0 = 0x3b0.U(12.W)
    val PMPaddr7 = 0x3b7.U(12.W)
    val PMPaddr15 = 0x3bf.U(12.W)
    // Supervisor Counter Setup
    val SCOUNTEREN = 0x106.U(12.W)
    // Machine Non-Maskable Interrupt Handling
    val MNSCRATCH = 0x740.U(12.W)
    val MNEPC     = 0x741.U(12.W)
    val MNCAUSE   = 0x742.U(12.W)
    val MNSTATUS  = 0x744.U(12.W)
    // Machine Counter/Timers
    val MCYCLE       = 0xb00.U(12.W)
    val MINSTRET     = 0xb02.U(12.W)
    val MHPMCOUNTER3 = 0xb03.U(12.W)
    val MHPMCOUNTER31 = 0xb1f.U(12.W)
    // User-level counter/timer views. Access below M-mode is controlled by
    // mcounteren/scounteren in CSRFile.
    val CYCLE   = 0xc00.U(12.W)
    val TIME    = 0xc01.U(12.W)
    val INSTRET = 0xc02.U(12.W)
}

object MCause {
    private def int(code: Int, XLEN: Int = 64): UInt = {
        (BigInt(1) << (XLEN - 1) | code).U(XLEN.W)
    }
    private def exc(code: Int, XLEN: Int = 64): UInt = {
        code.U(XLEN.W)
    }

    val InstrAddrMisaligned = exc(0)
    val InstrAccessFault    = exc(1)
    val IllegalInstr        = exc(2)
    val Breakpoint          = exc(3)
    val LoadAddrMisaligned  = exc(4)
    val LoadAccessFault     = exc(5)
    val StoreAddrMisaligned = exc(6)
    val StoreAccessFault    = exc(7)
    val EcallFromUMode      = exc(8)
    val EcallFromSMode      = exc(9)
    val EcallFromMMode      = exc(11)
    val InstrPageFault      = exc(12)
    val LoadPageFault       = exc(13)
    val StorePageFault      = exc(15)

    val SupervisorSoftInt  = int(1)
    val SupervisorTimerInt = int(5)
    val SupervisorExtInt   = int(9)
    val MachineSoftInt     = int(3)
    val MachineTimerInt    = int(7)
    val MachineExtInt      = int(11)
}

object InterruptCauseCode {
    val SupervisorSoft  = 1
    val MachineSoft     = 3
    val SupervisorTimer = 5
    val MachineTimer    = 7
    val SupervisorExt   = 9
    val MachineExt      = 11
}
