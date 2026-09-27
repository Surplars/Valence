package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.{TwoBankTileLinkRouter, TwoMasterTileLinkArbiter}

class TileLinkArbiterGsim extends Module {
    val upstream = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 2)
    val io = IO(new Bundle {
        val master0 = Flipped(new TLBundle(upstream))
        val master1 = Flipped(new TLBundle(upstream))
        val manager = new TLBundle(upstream.copy(sourceBits = 3))
    })
    val arbiter = Module(new TwoMasterTileLinkArbiter(upstream))
    io.master0 <> arbiter.io.masters(0)
    io.master1 <> arbiter.io.masters(1)
    io.manager <> arbiter.io.manager
}

object TileLinkArbiterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkArbiterGsim, Array("--target-dir", args.head))
}

object TileLinkArbiterRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TwoMasterTileLinkArbiter,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}

class TileLinkArbiterRouterComposition extends Module {
    val upstream = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val downstream = upstream.copy(sourceBits = upstream.sourceBits + 1)
    val io = IO(new Bundle {
        val masters = Vec(2, Flipped(new TLBundle(upstream)))
        val banks = Vec(2, new TLBundle(downstream))
    })
    val arbiter = Module(new TwoMasterTileLinkArbiter(upstream))
    val router = Module(new TwoBankTileLinkRouter(downstream))
    for (i <- 0 until 2) {
        io.masters(i) <> arbiter.io.masters(i)
        io.banks(i) <> router.io.banks(i)
    }
    arbiter.io.manager <> router.io.host
}

class TileLinkArbiterParamsSpec extends AnyFunSuite {
    test("two masters compose with the two-bank router using expanded source IDs") {
        val rtl = ChiselStage.emitCHIRRTL(new TileLinkArbiterRouterComposition)
        assert(rtl.contains("module TwoMasterTileLinkArbiter"))
        assert(rtl.contains("module TwoBankTileLinkRouter"))
    }
}
