package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import scala.collection.immutable.ListMap

class IssuePayloadTestWrite extends Bundle {
    val index = UInt(4.W)
    val data = new ImmutableIssuePayload
}
class IssuePayloadTestAddress extends Bundle {
    val index = UInt(4.W)
    val enable = Bool()
}
class IssuePayloadWritePorts extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until 2).map(lane =>
        s"lane$lane" -> Valid(new IssuePayloadTestWrite)): _*)
    def at(lane: Int): ValidIO[IssuePayloadTestWrite] =
        elements(s"lane$lane").asInstanceOf[ValidIO[IssuePayloadTestWrite]]
}
class IssuePayloadAddressPorts extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until 8).map(lane =>
        s"lane$lane" -> new IssuePayloadTestAddress): _*)
    def at(lane: Int): IssuePayloadTestAddress = elements(s"lane$lane").asInstanceOf[IssuePayloadTestAddress]
}
class IssuePayloadDataPorts extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until 8).map(lane =>
        s"lane$lane" -> new ImmutableIssuePayload): _*)
    def at(lane: Int): ImmutableIssuePayload = elements(s"lane$lane").asInstanceOf[ImmutableIssuePayload]
}
object BankedIssuePayloadTestConfig {
    val fields: Seq[Set[String]] = Seq(ImmutableIssuePayload.head, Set("immediate"), Set("immediate"),
        Set("pc"), Set("pc"), ImmutableIssuePayload.execution, ImmutableIssuePayload.execution, Set("pc"))
}
class BankedIssuePayloadGsim extends Module {
    val io = IO(new Bundle {
        val write = Input(new IssuePayloadWritePorts)
        val address = Input(new IssuePayloadAddressPorts)
        val data = Output(new IssuePayloadDataPorts)
    })
    val storage = Module(new BankedIssuePayload(16, BankedIssuePayloadTestConfig.fields))
    for (lane <- 0 until 2) {
        storage.io.write(lane).valid := io.write.at(lane).valid
        storage.io.write(lane).bits.index := io.write.at(lane).bits.index
        storage.io.write(lane).bits.data := io.write.at(lane).bits.data
    }
    for (lane <- 0 until 8) {
        storage.io.address(lane) := io.address.at(lane).index
        storage.io.enable(lane) := io.address.at(lane).enable
        io.data.at(lane) := storage.io.data(lane)
    }
}
object BankedIssuePayloadGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new BankedIssuePayloadGsim, Array("--target-dir", args.head))
}
