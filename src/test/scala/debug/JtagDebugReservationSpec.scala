package debug

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.debug._

class JtagDebugReservationSpec extends AnyFunSuite {
    test("default debug is absent structurally, with no registers or blackboxes") {
        val text = ChiselStage.emitCHIRRTL(new JtagDebugReservation())
        assert(!text.contains("extmodule"))
        assert(!text.contains("reg ") && !text.contains("regreset "))
        assert(!text.contains("inst "))
        assert(text.contains("connect tdo, UInt<1>(0h0)"))
        assert(text.contains("connect tdoOe, UInt<1>(0h0)"))
    }
    test("enabled debug exports independently clocked typed DMI and required resource") {
        val text = ChiselStage.emitCHIRRTL(new JtagDebugReservation(JtagDebugParams(enabled = true)))
        assert(text.contains("extmodule ValenceJtagDebugPort"))
        assert(text.contains("parameter IDCODE = 1"))
        assert(text.contains("parameter ABITS = 7"))
        assert(text.contains("parameter EXTERNAL_DMI = 0"))
        assert(text.contains("debugClock : Clock") && text.contains("tck : Clock"))
        assert(!text.contains("cpuReset") && !text.contains("haltRequest"))
    }
    test("bad identity, address width, hints and disabled external endpoint are rejected") {
        for (bits <- Seq(0, 33)) intercept[IllegalArgumentException](JtagDebugParams(addressBits = bits))
        for (id <- Seq(BigInt(-1), BigInt(0), BigInt(2), BigInt(1) << 32))
            intercept[IllegalArgumentException](JtagDebugParams(idcode = id))
        for (hint <- Seq(-1, 8)) intercept[IllegalArgumentException](JtagDebugParams(idleHint = hint))
        intercept[IllegalArgumentException](JtagDebugParams(externalDmi = true))
        assert(JtagDebugParams(enabled = true, externalDmi = true, idcode = BigInt("12345001", 16)).enabled)
    }
}
object JtagDebugReservationExport extends App {
    require(args.length == 2, "usage: JtagDebugReservationExport off|stub|external output-directory")
    val p = args(0) match {
        case "off" => JtagDebugParams()
        case "stub" => JtagDebugParams(enabled = true)
        case "external" => JtagDebugParams(enabled = true, externalDmi = true)
    }
    ChiselStage.emitSystemVerilogFile(new JtagDebugReservation(p), Array("--target-dir", args(1)),
        Array("--disable-all-randomization", "--strip-debug-info"))
    // Resource files are copied by Chisel, but firtool does not list them.
    if (p.enabled) {
        val list = java.nio.file.Paths.get(args(1), "filelist.f")
        java.nio.file.Files.write(list, "ValenceJtagDebugPort.sv\n".getBytes(java.nio.charset.StandardCharsets.UTF_8),
            java.nio.file.StandardOpenOption.APPEND)
    }
}
