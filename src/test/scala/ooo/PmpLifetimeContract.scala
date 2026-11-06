package ooo

import chisel3._
import soc.core.ooo._
import _root_.circt.stage.ChiselStage

// Test-only raw-input helper fixture, not an FP pipeline or walker simulation.
// PmpLifetimeSpec separately verifies the actual production owner wiring.
// Illegal and X inputs deliberately bypass normal caller alignment sanitizers.
class PmpLifetimeContract(decoded: Boolean) extends Module {
    val io = IO(new Bundle {
        val state = Input(new PmpState)
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val privilege = Input(UInt(2.W))
        val access = Input(UInt(2.W))
        val preparedValid = Input(Bool())
        val walker0State = Input(UInt(2.W))
        val walker1State = Input(UInt(2.W))
        val denied = Output(Vec(3, Bool()))
    })
    val owners = Seq(io.preparedValid, io.walker0State === 1.U, io.walker1State === 1.U)
    for (i <- 0 until 3) {
        io.denied(i) := NaturalPmpEvaluation.denied(16, decoded, true, io.state,
            io.address, io.size, io.privilege, io.access,
            assertionReset = Some(reset.asBool || !owners(i)))
    }
}
object PmpLifetimeContractMain extends App {
    require(args.length == 1 || (args.length == 2 && args(1) == "decoded"),
        "usage: PmpLifetimeContractMain <new-output-directory> [decoded]")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args.head)), "output directory must be new")
    ChiselStage.emitCHIRRTLFile(new PmpLifetimeContract(args.lift(1).contains("decoded")), Array("--target-dir", args.head))
}
