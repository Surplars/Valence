package soc.core.ooo
import chisel3._
import chisel3.util._
import hardfloat._
import _root_.circt.stage.ChiselStage
class FpConvertGsim extends Module {
 val io = IO(new Bundle {
  val bits = Input(UInt(64.W));val double = Input(Bool());val signed = Input(Bool());val rm = Input(UInt(3.W))
  val narrow = Output(UInt(64.W));val wide = Output(UInt(64.W));val nf = Output(UInt(3.W));val wf = Output(UInt(3.W))
  val referenceNarrow = Output(UInt(64.W));val referenceWide = Output(UInt(64.W));val rnf = Output(UInt(3.W));val rwf = Output(UInt(3.W))
 })
 val outs=Seq(false,true).map { d =>
  val e=if(d)11 else 8;val s=if(d)53 else 24
  val rec=recFNFromFN(e,s,if(d)io.bits else io.bits(31,0))
  val shared=Module(new FloatingPointToIntegerShared(e,s))
  shared.io.in:=rec;shared.io.signedOut:=io.signed;shared.io.roundingMode:=io.rm
  val r32=Module(new RecFNToIN(e,s,32));val r64=Module(new RecFNToIN(e,s,64))
  for(u<-Seq(r32,r64)){u.io.in:=rec;u.io.signedOut:=io.signed;u.io.roundingMode:=io.rm}
  (Cat(Fill(32,shared.io.out32(31)),shared.io.out32),shared.io.out64,shared.io.flags32,shared.io.flags64,
   Cat(Fill(32,r32.io.out(31)),r32.io.out),r64.io.out,r32.io.intExceptionFlags,r64.io.intExceptionFlags)
 }
 val a=outs(0);val b=outs(1)
 io.narrow:=Mux(io.double,b._1,a._1);io.wide:=Mux(io.double,b._2,a._2);io.nf:=Mux(io.double,b._3,a._3);io.wf:=Mux(io.double,b._4,a._4)
 io.referenceNarrow:=Mux(io.double,b._5,a._5);io.referenceWide:=Mux(io.double,b._6,a._6);io.rnf:=Mux(io.double,b._7,a._7);io.rwf:=Mux(io.double,b._8,a._8)
}
object FpConvertGsimMain extends App {
 ChiselStage.emitCHIRRTLFile(new FpConvertGsim,Array("--target-dir",args(0)))
}
