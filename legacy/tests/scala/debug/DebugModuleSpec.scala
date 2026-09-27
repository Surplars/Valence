package debug

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import device.TileLinkDeviceTestUtils
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLParams, TLRAM}
import soc.debug.{DebugModule, DebugModuleMap}

class DebugModuleSbaHarness(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new soc.bus.tilelink.TLBundle(params))
    })

    val dm = Module(new DebugModule(params))
    val ram = Module(new TLRAM(params, sizeBytes = 4096, base = 0x1000))

    dm.io.tl <> io.tl
    ram.io.tl <> dm.io.sba
    dm.io.dmi_valid := false.B
    dm.io.dmi_addr := 0.U
    dm.io.dmi_wdata := 0.U
    dm.io.dmi_write := false.B
    dm.io.hart_halted := true.B
    dm.io.hart_pc := 0.U
    dm.io.gpr_rdata := 0.U
    dm.io.csr_rdata := 0.U
    dm.io.csr_valid := true.B
    dm.io.csr_writable := true.B
    dm.io.cache.dcacheAck := false.B
    dm.io.cache.icacheAck := false.B
    dm.io.cache.dcacheBusy := false.B
    dm.io.cache.icacheBusy := false.B
    dm.io.cache.dcacheErr := false.B
    dm.io.cache.icacheErr := false.B
}

class DebugModuleSpec extends AnyFunSuite with ChiselSim with TileLinkDeviceTestUtils {
    private def init(dut: DebugModule): Unit = {
        initTlSlave(dut.io.tl, size = 2)
        dut.io.sba.a.ready.poke(false.B)
        dut.io.sba.d.valid.poke(false.B)
        dut.io.sba.d.bits.opcode.poke(0.U)
        dut.io.sba.d.bits.param.poke(0.U)
        dut.io.sba.d.bits.size.poke(0.U)
        dut.io.sba.d.bits.source.poke(0.U)
        dut.io.sba.d.bits.sink.poke(0.U)
        dut.io.sba.d.bits.denied.poke(false.B)
        dut.io.sba.d.bits.data.poke(0.U)
        dut.io.sba.d.bits.corrupt.poke(false.B)
        dut.io.dmi_valid.poke(false.B)
        dut.io.dmi_addr.poke(0.U)
        dut.io.dmi_wdata.poke(0.U)
        dut.io.dmi_write.poke(false.B)
        dut.io.hart_halted.poke(false.B)
        dut.io.hart_pc.poke(0.U)
        dut.io.gpr_rdata.poke(0.U)
        dut.io.csr_rdata.poke(0.U)
        dut.io.csr_valid.poke(true.B)
        dut.io.csr_writable.poke(true.B)
        dut.io.cache.dcacheAck.poke(false.B)
        dut.io.cache.icacheAck.poke(false.B)
        dut.io.cache.dcacheBusy.poke(false.B)
        dut.io.cache.icacheBusy.poke(false.B)
        dut.io.cache.dcacheErr.poke(false.B)
        dut.io.cache.icacheErr.poke(false.B)
    }

    private def debugWrite(dut: DebugModule, address: BigInt, data: BigInt): Unit =
        writeTlWord(dut.io.tl, dut.clock, address, data)

    private def debugRead(dut: DebugModule, address: BigInt): BigInt =
        readTlWord(dut.io.tl, dut.clock, address)

    private def debugWrite(dut: DebugModuleSbaHarness, address: BigInt, data: BigInt): Unit =
        writeTlWord(dut.io.tl, dut.clock, address, data)

    private def debugRead(dut: DebugModuleSbaHarness, address: BigInt): BigInt =
        readTlWord(dut.io.tl, dut.clock, address)

    private def waitSbaIdle(dut: DebugModuleSbaHarness): BigInt = {
        var sbcs = BigInt(0)
        var idle = false
        for (_ <- 0 until 20) {
            sbcs = debugRead(dut, DebugModuleMap.SBCS * 4)
            if (((sbcs >> 21) & 0x1) == 0) {
                idle = true
                return sbcs
            }
            dut.clock.step()
        }
        assert(idle, f"SBA stayed busy, last sbcs=0x$sbcs%08x")
        sbcs
    }

