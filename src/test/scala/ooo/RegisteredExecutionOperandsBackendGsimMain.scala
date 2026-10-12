package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._

object RegisteredExecutionOperandsBackendGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile({
        val dut = new RegisteredExecutionOperandsBackendGsim(args(1) == "1")
        require(dut.backend.p == dut.p && dut.backend.ledger.p == dut.p)
        PostedBoardConfiguration.writeCore(Lane1OwnerBackendProfile.abc, args.head + "/published-abc")
        PostedBoardConfiguration.writeCore(dut.backend.p, args.head)
        dut
    }, Array("--target-dir", args.head))
}
