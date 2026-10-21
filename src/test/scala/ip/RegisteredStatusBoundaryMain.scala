package soc.ip

import circt.stage.ChiselStage
import soc.ip.bus.RegisteredStatusClockBoundary

/** Native event-driven simulation emitter; no GSIM multi-clock claim. */
object RegisteredStatusBoundaryMain extends App {
    require(args.length == 1, "usage: RegisteredStatusBoundaryMain <output-directory>")
    ChiselStage.emitSystemVerilogFile(
        new RegisteredStatusClockBoundary,
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable",
            "--verification-flavor=if-else-fatal")
    )
}

/** Reuse the existing independent RX-stop fixture without rewriting generated RTL. */
object RxAdmissionStopIcarusMain extends App {
    require(args.length == 1, "usage: RxAdmissionStopIcarusMain <output-directory>")
    ChiselStage.emitSystemVerilogFile(
        new _root_.ip.GmacRxAdmissionStopCdcTop,
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable",
            "--verification-flavor=if-else-fatal")
    )
}
