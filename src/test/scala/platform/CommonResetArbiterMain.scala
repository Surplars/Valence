package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.ResetDefinedRRArbiter

/** Four-state fixture; the legacy arm deliberately preserves unknown lastGrant. */
class CommonResetArbiterFixture(n: Int, legacy: Boolean) extends Module {
    val io = IO(new ArbiterIO(UInt(16.W), n))
    val ports = if (legacy) Module(new RRArbiter(UInt(16.W), n)).suggestName("arbiter").io
        else Module(new ResetDefinedRRArbiter(UInt(16.W), n)).suggestName("arbiter").io
    for (i <- 0 until n) ports.in(i) <> io.in(i)
    io.out <> ports.out
    io.chosen := ports.chosen
}

object CommonResetArbiterMain extends App {
    require(args.length == 3, "output-directory inputs fixed|legacy")
    require(Set("fixed", "legacy")(args(2)))
    ChiselStage.emitSystemVerilogFile(new CommonResetArbiterFixture(args(1).toInt, args(2) == "legacy"),
        Array("--target-dir", args(0)),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=enable"))
}
