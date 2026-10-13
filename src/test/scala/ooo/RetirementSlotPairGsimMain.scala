package ooo
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
object RetirementSlotPairGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RetirementSlotPairGsim, Array("--target-dir", args.head))
    RetirementSlotTestProfile.writeParameters(args.head)
}
