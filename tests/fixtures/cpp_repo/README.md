# cpp_repo

A minimal modern C++17 HTTP API fixture used by the `code-context` eval
suite. It is **not** intended to compile or run — it only needs to be
parseable by tree-sitter so the chunker can extract semantically
meaningful units (functions, classes, structs, namespaces).

## Stack

- C++17 / 20 idioms (`std::optional`, `std::string_view`, `[[nodiscard]]`,
  structured bindings, smart pointers).
- `cpp-httplib`-style HTTP server (`httplib::Server`) — headers are
  stubbed and the routing surface is hand-written.
- `nlohmann::json` for JSON serialization.
- `sqlite3` C API for persistence.
- `jwt-cpp` for JWT issuance/validation (stubbed).
- `bcrypt`-style password hashing (stubbed).

## Layout

```
include/api/        — public headers (.hpp), declarations
src/                — implementations (.cpp), with handlers/, services/,
                      repository/, middleware/ subdirs mirroring the
                      include tree
tests/              — Catch2-style test sources (also non-compiling)
CMakeLists.txt      — declarative target listing
```

Each handler / service / repository has both a `.hpp` (declaration) and
a `.cpp` (implementation), so the chunker sees the same concept twice
and the eval queries can pin to either side.
