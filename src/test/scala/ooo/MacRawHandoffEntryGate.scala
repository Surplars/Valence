package ooo
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files,Paths}
import soc.core.ooo._
import soc.ip.clock._
object MacRawHandoffBoardGateMain extends App {
  val out=Paths.get(args(0)).toAbsolutePath
  require(!Files.exists(out)); Files.createDirectories(out)
  val config=MacRawHandoffEntry.on
  var actual: Option[Map[String,Any]]=None
  ChiselStage.emitCHIRRTLFile({
    val dut=new FpgaNextSocTop(config,bscanChain=MacRawHandoffEntry.options.find(_.startsWith("--experimental-jtag-bscan=")).map(_.split("=")(1).toInt).getOrElse(0))
    actual=Some(MacRawHandoffEntryAudit.capture(dut.board,config))
    dut
  },Array("--target-dir",out.toString))
  Files.writeString(out.resolve("actual-mac-raw-handoff.json"),PostedBoardConfiguration.json(actual.get)+"\n")
  PostedBoardConfiguration.write(config,out.resolve("configuration").toString)
  println(s"PASS_ACTUAL_FULL_BOARD_CHIRRTL profile=${config.productArity} core=${config.coreParams.productArity} handoff=true")
}
object MacRawHandoffBankGateMain extends App {
  val out=Paths.get(args(0)).toAbsolutePath
  require(!Files.exists(out)); Files.createDirectories(out)
  val on=args(1)=="on"
  val c=if(on) MacRawHandoffEntry.on else MacRawHandoffEntry.off
  val cmu=CmuParams(c.aonHz,BoardSocConfig.clockResources(c.aonHz,c.cpuHz,c.uartHz,true,c.ddrUiHz,true)
      .zipWithIndex.map {case(r,n)=>r.copy(canGate=Set(3,5,6).contains(n))},timeoutCycles=65536)
  var seen=false
  ChiselStage.emitSystemVerilogFile({
    val bank=new ManagedPeripheralBank(cmu,c.cpuHz,c.uartHz,networkDmaConfig=c.network,
      triSpeedEthernet=true,triSpeedTxFrameSlots=2,triSpeedRawClockHandoff=on)
    require(bank.triSpeedRawClockHandoff==on)
    val mac=bank.instantiatedTriSpeedMac.get
    require(mac.rawClockHandoff==on && mac.rawHandoff.isDefined==on)
    seen=true;bank
  },Array("--target-dir",out.toString),Array("--split-verilog","--strip-debug-info","--disable-all-randomization"))
  require(seen)
  Files.writeString(out.resolve("actual-bank-mac.json"),PostedBoardConfiguration.json(Map("triSpeedRawClockHandoff"->on,
    "actualBankAndMacConstructed"->true,"physicalQualification"->false))+"\n")
  println("PASS_ACTUAL_BANK_MAC_NATIVE handoff="+on)
}
