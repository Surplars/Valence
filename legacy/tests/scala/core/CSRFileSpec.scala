package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.config.SoCProfiles
import soc.core.csr.{CSRFile, HpmEventId}
import soc.core.pipeline.{CSROps, TrapReturnType}
import soc.isa.{CSR, MCause, PrivilegeLevel}

class CSRFileSpec extends AnyFunSuite with ChiselSim {
    private val xlen = 64
    private val mieMask = (1L << 3) | (1L << 7) | (1L << 11)
    private val sInterruptMask = (1L << 1) | (1L << 5) | (1L << 9)
    private val mstatusMprv = BigInt(1) << 17
    private val mstatusSum = BigInt(1) << 18
    private val mstatusMxr = BigInt(1) << 19
    private val mstatusMppS = BigInt(1) << 11

    private def init(dut: CSRFile): Unit = {
        dut.io.valid.poke(false.B)
        dut.io.cmd.poke(CSROps.RW.asUInt)
        dut.io.addr.poke(0.U)
        dut.io.write.poke(false.B)
        dut.io.wdata.poke(0.U)
        dut.io.wvalid.poke(false.B)
        dut.io.wcmd.poke(CSROps.RW.asUInt)
        dut.io.waddr.poke(0.U)
        dut.io.wwrite.poke(false.B)
        dut.io.wwdata.poke(0.U)
        dut.io.debug_addr.poke(0.U)
        dut.io.debug_write.poke(false.B)
        dut.io.debug_wdata.poke(0.U)
        dut.io.perf.retire.poke(false.B)
        dut.io.perf.globalStall.poke(false.B)
        dut.io.perf.ifetchStall.poke(false.B)
        dut.io.perf.lsuStall.poke(false.B)
        dut.io.perf.lsuLoadStall.poke(false.B)
        dut.io.perf.lsuStoreStall.poke(false.B)
        dut.io.perf.lsuFenceStall.poke(false.B)
        dut.io.perf.lsuAtomicStall.poke(false.B)
        dut.io.perf.lsuMmioStall.poke(false.B)
        dut.io.perf.branch.poke(false.B)
        dut.io.perf.branchTaken.poke(false.B)
        dut.io.perf.branchRedirect.poke(false.B)
        dut.io.perf.branchPredTaken.poke(false.B)
        dut.io.perf.branchPredCorrect.poke(false.B)
        dut.io.trap_valid.poke(false.B)
        dut.io.trap_pc.poke(0.U)
        dut.io.trap_cause.poke(0.U)
        dut.io.trap_value.poke(0.U)
        dut.io.is_ret.poke(false.B)
        dut.io.ret_type.poke(TrapReturnType.None)
        dut.io.msip.poke(false.B)
        dut.io.mtip.poke(false.B)
        dut.io.meip.poke(false.B)
        dut.io.ssip.poke(false.B)
        dut.io.stip.poke(false.B)
        dut.io.seip.poke(false.B)
    }

    private def writeCsr(dut: CSRFile, addr: UInt, value: BigInt): Unit = {
        dut.io.wvalid.poke(true.B)
        dut.io.wwrite.poke(true.B)
        dut.io.wcmd.poke(CSROps.RW.asUInt)
        dut.io.waddr.poke(addr)
        dut.io.wwdata.poke(value.U)
        dut.clock.step()
        dut.io.wvalid.poke(false.B)
        dut.io.wwrite.poke(false.B)
        dut.io.waddr.poke(0.U)
        dut.io.wwdata.poke(0.U)
    }

    private def readCsr(dut: CSRFile, addr: UInt): BigInt = {
        dut.io.valid.poke(true.B)
        dut.io.write.poke(false.B)
        dut.io.addr.poke(addr)
        val value = dut.io.rdata.peek().litValue
        dut.io.valid.poke(false.B)
        value
    }

    private def takeTrap(dut: CSRFile, pc: BigInt, cause: BigInt, value: BigInt = 0): Unit = {
        dut.io.trap_pc.poke(pc.U)
        dut.io.trap_cause.poke(cause.U)
        dut.io.trap_value.poke(value.U)
        dut.io.trap_valid.poke(true.B)
        dut.clock.step()
        dut.io.trap_valid.poke(false.B)
    }

    private def takeRet(dut: CSRFile, retType: TrapReturnType.Type = TrapReturnType.MRET): Unit = {
        dut.io.ret_type.poke(retType)
        dut.io.is_ret.poke(true.B)
        dut.clock.step()
        dut.io.is_ret.poke(false.B)
        dut.io.ret_type.poke(TrapReturnType.None)
    }