    private def writeSbcs(
        dut: DebugModuleSbaHarness,
        sbaccess: Int,
        readOnAddr: Boolean = false,
        readOnData: Boolean = false,
        autoIncrement: Boolean = false
    ): Unit = {
        val value =
            (if (readOnAddr) BigInt(1) << 20 else BigInt(0)) |
                (BigInt(sbaccess) << 17) |
                (if (autoIncrement) BigInt(1) << 16 else BigInt(0)) |
                (if (readOnData) BigInt(1) << 15 else BigInt(0))
        debugWrite(dut, DebugModuleMap.SBCS * 4, value)
    }

    private def writeSbAddress(dut: DebugModuleSbaHarness, address: BigInt): Unit = {
        debugWrite(dut, DebugModuleMap.SBAddress1 * 4, address >> 32)
        debugWrite(dut, DebugModuleMap.SBAddress0 * 4, address & BigInt("ffffffff", 16))
    }

    private def startCommandWrite(dut: DebugModule, command: BigInt): Unit = {
        startDebugWrite(dut, DebugModuleMap.Command * 4, command)
    }

    private def startDebugWrite(dut: DebugModule, address: BigInt, data: BigInt): Unit = {
        val lane = (address & 0x7).toInt
        dut.io.tl.d.ready.poke(true.B)
        dut.io.tl.a.bits.opcode.poke(soc.bus.tilelink.TLOpcode.PutPartialData)
        dut.io.tl.a.bits.param.poke(0.U)
        dut.io.tl.a.bits.size.poke(2.U)
        dut.io.tl.a.bits.source.poke(3.U)
        dut.io.tl.a.bits.address.poke(address.U)
        dut.io.tl.a.bits.mask.poke((0xf << lane).U)
        dut.io.tl.a.bits.data.poke((data << (lane * 8)).U)
        dut.io.tl.a.bits.corrupt.poke(false.B)
        dut.io.tl.a.valid.poke(true.B)
        dut.io.tl.a.ready.expect(true.B)
        dut.clock.step()
        dut.io.tl.a.valid.poke(false.B)
    }

    private def writeCommandAndExpectGprWrite(dut: DebugModule, command: BigInt, addr: BigInt, data: BigInt): Unit = {
        debugWrite(dut, DebugModuleMap.Data0 * 4, data & BigInt("ffffffff", 16))
        debugWrite(dut, DebugModuleMap.Data1 * 4, data >> 32)

        startCommandWrite(dut, command)
        dut.io.gpr_write.expect(true.B)
        dut.io.gpr_addr.expect(addr.U)
        dut.io.gpr_wdata.expect(data.U)
        dut.io.tl.d.valid.expect(true.B)
        dut.clock.step()
    }

    private def writeCommandAndExpectCsrWrite(dut: DebugModule, command: BigInt, addr: BigInt, data: BigInt): Unit = {
        debugWrite(dut, DebugModuleMap.Data0 * 4, data & BigInt("ffffffff", 16))
        debugWrite(dut, DebugModuleMap.Data1 * 4, data >> 32)

        startCommandWrite(dut, command)
        dut.io.csr_write.expect(true.B)
        dut.io.csr_addr.expect(addr.U)
        dut.io.csr_wdata.expect(data.U)
        dut.io.tl.d.valid.expect(true.B)
        dut.clock.step()
    }

    private def clearCmderr(dut: DebugModule): Unit =
        debugWrite(dut, DebugModuleMap.AbstractCS * 4, BigInt("00000700", 16))

    private def accessRegCommand(regno: BigInt, write: Boolean = false, postexec: Boolean = false): BigInt =
        BigInt("00300000", 16) |
            (if (postexec) BigInt(1) << 18 else BigInt(0)) |
            (BigInt(1) << 17) |
            (if (write) BigInt(1) << 16 else BigInt(0)) |
            regno

