package ooo

import soc.core.ooo._

/** Reads actual constructor objects and optional interfaces, without production taps or state. */
object TimingClosureActualAudit {
    private def fields(instance: AnyRef): Seq[java.lang.reflect.Field] = {
        val result = scala.collection.mutable.ArrayBuffer.empty[java.lang.reflect.Field]
        var declaring: Class[_] = instance.getClass
        while (declaring != null) {
            result ++= declaring.getDeclaredFields.filter(f => !java.lang.reflect.Modifier.isStatic(f.getModifiers))
            declaring = declaring.getSuperclass
        }
        result.toSeq
    }
    private def params(instance: AnyRef): OooParams = {
        val found = fields(instance).filter(_.getType == classOf[OooParams])
        require(found.size == 1, "actual constructor OooParams absent/ambiguous: " + instance.getClass.getName)
        found.head.setAccessible(true)
        found.head.get(instance).asInstanceOf[OooParams]
    }
    private def checkedRegister(adapter: DataTranslationAdapter): Boolean = {
        val found = fields(adapter).filter(_.getName == "registerCheckedRequests")
        require(found.size == 1 && found.head.getType == java.lang.Boolean.TYPE)
        found.head.setAccessible(true)
        found.head.getBoolean(adapter)
    }
    private def modules(backend: IntegerBackend): Seq[chisel3.experimental.BaseModule] = {
        val ids = classOf[chisel3.experimental.BaseModule].getMethod("getIds").invoke(backend)
            .asInstanceOf[scala.collection.Iterable[_]]
        ids.collect { case m: chisel3.experimental.BaseModule => m }.toSeq
    }
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        ProfileAbi77.requireLive(expected)
        PlacedTimingProfileBridge.requireShape(expected)
        val core = platform.core.core.core
        val backend = core.backend
        val p = expected.coreParams
        require(p.productArity == 178 && expected.productArity == 95)
        require(expected.registeredLoadResultReady == p.registeredLoadResultReady &&
            expected.frozenStoreCheckedFlow == p.frozenStoreCheckedFlow)
        require(core.p == p && backend.p == p && backend.ledger.p == p)
        val lsu = backend.lsu
        require(params(lsu) == p && lsu.slots.size == 4 && lsu.slots.forall(params(_) == p))
        val owner = backend.ownerReady.getOrElse(throw new IllegalArgumentException("owner mirror absent"))
        require(params(owner) == p && owner.ready1.size == 16 && owner.ready2.size == 16)
        val allocation = modules(backend).collect { case m: FaultAwareAllocationReady => m }
        require(allocation.size == 1 && allocation.forall(params(_) == p))
        val enabled = p.registeredLoadResultReady
        require(backend.heldLoadDestinations.nonEmpty == enabled &&
            lsu.io.loadResultPublish.nonEmpty == enabled && lsu.io.heldLoadValue.nonEmpty == enabled &&
            lsu.slots.forall(_.io.successfulLoadResultCapture.nonEmpty == enabled))
        require(owner.io.executionClass.nonEmpty == enabled && owner.io.allocationExecutionClass.nonEmpty == enabled &&
            owner.io.heldLoads.nonEmpty == enabled && owner.io.publishedLoads.nonEmpty == enabled)
        allocation.foreach { a =>
            require(a.io.allocationExecutionClass.nonEmpty == enabled && a.io.heldLoads.nonEmpty == enabled &&
                a.io.publishedLoads.nonEmpty == enabled)
        }
        lsu.io.loadResultPublish.foreach { slots =>
            require(slots.size == 4 && slots.forall(_.bits.getWidth == p.physBits))
        }
        lsu.io.heldLoadValue.foreach { slots =>
            require(slots.size == 4 && slots.forall(x => x.bits.destination.getWidth == p.physBits &&
                x.bits.data.getWidth == 64))
        }
        val adapter = platform.core.observationTranslation.getOrElse(
            throw new IllegalArgumentException("actual data translation adapter absent"))
        require(params(adapter) == p && checkedRegister(adapter) && adapter.registerCanonicalStoreEvent &&
            adapter.queuedHeadSelection == expected.queuedHeadSelection,
            "actual complete adapter/checked/canonical constructor differs")
        require(p.registeredCanonicalStoreEvent && p.registeredTranslationHeads &&
            p.canonicalVirtualStoreOverlap && p.pendingVirtualStoreProof && p.frozenStoreProofTransport)
        Map("schema" -> "actual-timing-closure-v1", "scope" -> "actual-constructor-only",
            "coreFields" -> p.productArity, "profileFields" -> expected.productArity,
            "registeredLoadResultReady" -> params(lsu).registeredLoadResultReady,
            "frozenStoreCheckedFlow" -> params(adapter).frozenStoreCheckedFlow,
            "core" -> core.p, "backend" -> backend.p, "ledger" -> backend.ledger.p,
            "lsu" -> params(lsu), "lsuSlots" -> lsu.slots.map(params),
            "ownerReady" -> params(owner), "allocationReady" -> allocation.map(params),
            "translation" -> params(adapter), "ownerReadyRows" -> owner.ready1.size,
            "allocationReadyInstances" -> allocation.size,
            "loadPublishSlots" -> lsu.io.loadResultPublish.map(_.size).getOrElse(0),
            "heldValueSlots" -> lsu.io.heldLoadValue.map(_.size).getOrElse(0),
            "successfulLoadCaptureSlots" -> lsu.slots.count(_.io.successfulLoadResultCapture.nonEmpty),
            "ownerExecutionClassInputs" -> owner.io.executionClass.map(_.size).getOrElse(0),
            "allocationExecutionClassInputs" -> owner.io.allocationExecutionClass.map(_.size).getOrElse(0),
            "checkedRequestsRegistered" -> checkedRegister(adapter),
            "canonicalEventRegistered" -> adapter.registerCanonicalStoreEvent,
            "queuedHeadSelection" -> adapter.queuedHeadSelection,
            "dynamicQualification" -> false, "physicalQualification" -> false)
    }
}
