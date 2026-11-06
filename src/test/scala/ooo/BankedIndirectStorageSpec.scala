package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class BankedIndirectStorageSpec extends AnyFunSuite {
    private val p = OooParams(indirectTargetEntries = 16, compressedInstructions = true,
        registeredPredictionTraining = true)
    private def normalize(fir: String): String = fir.replaceAll(" @\\[[^\\]]*\\]", "")
    private def emit(params: OooParams, banked: Boolean): String =
        ChiselStage.emitCHIRRTL(new IndirectTargetPredictor(params, bankedStorage = banked))

    test("omitted storage option is the unchanged register implementation") {
        assert(normalize(ChiselStage.emitCHIRRTL(new IndirectTargetPredictor(p))) == normalize(emit(p, false)))
        assert(!emit(p, false).contains("cmem "))
    }

    test("banked storage has four single-writer payload memories with the same interface") {
        val off = emit(p, false)
        val on = emit(p, true)
        def ports(fir: String): Seq[String] = fir.linesIterator.map(_.trim)
            .filter(line => line.startsWith("input ") || line.startsWith("output ")).toSeq
        assert(ports(off) == ports(on))
        for (name <- Seq("tagBank0", "targetBank0", "tagBank1", "targetBank1"))
            assert(on.contains(s"cmem $name : UInt<64>[16]"))
    }

    test("banked storage rejects unqualified geometry and training while registers remain available") {
        for (invalid <- Seq(p.copy(indirectTargetEntries = 32), p.copy(indirectTargetEntries = 64),
            p.copy(renameWidth = 4), p.copy(commitWidth = 4), p.copy(compressedInstructions = false),
            p.copy(registeredPredictionTraining = false))) {
            intercept[IllegalArgumentException] { emit(invalid, true) }
            emit(invalid, false)
        }
        intercept[IllegalArgumentException] { emit(p.copy(indirectTargetEntries = 0), true) }
    }

    test("the core cannot silently ignore banked storage when the indirect table is absent") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new IntegerCore(OooParams(), bankedIndirectStorage = true))
        }
    }
}
