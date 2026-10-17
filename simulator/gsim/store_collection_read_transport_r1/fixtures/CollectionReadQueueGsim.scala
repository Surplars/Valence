package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Transport-only boundary: the host supplies arbitrary sidecars to exercise bit
  * placement. This wrapper does not claim actual ROB-head authority.
  */
class CollectionReadQueueGsim(enabled: Boolean, projected: Boolean) extends Module {
    val p = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = enabled)
    val shape = new RegisteredRequestEntry(p)
    val io = IO(new Bundle {
        val enqValid = Input(Bool())
        val enqReady = Output(Bool())
        val enqBits = Input(UInt(shape.getWidth.W))
        val deqValid = Output(Bool())
        val deqReady = Input(Bool())
        val deqBits = Output(UInt(shape.getWidth.W))
        val count = Output(UInt(log2Ceil(p.memoryEntries + 1).W))
        val requestBits = Output(UInt(16.W))
        val recordBits = Output(UInt(16.W))
    })
    val queue = Module(new RegisteredRequestQueue(p, projectedHead = projected))
    val in = io.enqBits.asTypeOf(new RegisteredRequestEntry(p))
    val out = Wire(new RegisteredRequestEntry(p))
    queue.io.enq.valid := io.enqValid
    queue.io.enq.bits := in.request
    queue.proofIn.foreach(_ := in.postedProof.get)
    queue.canonicalOriginIn.foreach(_ := in.canonicalStoreOrigin.get)
    queue.frozenProofIn.foreach(_ := in.frozenStoreProof.get)
    queue.collectionReadIn.foreach(_ := in.collectionHeadRead.get)
    io.enqReady := queue.io.enq.ready
    queue.io.deq.ready := io.deqReady
    io.deqValid := queue.io.deq.valid
    out.request := queue.io.deq.bits
    out.postedProof.foreach(_ := queue.proofOut.get)
    out.canonicalStoreOrigin.foreach(_ := queue.canonicalOriginOut.get)
    out.frozenStoreProof.foreach(_ := queue.frozenProofOut.get)
    out.collectionHeadRead.foreach(_ := queue.collectionReadOut.get)
    io.deqBits := out.asUInt
    io.count := queue.io.count
    io.requestBits := in.request.getWidth.U
    io.recordBits := shape.getWidth.U
    require(in.request.getWidth == 181 + p.dataReturnHandleBits,
        "external DataRequest remains the exact original field sum plus existing handle bits")
    require(shape.getWidth == in.request.getWidth + in.postedProof.toSeq.map(_.getWidth).sum +
        in.canonicalStoreOrigin.toSeq.map(_.getWidth).sum + in.frozenStoreProof.toSeq.map(_.getWidth).sum +
        (if (enabled) 1 else 0), "explicit internal record schema contains only declared sidecars")
}

object CollectionReadQueueGsimMain extends App {
    require(args.length == 4)
    val output = java.nio.file.Path.of(args(0))
    java.nio.file.Files.createDirectories(output)
    val actual = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = args(1).toBoolean)
    val document = ujson.read(CollectionReadProfileJson.json(actual))
    java.nio.file.Files.writeString(output.resolve("actual-core.json"), ujson.write(document, indent = 2) + "\n")
    val legacy = ujson.read(ujson.write(document))
    require(legacy.obj.remove("postedCollectionReadProgress").contains(ujson.Bool(args(1).toBoolean)))
    val expected = ujson.read(java.nio.file.Files.readString(java.nio.file.Path.of(args(3))))
    require(ujson.read(CollectionReadProfileJson.json(CollectionReadProfileV2.config)) == expected("profile"),
        "all 96 original profile fields must match the selected configuration")
    require(legacy == expected("core"), "all original core fields must match qualified source profile")
    java.nio.file.Files.writeString(output.resolve("CollectionReadQueueGsim.fir"),
        ChiselStage.emitCHIRRTL(new CollectionReadQueueGsim(args(1).toBoolean, args(2).toBoolean)))
}

object CollectionReadProfileJson {
    private def quote(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    def json(value: Any): String = value match {
        case null => "null"
        case text: String => quote(text)
        case bool: Boolean => bool.toString
        case number: BigInt => number.toString
        case number: Int => number.toString
        case number: Long => number.toString
        case option: Option[_] => option.map(json).getOrElse("null")
        case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
            .map { case (name, item) => quote(name.toString) + ":" + json(item) }.mkString("{", ",", "}")
        case items: Seq[_] => items.map(json).mkString("[", ",", "]")
        case product: Product => json(product.productElementNames.zip(product.productIterator).toMap)
        case other => throw new IllegalArgumentException("unserialized profile value: " + other.getClass.getName)
    }
}
