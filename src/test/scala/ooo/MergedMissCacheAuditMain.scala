package ooo
import _root_.circt.stage.ChiselStage
import chisel3.experimental.BaseModule
import soc.core.ooo._
import java.nio.file.{Files, Paths}
object MergedMissCacheAuditMain extends App {
  def descendants(m: BaseModule): Seq[BaseModule] = {
    val c = classOf[BaseModule].getMethod("getIds").invoke(m).asInstanceOf[scala.collection.Iterable[_]]
      .collect { case x: BaseModule => x }.toSeq
    m +: c.flatMap(descendants)
  }
  require(args.length == 3 && Set("gsim", "native").contains(args(1)) && Set("0", "64").contains(args(2)),
    "usage: fresh-output-directory gsim|native 0|64")
  val out = Paths.get(args(0)); require(!Files.exists(out)); Files.createDirectories(out)
  val results = ujson.Arr()
  for ((translation, capacity) <- Seq((false,32),(false,64),(false,128),(true,16),(false,16))) {
    var rejected = false
    try { ChiselStage.emitCHIRRTL(new MachinePlatform(translationService=translation,dataTlbMissCacheEntries=capacity)) }
    catch { case e: IllegalArgumentException =>
      require(e.getMessage.contains(if (capacity == 16) "entries must be" else "requires translationService")); rejected=true }
    require(rejected)
    results.value += ujson.Obj("guardTranslation"->translation,"guardCapacity"->capacity,"rejected"->true)
  }
  for (native <- Seq(args(1) == "native"); capacity <- Seq(args(2).toInt)) {
    var top: BaseModule = null
    val config = CombinedTimingRepairR1Profile.config(true)
    val fir = ChiselStage.emitCHIRRTL {
      val d = if (native) new FpgaNextSocTop(config=config,
        debug=CombinedTimingPmpR1Profile.debug,bscanChain=CombinedTimingPmpR1Profile.bscanChain,
        sharedTwoWordFetchPmp=true,disjointEvictionStoreOverlap=true,projectedRequestHead=true,
        factorPreparedStorePool=true,proofBankControlDecoupling=true,registerNextLineDecision=true,
        registeredMemoryPreparationDescriptor=true,backendNaturalAlignedPmp=true,dataTlbMissCacheEntries=capacity)
      else FpgaNextBoardGsim.build(config,verifyConfiguration=true,sharedTwoWordFetchPmp=true,
        disjointEvictionStoreOverlap=true,proofBankControlDecoupling=true,projectedRequestHead=true,
        factorPreparedStorePool=true,combinedTimingR1Audit=true,registerNextLineDecision=true,
        registeredMemoryPreparationDescriptor=true,backendNaturalAlignedPmp=true,dataTlbMissCacheEntries=capacity)
      top=d; d
    }
    val all=descendants(top).distinct
    val services=all.collect {case x: SvTranslationService => x}
    require(services.size==2)
    val i=services.find(_.entries==8).get; val d=services.find(_.entries==16).get
    require(i.missCacheEntries==0 && d.missCacheEntries==capacity && d.loadPeek && d.writeReadReuse)
    require(i.maxLevels==3 && d.maxLevels==3)
    val early=all.flatMap { x => x.getClass.getMethods.find(_.getName=="earlyLoadPreparationDescriptor")
      .map(m => (x.getClass.getSimpleName,m.invoke(x).asInstanceOf[Boolean])) }
    require(early.exists(_._1=="IntegerBackend") && early.forall(!_._2))
    val forwarded=all.flatMap { x => x.getClass.getMethods.find(_.getName=="dataTlbMissCacheEntries")
      .map(m => (x.getClass.getSimpleName,m.invoke(x).asInstanceOf[Int])) }
    require(forwarded.exists(_._1=="MachinePlatform") && forwarded.forall(_._2==capacity))
    Files.writeString(out.resolve(s"${if(native) "native" else "gsim"}-$capacity.fir"),fir)
    results.value += ujson.Obj("native"->native,"capacity"->capacity,"I1"->i.entries,"I2"->i.missCacheEntries,
      "D1"->d.entries,"D2"->d.missCacheEntries,"earlyFalseAt"->ujson.Arr.from(early.map(_._1)),
      "capacityForwardedAt"->ujson.Arr.from(forwarded.map(_._1)))
    println(s"PASS_MERGED_PARAMETERS native=$native capacity=$capacity I8_D16=true earlyQ=false")
  }
  Files.writeString(out.resolve("results.json"),results.render(indent=2))
}