    private def enterSupervisor(dut: CSRFile): Unit = {
        writeCsr(dut, CSR.MSTATUS, 1 << 11) // MPP=S
        takeRet(dut)
        dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Supervisor)
    }

    test("CSRFile WARL-aligns trap vectors and preserves valid vectored mode") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            writeCsr(dut, CSR.MTVEC, BigInt("80000046", 16))
            dut.io.addr.poke(CSR.MTVEC)
            dut.io.rdata.expect(BigInt("80000044", 16))

            writeCsr(dut, CSR.STVEC, BigInt("80000047", 16))
            dut.io.addr.poke(CSR.STVEC)
            dut.io.rdata.expect(BigInt("80000044", 16))

            writeCsr(dut, CSR.MTVEC, BigInt("80000101", 16))
            dut.io.addr.poke(CSR.MTVEC)
            dut.io.rdata.expect(BigInt("80000101", 16))
        }
    }

    test("CSRFile WARL-filters satp to Bare and Sv39 modes") {
        simulate(new CSRFile(xlen, hartID = 0, features = SoCProfiles.LinuxCapablePLIC)) { dut =>
            init(dut)

            val sv39 = BigInt(8) << 60
            val sv48 = BigInt(9) << 60
            val sv57 = BigInt(10) << 60
            val root = BigInt("403cb", 16)

            writeCsr(dut, CSR.SATP, sv48 | root)
            dut.io.addr.poke(CSR.SATP)
            dut.io.rdata.expect(0.U)

            writeCsr(dut, CSR.SATP, sv39 | root)
            dut.io.addr.poke(CSR.SATP)
            dut.io.rdata.expect((sv39 | root).U)

            writeCsr(dut, CSR.SATP, sv57 | root)
            dut.io.addr.poke(CSR.SATP)
            dut.io.rdata.expect((sv39 | root).U)

            writeCsr(dut, CSR.SATP, 0)
            dut.io.addr.poke(CSR.SATP)
            dut.io.rdata.expect(0.U)
        }
    }

    test("CSRFile arbitrates machine interrupts by privileged priority") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            writeCsr(dut, CSR.MTVEC, BigInt("80000100", 16) | 1)
            writeCsr(dut, CSR.MIE, mieMask)
            writeCsr(dut, CSR.MSTATUS, 1 << 3)

            dut.io.msip.poke(true.B)
            dut.io.mtip.poke(true.B)
            dut.io.meip.poke(true.B)
            dut.io.interrupt.expect(true.B)
            dut.io.interrupt_cause.expect(MCause.MachineExtInt)
            dut.io.tvec_out.expect(BigInt("80000100", 16) + 4 * 11)

            dut.io.meip.poke(false.B)
            dut.io.interrupt_cause.expect(MCause.MachineSoftInt)
            dut.io.tvec_out.expect(BigInt("80000100", 16) + 4 * 3)

            dut.io.msip.poke(false.B)
            dut.io.interrupt_cause.expect(MCause.MachineTimerInt)
            dut.io.tvec_out.expect(BigInt("80000100", 16) + 4 * 7)
        }
    }

    test("CSRFile exposes delegated supervisor interrupt CSR views without taking M trap") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            writeCsr(dut, CSR.MIDELEG, sInterruptMask)
            writeCsr(dut, CSR.SIE, sInterruptMask)
            writeCsr(dut, CSR.MSTATUS, 1 << 3)

            dut.io.seip.poke(true.B)
            dut.io.interrupt.expect(false.B)

            dut.io.addr.poke(CSR.SIP)
            dut.io.rdata.expect(1 << 9)

            dut.io.seip.poke(false.B)
            dut.io.ssip.poke(true.B)
            dut.io.addr.poke(CSR.SIP)
            dut.io.rdata.expect(1 << 1)
        }
    }

    test("CSRFile delegates traps to supervisor mode and SRET returns through sepc") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            writeCsr(dut, CSR.MEDELEG, 1 << 2) // illegal instruction
            writeCsr(dut, CSR.STVEC, BigInt("80000200", 16))
            writeCsr(dut, CSR.SEPC, BigInt("80000080", 16))
            enterSupervisor(dut)

            takeTrap(dut, BigInt("80000040", 16), MCause.IllegalInstr.litValue, BigInt("dead", 16))
            dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Supervisor)
            dut.io.addr.poke(CSR.SEPC)
            dut.io.rdata.expect(BigInt("80000040", 16))
            dut.io.addr.poke(CSR.SCAUSE)
            dut.io.rdata.expect(MCause.IllegalInstr)
            dut.io.addr.poke(CSR.STVAL)
            dut.io.rdata.expect(BigInt("dead", 16))

            writeCsr(dut, CSR.SEPC, BigInt("80000088", 16))
            dut.io.ret_type.poke(TrapReturnType.SRET)
            dut.io.is_ret.poke(true.B)
            dut.io.epc_out.expect(BigInt("80000088", 16))
            dut.clock.step()
            dut.io.is_ret.poke(false.B)
            dut.io.ret_type.poke(TrapReturnType.None)
            dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Supervisor)
        }
    }

    test("CSRFile exposes return-updated MRET state in the same-cycle snapshot") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            val before = (BigInt(1) << 1) | (BigInt(1) << 5) | (BigInt(1) << 7) |
                (BigInt(1) << 11) | (BigInt(1) << 18)
            val after = (BigInt(1) << 1) | (BigInt(1) << 3) | (BigInt(1) << 5) |
                (BigInt(1) << 7) | (BigInt(1) << 18)
            val sstatusAfter = (BigInt(1) << 1) | (BigInt(1) << 5) | (BigInt(1) << 18)
            writeCsr(dut, CSR.MSTATUS, before)

            dut.io.ret_type.poke(TrapReturnType.MRET)
            dut.io.is_ret.poke(true.B)

            dut.io.state_snapshot.privilegeMode.expect(PrivilegeLevel.Supervisor)
            dut.io.state_snapshot.mstatus.expect(after.U)
            dut.io.state_snapshot.sstatus.expect(sstatusAfter.U)
        }
    }

    test("CSRFile derives same-cycle SRET sstatus snapshot from return-updated mstatus") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            enterSupervisor(dut)

            val before = (BigInt(1) << 5) | (BigInt(1) << 8) | (BigInt(1) << 18)
            val after = (BigInt(1) << 1) | (BigInt(1) << 5) | (BigInt(1) << 7) |
                (BigInt(1) << 18)
            val sstatusAfter = (BigInt(1) << 1) | (BigInt(1) << 5) | (BigInt(1) << 18)
            writeCsr(dut, CSR.SSTATUS, before)

            dut.io.ret_type.poke(TrapReturnType.SRET)
            dut.io.is_ret.poke(true.B)

            dut.io.state_snapshot.privilegeMode.expect(PrivilegeLevel.Supervisor)
            dut.io.state_snapshot.mstatus.expect(after.U)
            dut.io.state_snapshot.sstatus.expect(sstatusAfter.U)
        }
    }

    test("CSRFile vectors delegated supervisor external interrupts to stvec") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            writeCsr(dut, CSR.MIDELEG, 1 << 9)
            writeCsr(dut, CSR.SIE, 1 << 9)
            writeCsr(dut, CSR.SSTATUS, 1 << 1)
            writeCsr(dut, CSR.STVEC, BigInt("80000300", 16) | 1)
            enterSupervisor(dut)
            writeCsr(dut, CSR.SSTATUS, 1 << 1)

            dut.io.seip.poke(true.B)
            dut.io.interrupt.expect(true.B)
            dut.io.interrupt_cause.expect(MCause.SupervisorExtInt)
            dut.io.tvec_out.expect(BigInt("80000300", 16) + 4 * 9)

            takeTrap(dut, BigInt("80000044", 16), MCause.SupervisorExtInt.litValue)
            dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Supervisor)
            dut.io.addr.poke(CSR.SEPC)
            dut.io.rdata.expect(BigInt("80000044", 16))
            dut.io.addr.poke(CSR.SCAUSE)
            dut.io.rdata.expect(MCause.SupervisorExtInt)
        }
    }

    test("CSRFile enforces CSR privilege and read-only address encoding") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            enterSupervisor(dut)

            dut.io.valid.poke(true.B)
            dut.io.write.poke(false.B)
            dut.io.addr.poke(CSR.SSTATUS)
            dut.io.illegal.expect(false.B)

            dut.io.addr.poke(CSR.MSTATUS)
            dut.io.illegal.expect(true.B)

            dut.io.write.poke(true.B)
            dut.io.addr.poke(CSR.MVENDORID)
            dut.io.illegal.expect(true.B)
        }
    }

    test("CSRFile exposes supervisor capability in misa and returns through sepc on SRET") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            dut.io.addr.poke(CSR.MISA)
            dut.io.rdata.expect(
                (BigInt(2) << 62) |
                    (1L << ('i' - 'a')) |
                    (1L << ('m' - 'a')) |
                    (1L << ('a' - 'a')) |
                    (1L << ('b' - 'a')) |
                    (1L << ('c' - 'a')) |
                    (1L << ('s' - 'a')) |
                    (1L << ('u' - 'a'))
            )

            writeCsr(dut, CSR.MEDELEG, 1 << 2)
            writeCsr(dut, CSR.STVEC, BigInt("80000200", 16))
            writeCsr(dut, CSR.MSTATUS, 1 << 11)
            takeRet(dut, TrapReturnType.MRET)
            dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Supervisor)

            writeCsr(dut, CSR.SEPC, BigInt("80000088", 16))
            dut.io.ret_type.poke(TrapReturnType.SRET)
            dut.io.is_ret.poke(true.B)
            dut.io.epc_out.expect(BigInt("80000088", 16))
            dut.clock.step()
            dut.io.is_ret.poke(false.B)
            dut.io.ret_type.poke(TrapReturnType.None)
        }
    }

    test("CSRFile exposes RustSBI platform CSRs without illegal traps") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            Seq(CSR.MCOUNTEREN, CSR.SCOUNTEREN, CSR.MENVCFG, CSR.MCOUNTINHIBIT).zipWithIndex.foreach { case (addr, idx) =>
                val value = BigInt("100", 16) + idx
                writeCsr(dut, addr, value)
                dut.io.valid.poke(true.B)
                dut.io.write.poke(false.B)
                dut.io.addr.poke(addr)
                dut.io.illegal.expect(false.B)
                dut.io.rdata.expect(value.U)
                dut.io.valid.poke(false.B)
            }

            for (i <- 0 until 8) {
                val addr = (0x3b0 + i).U(12.W)
                val value = BigInt("10000000", 16) + i
                writeCsr(dut, addr, value)
                dut.io.valid.poke(true.B)
                dut.io.write.poke(false.B)
                dut.io.addr.poke(addr)
                dut.io.illegal.expect(false.B)
                dut.io.rdata.expect(value.U)
                dut.io.mem_cfg_out.pmpaddr(i).expect(value.U)
                dut.io.valid.poke(false.B)
            }

            writeCsr(dut, CSR.PMPaddr0, BigInt("ffffffffffffffff", 16))
            dut.io.addr.poke(CSR.PMPaddr0)
            dut.io.rdata.expect(BigInt("3fffffff", 16).U)
            dut.io.mem_cfg_out.pmpaddr(0).expect(BigInt("3fffffff", 16).U)

            Seq(CSR.PMPcfg2, CSR.PMPaddr15).foreach { addr =>
                writeCsr(dut, addr, BigInt("ffffffffffffffff", 16))
                dut.io.valid.poke(true.B)
                dut.io.write.poke(false.B)
                dut.io.addr.poke(addr)
                dut.io.illegal.expect(false.B)
                dut.io.rdata.expect(0.U)
                dut.io.valid.poke(false.B)
            }
        }
    }

    test("CSRFile forwards same-cycle CSR writeback to CSR reads") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            dut.io.wvalid.poke(true.B)
            dut.io.wwrite.poke(true.B)
            dut.io.wcmd.poke(CSROps.RW.asUInt)
            dut.io.waddr.poke(CSR.SSCRATCH)
            dut.io.wwdata.poke(BigInt("12345678", 16).U)
            dut.io.valid.poke(true.B)
            dut.io.write.poke(false.B)
            dut.io.addr.poke(CSR.SSCRATCH)

            dut.io.illegal.expect(false.B)
            dut.io.rdata.expect(BigInt("12345678", 16).U)
        }
    }

    test("CSRFile exposes machine performance counter CSRs for RustSBI probing") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            Seq(CSR.MCYCLE, CSR.MINSTRET).foreach { addr =>
                dut.io.valid.poke(true.B)
                dut.io.write.poke(false.B)
                dut.io.addr.poke(addr)
                dut.io.illegal.expect(false.B)
                dut.io.valid.poke(false.B)
            }

            val mhpmcounter3 = 0xb03.U(12.W)
            writeCsr(dut, mhpmcounter3, 1)
            dut.io.valid.poke(true.B)
            dut.io.write.poke(true.B)
            dut.io.cmd.poke(CSROps.RW.asUInt)
            dut.io.addr.poke(mhpmcounter3)
            dut.io.wdata.poke(BigInt("1234", 16).U)
            dut.io.wvalid.poke(true.B)
            dut.io.wwrite.poke(true.B)
            dut.io.wcmd.poke(CSROps.RW.asUInt)
            dut.io.waddr.poke(mhpmcounter3)
            dut.io.wwdata.poke(BigInt("1234", 16).U)
            dut.io.illegal.expect(false.B)
            dut.io.rdata.expect(1.U)
            dut.clock.step()

            dut.io.wvalid.poke(false.B)
            dut.io.wwrite.poke(false.B)
            dut.io.waddr.poke(0.U)
            dut.io.wwdata.poke(0.U)
            dut.io.write.poke(false.B)
            dut.io.wdata.poke(0.U)
            dut.io.rdata.expect(BigInt("1234", 16).U)
            dut.io.valid.poke(false.B)
        }
    }

    test("CSRFile allows supervisor rdtime when enabled by mcounteren") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            val time = "hc01".U(12.W)

            enterSupervisor(dut)
            dut.io.valid.poke(true.B)
            dut.io.addr.poke(time)
            dut.io.write.poke(false.B)
            dut.io.illegal.expect(true.B)
        }

        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)
            val time = "hc01".U(12.W)
            writeCsr(dut, CSR.MCOUNTEREN, BigInt(1) << 1)
            dut.clock.step(4)
            enterSupervisor(dut)

            dut.io.valid.poke(true.B)
            dut.io.addr.poke(time)
            dut.io.write.poke(false.B)
            dut.io.illegal.expect(false.B)
            val first = dut.io.rdata.peek().litValue
            dut.clock.step(2)
            val second = dut.io.rdata.peek().litValue
            assert(second > first)
        }
    }

    test("CSRFile exports memory privilege controls for S-mode and MPRV data accesses") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            writeCsr(dut, CSR.MSTATUS, mstatusMxr | mstatusSum)
            dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Machine)
            dut.io.mem_cfg_out.data_priv.expect(PrivilegeLevel.Machine)
            dut.io.mem_cfg_out.mxr.expect(true.B)
            dut.io.mem_cfg_out.sum.expect(true.B)
            dut.io.mem_cfg_out.mprv.expect(false.B)

            writeCsr(dut, CSR.SSTATUS, mstatusMxr)
            dut.io.mem_cfg_out.mxr.expect(true.B)
            dut.io.mem_cfg_out.sum.expect(false.B)
            dut.io.addr.poke(CSR.SSTATUS)
            dut.io.rdata.expect(mstatusMxr.U)

            writeCsr(dut, CSR.MSTATUS, mstatusMprv | mstatusMppS | mstatusMxr | mstatusSum)
            dut.io.mem_cfg_out.priv.expect(PrivilegeLevel.Machine)
            dut.io.mem_cfg_out.data_priv.expect(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg_out.mxr.expect(true.B)
            dut.io.mem_cfg_out.sum.expect(true.B)
            dut.io.mem_cfg_out.mprv.expect(true.B)
        }
    }

    test("CSRFile counts retire and selected HPM events") {
        simulate(new CSRFile(xlen, hartID = 0)) { dut =>
            init(dut)

            writeCsr(dut, CSR.MINSTRET, 0)
            dut.clock.step()
            assert(readCsr(dut, CSR.MINSTRET) == 0)

            dut.io.perf.retire.poke(true.B)
            dut.clock.step()
            dut.io.perf.retire.poke(false.B)
            assert(readCsr(dut, CSR.MINSTRET) == 1)

            writeCsr(dut, CSR.MCOUNTINHIBIT, 1 << 2)
            dut.io.perf.retire.poke(true.B)
            dut.clock.step()
            dut.io.perf.retire.poke(false.B)
            assert(readCsr(dut, CSR.MINSTRET) == 1)

            writeCsr(dut, CSR.MCOUNTINHIBIT, 0)
            writeCsr(dut, CSR.MHPMEVENT3, HpmEventId.BranchRedirect)
            writeCsr(dut, CSR.MHPMCOUNTER3, 0)
            dut.io.perf.branchRedirect.poke(true.B)
            dut.clock.step()
            dut.io.perf.branchRedirect.poke(false.B)
            assert(readCsr(dut, CSR.MHPMCOUNTER3) == 1)

            val mhpmcounter4 = 0xb04.U(12.W)
            val mhpmevent4 = 0x324.U(12.W)
            writeCsr(dut, mhpmevent4, HpmEventId.LSULoadStall)
            writeCsr(dut, mhpmcounter4, 0)
            dut.io.perf.lsuLoadStall.poke(true.B)
            dut.clock.step()
            dut.io.perf.lsuLoadStall.poke(false.B)
            assert(readCsr(dut, mhpmcounter4) == 1)

            writeCsr(dut, CSR.MCOUNTINHIBIT, 1 << 3)
            dut.io.perf.branchRedirect.poke(true.B)
            dut.clock.step()
            dut.io.perf.branchRedirect.poke(false.B)
            assert(readCsr(dut, CSR.MHPMCOUNTER3) == 1)
        }
    }
}
