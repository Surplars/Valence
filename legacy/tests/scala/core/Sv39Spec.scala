package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline._
import soc.isa.{MCause, PrivilegeLevel}

class Sv39Spec extends AnyFunSuite with ChiselSim {
    private val V = 1 << 0
    private val R = 1 << 1
    private val W = 1 << 2
    private val X = 1 << 3
    private val U = 1 << 4
    private val A = 1 << 6
    private val D = 1 << 7

    private def pte(ppn: BigInt, flags: Int): BigInt = (ppn << 10) | BigInt(flags)
    private def ppn(pa: BigInt): BigInt = pa >> 12

    private def init(dut: Sv39PteTranslator): Unit = {
        dut.io.valid.poke(true.B)
        dut.io.vaddr.poke(0.U)
        dut.io.pte.poke(0.U)
        dut.io.level.poke(0.U)
        dut.io.access.poke(Sv39AccessType.Load)
        dut.io.priv.poke(PrivilegeLevel.Supervisor)
        dut.io.mxr.poke(false.B)
        dut.io.sum.poke(false.B)
    }

    test("Sv39PteTranslator maps a valid 4 KiB leaf PTE") {
        simulate(new Sv39PteTranslator(64)) { dut =>
            init(dut)
            val va = BigInt("0000000010000678", 16)
            val pa = BigInt("0000000012345000", 16)
            dut.io.vaddr.poke(va.U)
            dut.io.pte.poke(pte(ppn(pa), V | R | W | A | D).U)
            dut.io.level.poke(0.U)

            dut.io.leaf.expect(true.B)
            dut.io.fault.valid.expect(false.B)
            dut.io.paddr.expect((pa | (va & 0xfff)).U)
        }
    }

    test("Sv39PteTranslator composes superpage physical addresses from VA low VPNs") {
        simulate(new Sv39PteTranslator(64)) { dut =>
            init(dut)
            val va = BigInt("0000000012345678", 16)

            val level1Pa = BigInt("0000000080200000", 16)
            dut.io.vaddr.poke(va.U)
            dut.io.pte.poke(pte(ppn(level1Pa), V | R | W | A | D).U)
            dut.io.level.poke(1.U)
            dut.io.paddr.expect((level1Pa | (va & BigInt("1fffff", 16))).U)
            dut.io.fault.valid.expect(false.B)

            val level2Pa = BigInt("0000000100000000", 16)
            dut.io.pte.poke(pte(ppn(level2Pa), V | R | W | A | D).U)
            dut.io.level.poke(2.U)
            dut.io.paddr.expect((level2Pa | (va & BigInt("3fffffff", 16))).U)
            dut.io.fault.valid.expect(false.B)
        }
    }

    test("Sv39PteTranslator reports page faults for invalid encodings and noncanonical VA") {
        simulate(new Sv39PteTranslator(64)) { dut =>
            init(dut)
            dut.io.vaddr.poke(BigInt("0000000010000000", 16).U)
            dut.io.pte.poke(pte(0x1000, V | W | A | D).U)
            dut.io.fault.valid.expect(true.B)
            dut.io.fault.cause.expect(MCause.LoadPageFault)

            dut.io.pte.poke((pte(0x1000, V | R | A | D) | (BigInt(1) << 63)).U)
            dut.io.fault.valid.expect(true.B)

            dut.io.vaddr.poke(BigInt("0000008000000000", 16).U)
            dut.io.pte.poke(pte(0x1000, V | R | A | D).U)
            dut.io.fault.valid.expect(true.B)
        }
    }

    test("Sv39PteTranslator enforces A/D bits and superpage alignment") {
        simulate(new Sv39PteTranslator(64)) { dut =>
            init(dut)
            dut.io.vaddr.poke(BigInt("0000000010000000", 16).U)
            dut.io.access.poke(Sv39AccessType.Store)
            dut.io.pte.poke(pte(0x1000, V | R | W | A).U)
            dut.io.fault.valid.expect(true.B)
            dut.io.fault.cause.expect(MCause.StorePageFault)

            dut.io.access.poke(Sv39AccessType.Load)
            dut.io.level.poke(1.U)
            dut.io.pte.poke(pte(0x1001, V | R | W | A | D).U)
            dut.io.fault.valid.expect(true.B)
            dut.io.fault.cause.expect(MCause.LoadPageFault)
        }
    }

