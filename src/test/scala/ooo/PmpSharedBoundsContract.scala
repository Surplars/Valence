package ooo
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
class PmpSharedBoundsContract(line: Boolean) extends Module {
 val io = IO(new Bundle { val address=Input(UInt(64.W)); val size=Input(UInt(3.W)); val denied=Output(Bool()) })
 val checker = Module(new PmpChecker(16,naturalAlignedAccess = !line,alignedLineAccess=line,sharedAlignedBounds=true))
 checker.io.state := 0.U.asTypeOf(new PmpState)
 checker.io.address := io.address; checker.io.size := io.size
 checker.io.privilege := 1.U; checker.io.access := PmpAccess.read
 io.denied := checker.io.denied
}
object PmpSharedBoundsContractMain extends App {
 ChiselStage.emitCHIRRTLFile(new PmpSharedBoundsContract(args(1)=="line"),Array("--target-dir",args.head))
}
