package ooo

import _root_.circt.stage.ChiselStage

/** Local qualification switches only. Board/core profiles continue to use default-OFF production knobs. */
object TranslationHintPmpGsimMain extends App {
    require(args.length == 2 && Set("8", "16").contains(args(1)), "output directory and PMP entries 8|16")
    ChiselStage.emitCHIRRTLFile(new NextLineAuthorizationGsim(storePrefetch = true,
        hintTimingPair = true, pmpEntries = args(1).toInt), Array("--target-dir", args.head))
}

object TranslationHintCanonicalGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CanonicalStoreAdapterGsim(translationHitFlow = true, hintTimingPair = true),
        Array("--target-dir", args.head))
}

object TranslationHintPrecheckedGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new VirtualLoadPrecheckGsim(true, identityFlow = true,
        hintTimingPair = true, precheckedFlow = true, physicalIngressFlow = true), Array("--target-dir", args.head))
}

object TranslationHintFrozenGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TranslatedFrozenProofGsim(hintTimingPair = true), Array("--target-dir", args.head))
}
