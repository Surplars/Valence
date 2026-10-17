package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Real StoreBuffer IO, including posted ownership and the optional read sidecar.
  * This component receives test-authored qualification; it does not mint ROB authority.
  */
class CollectionReadStoreGsim(enabled: Boolean) extends Module {
    val p = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = enabled)
    val buffer = Module(new StoreBuffer(p))
    val io = IO(chiselTypeOf(buffer.io))
    io <> buffer.io
    require(buffer.io.upstream.request.bits.getWidth == 184)
    require(buffer.io.memory.request.bits.getWidth == 184)
}

object CollectionReadStoreGsimMain extends App {
    require(args.length == 3)
    val output = java.nio.file.Path.of(args(0))
    java.nio.file.Files.createDirectories(output)
    val actual = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = args(1).toBoolean)
    val document = ujson.read(CollectionReadProfileJson.json(actual))
    val legacy = ujson.read(ujson.write(document))
    require(legacy.obj.remove("postedCollectionReadProgress").contains(ujson.Bool(args(1).toBoolean)))
    val expected = ujson.read(java.nio.file.Files.readString(java.nio.file.Path.of(args(2))))
    require(ujson.read(CollectionReadProfileJson.json(CollectionReadProfileV2.config)) == expected("profile"))
    require(legacy == expected("core"))
    java.nio.file.Files.writeString(output.resolve("actual-core.json"),ujson.write(document,indent=2)+"\n")
    java.nio.file.Files.writeString(output.resolve("CollectionReadStoreGsim.fir"),
        ChiselStage.emitCHIRRTL(new CollectionReadStoreGsim(args(1).toBoolean)))
}
