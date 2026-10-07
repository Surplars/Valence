package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import scala.collection.immutable.ListMap

/** Scalar top-level fields avoid the pinned GSIM generator's invalid Vec input
  * setters. The actual DUT still uses its original Vec operand interfaces.
  */
class OperandScalarPorts(width: Int, count: Int) extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until count).map(i =>
        s"r$i" -> UInt(width.W)): _*)
    def at(i: Int): UInt = elements(s"r$i").asInstanceOf[UInt]
}

class PhysicalOperandsGsim(entries: Int, registers: Int, sharedDecode: Boolean = false,
                           clients: Int = 1) extends Module {
    require(entries <= 32 && registers <= 64 && (clients == 1 || clients == 3))
    val p = OooParams(robEntries = entries, physicalRegs = registers)
    val io = IO(new Bundle {
        val owner0 = Input(UInt(32.W))
        val owner1 = Input(UInt(32.W))
        val otherOwners = if (clients == 3) Some(Input(new OperandScalarPorts(32, 4))) else None
        val source1 = Input(new OperandScalarPorts(8, entries))
        val source2 = Input(new OperandScalarPorts(8, entries))
        val values = Input(new OperandScalarPorts(64, registers))
        val left0 = Output(UInt(64.W))
        val right0 = Output(UInt(64.W))
        val left1 = Output(UInt(64.W))
        val right1 = Output(UInt(64.W))
        val others = if (clients == 3) Some(Output(new OperandScalarPorts(64, 8))) else None
    })
    val source1 = VecInit((0 until entries).map(i => io.source1.at(i)(p.physBits - 1, 0)))
    val source2 = VecInit((0 until entries).map(i => io.source2.at(i)(p.physBits - 1, 0)))
    val values = VecInit((0 until registers).map(io.values.at))
    val shared = if (sharedDecode) Some(Module(new QueuedPhysicalSourceDecode(p))) else None
    shared.foreach { decode =>
        decode.io.source1 := source1
        decode.io.source2 := source2
    }
    for (client <- 0 until clients) {
        val operands = Module(new IssuePhysicalOperands(p, sharedSourceDecode = sharedDecode))
        for (lane <- 0 until 2) {
            val owner = if (client == 0) {
                if (lane == 0) io.owner0 else io.owner1
            } else io.otherOwners.get.at(2 * (client - 1) + lane)
            operands.io.owners(lane) := owner(entries - 1, 0)
        }
        operands.io.source1 := source1
        operands.io.source2 := source2
        operands.io.values := values
        shared.foreach { decode =>
            operands.io.decoded1.get := decode.io.decoded1
            operands.io.decoded2.get := decode.io.decoded2
        }
        if (client == 0) {
            io.left0 := operands.io.left(0); io.right0 := operands.io.right(0)
            io.left1 := operands.io.left(1); io.right1 := operands.io.right(1)
        } else {
            for (lane <- 0 until 2) {
                val offset = 4 * (client - 1) + 2 * lane
                io.others.get.at(offset) := operands.io.left(lane)
                io.others.get.at(offset + 1) := operands.io.right(lane)
            }
        }
    }
}
object PhysicalOperandsGsimMain extends App {
    val shared = args.lift(3).exists(_.toBoolean)
    val clients = args.lift(4).map(_.toInt).getOrElse(1)
    ChiselStage.emitCHIRRTLFile(new PhysicalOperandsGsim(args(1).toInt, args(2).toInt, shared, clients),
        Array("--target-dir", args.head))
}
