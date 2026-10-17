package ooo
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
object StoreOffMain extends App {
    require(args.length == 2)
    val p = CollectionReadProfileV2.config.coreParams
    require(!p.postedCollectionReadProgress)
    val document = ujson.read(CollectionReadProfileJson.json(p))
    require(document.obj.remove("postedCollectionReadProgress").contains(ujson.Bool(false)))
    val expected = ujson.read(java.nio.file.Files.readString(java.nio.file.Path.of(args(1))))
    require(document == expected("core"))
    require(ujson.read(CollectionReadProfileJson.json(CollectionReadProfileV2.config)) == expected("profile"))
    java.nio.file.Files.writeString(java.nio.file.Path.of(args(0)).resolve("StoreBuffer.fir"),
        ChiselStage.emitCHIRRTL(new StoreBuffer(p)))
}
