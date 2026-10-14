package ooo
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files,Paths}
/** New R6 source/classes; same complete parameter contract, no inherited qualification. */
object R6Exact73CpuMain extends App {
 require(args.length == 74)
 val p=TimingReady73Profile
 p.requireSide("on",args.drop(1).toSeq,p.on)
 val out=Paths.get(args(0)).toAbsolutePath
 require(!Files.exists(out),"fresh R6 CPU output required")
 p.write("on",out)
 ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(p.on,verifyConfiguration=true),Array("--target-dir",out.toString))
 MatchingFabricAudit.write(out.toString)
 p.requireFabric("on",out)
 println("PASS_R6_EXACT73_ACTUAL_CPU core=177 profile=94 options=73 new_source_qualification_pending")
}
