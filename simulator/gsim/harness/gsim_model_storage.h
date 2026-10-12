#pragma once
#include <array>
#include <cstddef>
#include <new>

// Establish deterministic simulator storage BEFORE the object's lifetime.
// The public constructor still runs. Callers drive real reset normally; this
// helper grants no hardware initialization or invalid-payload authorization.
template <class Model> class GsimModelStorage {
    alignas(Model) std::array<std::byte, sizeof(Model)> bytes{};
    Model* object;
public:
    GsimModelStorage() : object(::new (static_cast<void*>(bytes.data())) Model()) {}
    ~GsimModelStorage() { object->~Model(); }
    GsimModelStorage(const GsimModelStorage&) = delete;
    GsimModelStorage& operator=(const GsimModelStorage&) = delete;
    Model& get() { return *object; }
};