    test("Sv39PteTranslator enforces U/SUM/MXR leaf permissions") {
        simulate(new Sv39PteTranslator(64)) { dut =>
            init(dut)
            dut.io.vaddr.poke(BigInt("0000000010000000", 16).U)
            dut.io.pte.poke(pte(0x1000, V | R | U | A | D).U)
            dut.io.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.sum.poke(false.B)
            dut.io.fault.valid.expect(true.B)

            dut.io.sum.poke(true.B)
            dut.io.fault.valid.expect(false.B)

            dut.io.access.poke(Sv39AccessType.Fetch)
            dut.io.pte.poke(pte(0x1000, V | X | U | A | D).U)
            dut.io.fault.valid.expect(true.B)
            dut.io.fault.cause.expect(MCause.InstrPageFault)

            dut.io.access.poke(Sv39AccessType.Load)
            dut.io.sum.poke(false.B)
            dut.io.priv.poke(PrivilegeLevel.User)
            dut.io.mxr.poke(false.B)
            dut.io.fault.valid.expect(true.B)

            dut.io.mxr.poke(true.B)
            dut.io.fault.valid.expect(false.B)
        }
    }

    test("Sv39PteTranslator classifies non-leaf PTEs and faults below level zero") {
        simulate(new Sv39PteTranslator(64)) { dut =>
            init(dut)
            val nextTable = BigInt("0000000080000000", 16)
            dut.io.level.poke(2.U)
            dut.io.pte.poke(pte(ppn(nextTable), V).U)
            dut.io.leaf.expect(false.B)
            dut.io.fault.valid.expect(false.B)
            dut.io.nextTablePaddr.expect(nextTable.U)

            dut.io.level.poke(0.U)
            dut.io.fault.valid.expect(true.B)
            dut.io.fault.cause.expect(MCause.LoadPageFault)
        }
    }

    private def initWalker(dut: Sv39PageTableWalker): Unit = {
        dut.io.req.valid.poke(false.B)
        dut.io.req.bits.vaddr.poke(0.U)
        dut.io.req.bits.satp.poke(0.U)
        dut.io.req.bits.access.poke(Sv39AccessType.Load)
        dut.io.req.bits.priv.poke(PrivilegeLevel.Supervisor)
        dut.io.req.bits.mxr.poke(false.B)
        dut.io.req.bits.sum.poke(false.B)
        dut.io.resp.ready.poke(true.B)
        dut.io.mem.req.ready.poke(true.B)
        dut.io.mem.resp.valid.poke(false.B)
        dut.io.mem.resp.bits.rdata.poke(0.U)
        dut.io.mem.resp.bits.err.poke(false.B)
    }

    private def satp(root: BigInt): BigInt = (BigInt(8) << 60) | (root >> 12)

    private def expectRead(dut: Sv39PageTableWalker, addr: BigInt): Unit = {
        dut.io.mem.req.valid.expect(true.B)
        dut.io.mem.req.bits.addr.expect(addr.U)
        dut.io.mem.req.bits.size.expect(3.U)
        dut.io.mem.req.bits.mask.expect("hff".U)
        dut.io.mem.req.bits.cacheable.expect(true.B)
        dut.io.mem.req.bits.device.expect(false.B)
    }

    private def acceptRead(dut: Sv39PageTableWalker, pteValue: BigInt): Unit = {
        dut.clock.step()
        dut.io.mem.resp.valid.poke(true.B)
        dut.io.mem.resp.bits.rdata.poke(pteValue.U)
        dut.clock.step()
        dut.io.mem.resp.valid.poke(false.B)
    }

