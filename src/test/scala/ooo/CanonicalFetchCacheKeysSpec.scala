package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Elaboration guards only; arithmetic and ownership use the independent GSIM fixtures. */
class CanonicalFetchCacheKeysSpec extends AnyFunSuite {
    private def emit(enabled: Boolean = true, sets: Int = 16, slots: Int = 2,
        compressed: Boolean = true, width: Int = 2, parallel: Boolean = true,
        window: Boolean = true, aligned: Boolean = true, compact: Boolean = false): String =
        ChiselStage.emitCHIRRTL(new SynchronousFetch(compressed = compressed, cacheSets = sets,
            fetchWidth = width, parallelFetchTagLookup = parallel, registeredWindow = window,
            alignedFetchPmp = aligned, transactionSlots = slots, compactCacheKeys = compact,
            canonicalFetchCacheKeys = enabled))

    test("canonical helper exists only in the explicitly selected qualified topology") {
        val candidate = emit()
        assert(candidate.contains("module CanonicalFetchCacheKeys"))
        assert(!emit(enabled = false).contains("module CanonicalFetchCacheKeys"))
        assert(!ChiselStage.emitCHIRRTL(new SynchronousFetch).contains("module CanonicalFetchCacheKeys"))
        // The older compact-key path remains independently elaboratable, without
        // opting into the two-owner canonical helper or changing its constraints.
        assert(emit(enabled = false, slots = 1, compact = true).contains("module CompactFetchCacheKeys"))
    }

    test("canonical keys reject unsupported domains instead of silently truncating or widening") {
        val bad: Seq[() => String] = Seq(() => emit(sets = 8), () => emit(sets = 32),
            () => emit(slots = 1), () => emit(compressed = false), () => emit(width = 4),
            () => emit(parallel = false), () => emit(window = false), () => emit(aligned = false),
            () => emit(compact = true))
        for (f <- bad) intercept[IllegalArgumentException] { f() }
    }
}
