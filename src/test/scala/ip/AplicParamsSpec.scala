package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.interrupt._
import soc.core.ooo._

class AplicParamsSpec extends AnyFunSuite {
    test("APLIC rejects invalid sources, identity widths and overlapping address windows") {
        for (n <- Seq(0, 1024)) intercept[IllegalArgumentException] { AplicParams(sources = n) }
        intercept[IllegalArgumentException] { AplicParams(identities = 32) }
        intercept[IllegalArgumentException] { AplicParams(base = 1) }
        intercept[IllegalArgumentException] { AplicParams(msiBase = BigInt(1) << 56) }
        intercept[IllegalArgumentException] { AplicParams(msiBase = BigInt("0c001000", 16)) }
    }
    test("APLIC single-source and maximum source banks elaborate independently") {
        for (n <- Seq(1, 1023)) {
            val rtl = ChiselStage.emitCHIRRTL(new Aplic(AplicParams(sources = n)))
            assert(rtl.contains("module Aplic") && !rtl.contains("IntegerBackend"))
        }
    }
    test("wired machine assembly connects independent APLIC and IMSIC") {
        val rtl = ChiselStage.emitCHIRRTL(new WiredMachineCore(OooParams(robEntries = 8, physicalRegs = 36)))
        assert(rtl.contains("module Aplic") && rtl.contains("module Imsic") && rtl.contains("module MachineCore"))
    }
    test("mapped machine rejects speculative RAM aliasing its MMIO window") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(
                new MappedMachineCore(
                    OooParams(speculativeRamBase = BigInt("0c000000", 16), speculativeRamBytes = 4096)
                )
            )
        }
        val rtl = ChiselStage.emitCHIRRTL(new MappedMachineCore())
        assert(rtl.contains("module CoreRegisterRouter") && rtl.contains("module Aplic"))
    }

}