    test("Sv39PageTableWalker walks three levels to a 4 KiB leaf PTE") {
        simulate(new Sv39PageTableWalker(64)) { dut =>
            initWalker(dut)
            val root = BigInt("0000000080000000", 16)
            val l1 = BigInt("0000000080001000", 16)
            val l0 = BigInt("0000000080002000", 16)
            val leafPa = BigInt("0000000012345000", 16)
            val va = BigInt("0000000012345678", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.req.valid.poke(true.B)
            dut.io.req.bits.vaddr.poke(va.U)
            dut.io.req.bits.satp.poke(satp(root).U)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            expectRead(dut, root + vpn2 * 8)
            acceptRead(dut, pte(ppn(l1), V))
            expectRead(dut, l1 + vpn1 * 8)
            acceptRead(dut, pte(ppn(l0), V))
            expectRead(dut, l0 + vpn0 * 8)
            acceptRead(dut, pte(ppn(leafPa), V | R | W | A | D))

            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.fault.valid.expect(false.B)
            dut.io.resp.bits.paddr.expect((leafPa | (va & 0xfff)).U)
        }
    }

    test("Sv39PageTableWalker resolves a level-1 superpage leaf") {
        simulate(new Sv39PageTableWalker(64)) { dut =>
            initWalker(dut)
            val root = BigInt("0000000080000000", 16)
            val l1 = BigInt("0000000080001000", 16)
            val superPa = BigInt("0000000040200000", 16)
            val va = BigInt("0000000012345678", 16)
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.req.valid.poke(true.B)
            dut.io.req.bits.vaddr.poke(va.U)
            dut.io.req.bits.satp.poke(satp(root).U)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            expectRead(dut, root + vpn2 * 8)
            acceptRead(dut, pte(ppn(l1), V))
            expectRead(dut, l1 + vpn1 * 8)
            acceptRead(dut, pte(ppn(superPa), V | R | W | A | D))

            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.fault.valid.expect(false.B)
            dut.io.resp.bits.paddr.expect((superPa | (va & BigInt("1fffff", 16))).U)
        }
    }

    test("Sv39PageTableWalker accepts a memory response in the request cycle") {
        simulate(new Sv39PageTableWalker(64)) { dut =>
            initWalker(dut)
            val root = BigInt("0000000080000000", 16)
            val leafPa = BigInt("0000000040000000", 16)
            val va = BigInt("0000000012345678", 16)
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.req.valid.poke(true.B)
            dut.io.req.bits.vaddr.poke(va.U)
            dut.io.req.bits.satp.poke(satp(root).U)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            expectRead(dut, root + vpn2 * 8)
            dut.io.mem.resp.valid.poke(true.B)
            dut.io.mem.resp.bits.rdata.poke(pte(ppn(leafPa), V | R | W | A | D).U)
            dut.clock.step()
            dut.io.mem.resp.valid.poke(false.B)

            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.fault.valid.expect(false.B)
            dut.io.resp.bits.paddr.expect((leafPa | (va & BigInt("3fffffff", 16))).U)
        }
    }

    test("Sv39PageTableWalker returns page faults and memory access faults") {
        simulate(new Sv39PageTableWalker(64)) { dut =>
            initWalker(dut)
            val root = BigInt("0000000080000000", 16)
            val va = BigInt("0000000010000000", 16)
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.req.valid.poke(true.B)
            dut.io.req.bits.vaddr.poke(va.U)
            dut.io.req.bits.satp.poke(satp(root).U)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            expectRead(dut, root + vpn2 * 8)
            acceptRead(dut, pte(0x1000, V | W | A | D))
            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.fault.valid.expect(true.B)
            dut.io.resp.bits.fault.cause.expect(MCause.LoadPageFault)
            dut.io.resp.ready.poke(true.B)
            dut.clock.step()

            dut.io.req.valid.poke(true.B)
            dut.io.req.bits.vaddr.poke(va.U)
            dut.io.req.bits.satp.poke(satp(root).U)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            expectRead(dut, root + vpn2 * 8)
            dut.clock.step()
            dut.io.mem.resp.valid.poke(true.B)
            dut.io.mem.resp.bits.err.poke(true.B)
            dut.clock.step()
            dut.io.mem.resp.valid.poke(false.B)
            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.fault.valid.expect(true.B)
            dut.io.resp.bits.fault.cause.expect(MCause.LoadAccessFault)
        }
    }
}
