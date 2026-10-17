#!/usr/bin/env python3
"""Emit mechanical scalar GSIM access only; generation is separately gated."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from ports import INPUTS, OUTPUTS, method


def emit_driver(destination):
    setter_lines = []
    for n in INPUTS:
        if n.startswith(('pmpCfg.', 'pmpAddr.')):
            array, index = n.split('.')
            assignment = array + '[' + index + '] = v;'
        else:
            assignment = 'd.' + method('set_', n) + '(v);'
        setter_lines.append('    setters.emplace("' + n + '", [&](uint64_t v) { ' + assignment + ' });')
    setters = '\n'.join(setter_lines)
    getters = '\n'.join('      std::cout << ",\\"' + n + '\\":" << uint64_t(d.' +
                        method('get_', n) + '());' for n in OUTPUTS)
    source = r'''#include "CollectionReadTranslationGsim.h"
#include <cstdint>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
int main() {
  try {
    SCollectionReadTranslationGsim d;
    uint8_t pmpCfg[16] = {};
    uint64_t pmpAddr[16] = {};
    std::unordered_map<std::string, std::function<void(uint64_t)>> setters;
SETTERS
    for (auto& [name, set] : setters) { (void)name; set(0); }
    std::string line; unsigned cycle = 0;
    while (std::getline(std::cin, line)) {
      if (line == "quit") break;
      if (++cycle > 512) throw std::runtime_error("narrow adapter cycle budget exceeded");
      std::unordered_set<std::string> assigned;
      std::istringstream input(line); std::string item;
      while (input >> item) {
        const auto equal = item.find('=');
        if (equal == std::string::npos) throw std::runtime_error("malformed driver input");
        const auto name = item.substr(0, equal);
        if (!setters.count(name)) throw std::runtime_error("unknown driver input: " + name);
        if (!assigned.insert(name).second) throw std::runtime_error("duplicate driver input: " + name);
        size_t consumed = 0; const auto text = item.substr(equal + 1);
        if (text.empty() || text[0] == '-') throw std::runtime_error("unsigned scalar required");
        const auto value = std::stoull(text, &consumed, 0);
        if (consumed != text.size()) throw std::runtime_error("trailing input data");
        setters.at(name)(value);
      }
      if (assigned.size() != setters.size()) throw std::runtime_error("incomplete scalar frame");
      d.set_io$$pmpCfg(pmpCfg);
      d.set_io$$pmpAddr(pmpAddr);
      d.step();
      std::cout << "{\"cycle\":" << cycle;
GETTERS
      std::cout << "}\n" << std::flush;
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "CHECKED_TRANSLATION_DRIVER_FAIL " << error.what() << "\n";
    return 1;
  }
}
'''.replace('SETTERS', setters).replace('GETTERS', getters)
    destination = Path(destination)
    if destination.exists():
        raise RuntimeError('PRESERVE_EXISTING_DRIVER: ' + str(destination))
    destination.write_text(source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    emit_driver(parser.parse_args().destination)
