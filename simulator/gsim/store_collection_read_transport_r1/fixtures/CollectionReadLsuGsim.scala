package ooo
import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Component transport only. Start qualification is test-authored here; real
  * head minting is checked separately in CollectionReadBackendGsim.
  */
class CollectionReadLsuGsim(enabled: Boolean) extends Module {
    val profile = CollectionReadProfileV2.config
    val p = profile.coreParams.copy(postedCollectionReadProgress = enabled)
    val lsu = Module(new ParallelLoadStoreUnit(p,
        canonicalHandoff = profile.independentDemandAdmission && p.canonicalVirtualStoreOverlap,
        localTaggedResponseReady = p.localTaggedResponseReady,
        candidateLoadPreparation = p.pendingVirtualStoreProof && p.registeredLoadResultReady && p.localTaggedResponseReady,
        observeOrdinaryLoadCapacity = true))
    val io = IO(chiselTypeOf(lsu.io))
    io <> lsu.io
    require(io.memory.request.bits.getWidth == 184)
}
object CollectionReadLsuGsimMain extends App {
    require(args.length == 3)
    val out = java.nio.file.Path.of(args(0)); java.nio.file.Files.createDirectories(out)
    val p = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = args(1).toBoolean)
    val actual = ujson.read(CollectionReadProfileJson.json(p))
    val legacy = ujson.read(ujson.write(actual))
    require(legacy.obj.remove("postedCollectionReadProgress").contains(ujson.Bool(args(1).toBoolean)))
    val expected = ujson.read(java.nio.file.Files.readString(java.nio.file.Path.of(args(2))))
    require(legacy == expected("core"))
    require(ujson.read(CollectionReadProfileJson.json(CollectionReadProfileV2.config)) == expected("profile"))
    require(expected("geometry")("cache")("independentDemandAdmission") ==
        ujson.Bool(CollectionReadProfileV2.config.independentDemandAdmission))
    require(expected("featureFlags")("shadowEarlyProofBind") == ujson.Bool(true))
    java.nio.file.Files.writeString(out.resolve("actual-core.json"),ujson.write(actual,indent=2)+"\n")
    java.nio.file.Files.writeString(out.resolve("CollectionReadLsuGsim.fir"),
        ChiselStage.emitCHIRRTL(new CollectionReadLsuGsim(args(1).toBoolean)))
}
