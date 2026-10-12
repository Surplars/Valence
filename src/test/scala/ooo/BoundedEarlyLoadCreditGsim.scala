package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Only legal component IO is driven. The host owns the independent obligation ledger. */
class BoundedEarlyLoadCreditGsim(capacity: Int) extends Module {
    val p = PendingStoreProofFixture.params().copy(pendingStoreEarlyLoadCredits = capacity)
    val io = IO(new Bundle {
        val reserve = Input(Valid(new RobToken(p)))
        val consume = Input(Valid(new RobToken(p)))
        val cancel = Input(Valid(new RobToken(p)))
        val live0 = Input(Valid(new RobToken(p)))
        val live1 = Input(Valid(new RobToken(p)))
        val live2 = Input(Valid(new RobToken(p)))
        val live3 = Input(Valid(new RobToken(p)))
        val available = Output(Bool())
        val reserved = Output(UInt(2.W))
        val active = Output(UInt(2.W))
        val owner0 = Output(new RobToken(p))
        val owner1 = Output(new RobToken(p))
    })
    val credit = Module(new PendingStoreEarlyLoadCredit(p))
    credit.io.reserve := io.reserve
    credit.io.consume := io.consume
    credit.io.cancelReservation := io.cancel
    for ((live, i) <- Seq(io.live0, io.live1, io.live2, io.live3).zipWithIndex) {
        credit.io.liveOwners(i) := live
    }
    io.available := credit.io.available
    io.reserved := credit.io.reserved.asUInt
    io.active := credit.io.active.asUInt
    io.owner0 := credit.io.owner(0)
    io.owner1 := (if (capacity == 2) credit.io.owner(1) else 0.U.asTypeOf(io.owner1))
}

object BoundedEarlyLoadCreditGsimMain extends App {
    require(args.length == 2 && Set("1", "2").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new BoundedEarlyLoadCreditGsim(args(1).toInt),
        Array("--target-dir", args.head))
}