    private def postexecOnlyCommand: BigInt =
        BigInt("00300000", 16) | (BigInt(1) << 18)

    test("DebugModule supports halt control and abstract GPR/CSR access") {
        simulate(new DebugModule(deviceParams)) { dut =>
            init(dut)

            debugWrite(dut, DebugModuleMap.DMControl * 4, BigInt("80000001", 16))
            assert(debugRead(dut, DebugModuleMap.DMControl * 4) == BigInt("80000001", 16))
            dut.io.dmactive.expect(true.B)
            dut.io.haltreq.expect(true.B)
            assert((debugRead(dut, DebugModuleMap.DMStatus * 4) & 0xf) == 2)
            assert(((debugRead(dut, DebugModuleMap.DMStatus * 4) >> 7) & 0x1) == 0x1)
            assert(((debugRead(dut, DebugModuleMap.DMStatus * 4) >> 10) & 0x3) == 0x3)
            assert(((debugRead(dut, DebugModuleMap.DMStatus * 4) >> 18) & 0x3) == 0x3)
            assert(debugRead(dut, DebugModuleMap.HartInfo * 4) != BigInt(0))
            assert((debugRead(dut, DebugModuleMap.SBCS * 4) & BigInt("f", 16)) == BigInt("f", 16))

            dut.io.hart_pc.poke("h80000044".U)
            dut.io.hart_halted.poke(true.B)
            assert(((debugRead(dut, DebugModuleMap.DMStatus * 4) >> 8) & 0x3) == 0x3)
            dut.clock.step()
            assert(debugRead(dut, DebugModuleMap.HaltSum0 * 4) == BigInt(1))
            debugWrite(dut, DebugModuleMap.DMControl * 4, BigInt("10000001", 16))
            assert(debugRead(dut, DebugModuleMap.DMControl * 4) == BigInt("00000001", 16))
            assert(((debugRead(dut, DebugModuleMap.DMStatus * 4) >> 18) & 0x3) == 0)
            dut.io.dmi_addr.poke(DebugModuleMap.DMControl.U)
            dut.io.dmi_wdata.poke("h40000001".U)
            dut.io.dmi_write.poke(true.B)
            dut.io.dmi_valid.poke(true.B)
            dut.io.resumereq.expect(true.B)
            dut.clock.step()
            dut.io.dmi_valid.poke(false.B)
            dut.io.dmi_write.poke(false.B)
            dut.clock.step()
            assert(debugRead(dut, DebugModuleMap.DMControl * 4) == BigInt("00000001", 16))
            dut.io.resumereq.expect(false.B)
            assert(debugRead(dut, DebugModuleMap.AbstractAuto * 4) == BigInt(0))
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 24) & 0x1f) == BigInt(2))
            debugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("00100073", 16)) // ebreak
            assert(debugRead(dut, DebugModuleMap.ProgBuf0 * 4) == BigInt("00100073", 16))
            assert(debugRead(dut, DebugModuleMap.ProgBuf1 * 4) == BigInt(0))
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt(0))

            debugWrite(dut, DebugModuleMap.Command * 4, BigInt("003207b0", 16))
            assert(((debugRead(dut, DebugModuleMap.Data0 * 4) >> 6) & 0x7) == 3)
            assert(debugRead(dut, DebugModuleMap.Data1 * 4) == BigInt(0))

            debugWrite(dut, DebugModuleMap.Command * 4, BigInt("003207b1", 16))
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt("80000044", 16))
            assert(debugRead(dut, DebugModuleMap.Data1 * 4) == BigInt(0))

            dut.io.dmi_addr.poke(DebugModuleMap.Data0.U)
            dut.io.dmi_wdata.poke("h12345678".U)
            dut.io.dmi_write.poke(true.B)
            dut.io.dmi_valid.poke(true.B)
            dut.clock.step()
            dut.io.dmi_valid.poke(false.B)
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt("12345678", 16))

            dut.io.hart_halted.poke(true.B)
            writeCommandAndExpectGprWrite(dut, BigInt("00331005", 16), addr = 5, data = BigInt("1122334455667788", 16))

            dut.io.gpr_rdata.poke("h8877665544332211".U)
            debugWrite(dut, DebugModuleMap.Command * 4, BigInt("00321005", 16))
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt("44332211", 16))
            assert(debugRead(dut, DebugModuleMap.Data1 * 4) == BigInt("88776655", 16))

            writeCommandAndExpectCsrWrite(
                dut,
                BigInt("00330300", 16),
                addr = BigInt("300", 16),
                data = BigInt("0123456789abcdef", 16)
            )

            dut.io.csr_rdata.poke("h4000110100000105".U)
            debugWrite(dut, DebugModuleMap.Command * 4, BigInt("00320301", 16))
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt("00000105", 16))
            assert(debugRead(dut, DebugModuleMap.Data1 * 4) == BigInt("40001101", 16))

            dut.io.csr_valid.poke(false.B)
            debugWrite(dut, DebugModuleMap.Command * 4, BigInt("00320c22", 16))
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 2)
            clearCmderr(dut)
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 0)
        }
    }

    test("DebugModule interprets a safe progbuf postexec subset") {
        simulate(new DebugModule(deviceParams)) { dut =>
            init(dut)
            dut.io.hart_halted.poke(true.B)
            dut.io.gpr_rdata.poke("h123456789abcdef0".U)

            debugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("0000100f", 16)) // fence.i
            debugWrite(dut, DebugModuleMap.ProgBuf1 * 4, BigInt("00100073", 16)) // ebreak
            debugWrite(dut, DebugModuleMap.Command * 4, postexecOnlyCommand)
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 0)

            debugWrite(dut, DebugModuleMap.Command * 4, accessRegCommand(BigInt("1005", 16), postexec = true))
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt("9abcdef0", 16))
            assert(debugRead(dut, DebugModuleMap.Data1 * 4) == BigInt("12345678", 16))
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 0)

            debugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("0330000f", 16)) // fence rw,rw
            debugWrite(dut, DebugModuleMap.ProgBuf1 * 4, BigInt("00100073", 16))
            debugWrite(dut, DebugModuleMap.Command * 4, postexecOnlyCommand)
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 0)

            debugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("00000013", 16)) // nop, no terminating ebreak
            debugWrite(dut, DebugModuleMap.ProgBuf1 * 4, BigInt("00000013", 16))
            debugWrite(dut, DebugModuleMap.Command * 4, accessRegCommand(BigInt("1005", 16), postexec = true))
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 2)
            clearCmderr(dut)

            debugWrite(dut, DebugModuleMap.Data0 * 4, BigInt("feedface", 16))
            debugWrite(dut, DebugModuleMap.Data1 * 4, BigInt("01234567", 16))
            debugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("00002003", 16)) // lw x0,0(x0), unsupported
            debugWrite(dut, DebugModuleMap.ProgBuf1 * 4, BigInt("00100073", 16))
            debugWrite(dut, DebugModuleMap.Command * 4, accessRegCommand(BigInt("1005", 16), write = true, postexec = true))
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 2)
            dut.io.gpr_write.expect(false.B)
        }
    }

    test("DebugModule supports abstractauto for data and progbuf registers") {
        simulate(new DebugModule(deviceParams)) { dut =>
            init(dut)
            dut.io.hart_halted.poke(true.B)

            debugWrite(dut, DebugModuleMap.AbstractAuto * 4, BigInt("ffff0003", 16))
            assert(debugRead(dut, DebugModuleMap.AbstractAuto * 4) == BigInt("00030003", 16))

            debugWrite(dut, DebugModuleMap.Command * 4, accessRegCommand(BigInt("1005", 16), write = true))
            startDebugWrite(dut, DebugModuleMap.Data0 * 4, BigInt("55667788", 16))
            dut.io.gpr_write.expect(true.B)
            dut.io.gpr_addr.expect(5.U)
            dut.io.gpr_wdata.expect(BigInt("0000000055667788", 16).U)
            dut.clock.step()

            debugWrite(dut, DebugModuleMap.AbstractAuto * 4, BigInt("00000001", 16)) // autoexecdata0 only
            startDebugWrite(dut, DebugModuleMap.Data1 * 4, BigInt("11223344", 16))
            dut.io.gpr_write.expect(false.B)
            dut.clock.step()
            startDebugWrite(dut, DebugModuleMap.Data0 * 4, BigInt("99aabbcc", 16))
            dut.io.gpr_write.expect(true.B)
            dut.io.gpr_wdata.expect(BigInt("1122334499aabbcc", 16).U)
            dut.clock.step()

            dut.io.gpr_rdata.poke("hdeadbeefcafebabe".U)
            debugWrite(dut, DebugModuleMap.Command * 4, accessRegCommand(BigInt("1006", 16)))
            debugWrite(dut, DebugModuleMap.AbstractAuto * 4, BigInt("00000002", 16)) // autoexecdata1
            debugRead(dut, DebugModuleMap.Data1 * 4) // The read returns old data and triggers the command.
            assert(debugRead(dut, DebugModuleMap.Data1 * 4) == BigInt("deadbeef", 16))
            assert(debugRead(dut, DebugModuleMap.Data0 * 4) == BigInt("cafebabe", 16))

            debugWrite(dut, DebugModuleMap.AbstractAuto * 4, BigInt(0))
            debugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("0330000f", 16)) // fence rw,rw
            debugWrite(dut, DebugModuleMap.ProgBuf1 * 4, BigInt("00100073", 16)) // ebreak
            debugWrite(dut, DebugModuleMap.Command * 4, postexecOnlyCommand)
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 0)
            debugWrite(dut, DebugModuleMap.AbstractAuto * 4, BigInt("00010000", 16)) // autoexecprogbuf0
            startDebugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("0330000f", 16)) // fence rw,rw, autoexec succeeds
            dut.clock.step()
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 0)

            startDebugWrite(dut, DebugModuleMap.ProgBuf0 * 4, BigInt("00002003", 16)) // unsupported lw, autoexec fails
            dut.clock.step()
            assert(((debugRead(dut, DebugModuleMap.AbstractCS * 4) >> 8) & 0x7) == 2)
        }
    }

    test("DebugModule exposes Ion cache maintenance control") {
        simulate(new DebugModule(deviceParams)) { dut =>
            init(dut)

            assert(debugRead(dut, DebugModuleMap.IonCacheCtl * 4) == BigInt(0))

            dut.io.dmi_addr.poke(DebugModuleMap.IonCacheCtl.U)
            dut.io.dmi_wdata.poke("h00000003".U)
            dut.io.dmi_write.poke(true.B)
            dut.io.dmi_valid.poke(true.B)
            dut.io.cache.dcacheReq.expect(true.B)
            dut.io.cache.icacheReq.expect(true.B)
            dut.clock.step()
            dut.io.dmi_valid.poke(false.B)
            dut.io.dmi_write.poke(false.B)
            dut.io.cache.dcacheReq.expect(false.B)
            dut.io.cache.icacheReq.expect(false.B)

            dut.io.cache.dcacheBusy.poke(true.B)
            dut.io.cache.icacheBusy.poke(true.B)
            assert((debugRead(dut, DebugModuleMap.IonCacheCtl * 4) & BigInt("00000003", 16)) == BigInt("00000003", 16))
            dut.io.cache.dcacheBusy.poke(false.B)
            dut.io.cache.icacheBusy.poke(false.B)

            dut.io.cache.dcacheAck.poke(true.B)
            dut.io.cache.dcacheErr.poke(true.B)
            dut.clock.step()
            dut.io.cache.dcacheAck.poke(false.B)
            dut.io.cache.dcacheErr.poke(false.B)
            assert((debugRead(dut, DebugModuleMap.IonCacheCtl * 4) & BigInt("00010100", 16)) == BigInt("00010100", 16))

            debugWrite(dut, DebugModuleMap.IonCacheCtl * 4, BigInt("00010100", 16))
            assert((debugRead(dut, DebugModuleMap.IonCacheCtl * 4) & BigInt("00010100", 16)) == BigInt(0))

            debugWrite(dut, DebugModuleMap.IonCacheCtl * 4, BigInt("00000003", 16))
            dut.io.cache.dcacheReq.expect(false.B)
            dut.io.cache.icacheReq.expect(false.B)
        }
    }

    test("DebugModule SBA reads and writes memory through TileLink") {
        simulate(new DebugModuleSbaHarness(deviceParams)) { dut =>
            initTlSlave(dut.io.tl, size = 2)

            debugWrite(dut, DebugModuleMap.SBCS * 4, BigInt("00040000", 16)) // sbaccess=2, 32-bit
            debugWrite(dut, DebugModuleMap.SBAddress0 * 4, 0x1000)
            debugWrite(dut, DebugModuleMap.SBData0 * 4, BigInt("89abcdef", 16))
            assert(((waitSbaIdle(dut) >> 12) & 0x7) == 0)
            debugWrite(dut, DebugModuleMap.SBAddress0 * 4, 0x1008)
            debugWrite(dut, DebugModuleMap.SBData0 * 4, BigInt("12345678", 16))
            assert(((waitSbaIdle(dut) >> 12) & 0x7) == 0)

            debugWrite(dut, DebugModuleMap.SBCS * 4, BigInt("00140000", 16)) // sbreadonaddr + sbaccess=2
            debugWrite(dut, DebugModuleMap.SBAddress0 * 4, 0x1000)
            waitSbaIdle(dut)
            assert(debugRead(dut, DebugModuleMap.SBData0 * 4) == BigInt("89abcdef", 16))

            // The read-on-address request must use the just-written address,
            // not the previous sbaddress value.
            debugWrite(dut, DebugModuleMap.SBAddress0 * 4, 0x1008)
            waitSbaIdle(dut)
            assert(debugRead(dut, DebugModuleMap.SBData0 * 4) == BigInt("12345678", 16))
        }
    }

    test("DebugModule SBA splits cross-beat accesses") {
        simulate(new DebugModuleSbaHarness(deviceParams)) { dut =>
            initTlSlave(dut.io.tl, size = 2)

            writeSbcs(dut, sbaccess = 2) // 32-bit access
            writeSbAddress(dut, 0x1006)
            debugWrite(dut, DebugModuleMap.SBData0 * 4, BigInt("aabbccdd", 16))
            assert(((waitSbaIdle(dut) >> 12) & 0x7) == 0)

            writeSbcs(dut, sbaccess = 2, readOnAddr = true)
            writeSbAddress(dut, 0x1006)
            waitSbaIdle(dut)
            assert(debugRead(dut, DebugModuleMap.SBData0 * 4) == BigInt("aabbccdd", 16))

            writeSbcs(dut, sbaccess = 3, autoIncrement = true) // 64-bit access
            writeSbAddress(dut, 0x1004)
            debugWrite(dut, DebugModuleMap.SBData0 * 4, BigInt("01234567", 16))
            debugWrite(dut, DebugModuleMap.SBData1 * 4, BigInt("89abcdef", 16))
            assert(((waitSbaIdle(dut) >> 12) & 0x7) == 0)
            assert(debugRead(dut, DebugModuleMap.SBAddress0 * 4) == BigInt("100c", 16))

            writeSbcs(dut, sbaccess = 3, readOnAddr = true)
            writeSbAddress(dut, 0x1004)
            waitSbaIdle(dut)
            assert(debugRead(dut, DebugModuleMap.SBData0 * 4) == BigInt("01234567", 16))
            assert(debugRead(dut, DebugModuleMap.SBData1 * 4) == BigInt("89abcdef", 16))
        }
    }
}
