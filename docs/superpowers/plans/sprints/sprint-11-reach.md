# Sprint 11 — Reach (v1.3.0)

> Read [`../2026-05-05-v1.1-roadmap.md`](../2026-05-05-v1.1-roadmap.md) for v1.x context. **Depends on Sprint 9** (eval gate); **independent of Sprint 10**.

## Goal

Extend tree-sitter chunking and symbol extraction to the languages that today fall through to the line chunker. Drop the v0.2 5-language list (Py/JS/TS/Go/Rust) to add **C#, Java, C++, Markdown**.

After Sprint 11, ~80% of typical mainstream codebases get AST-aligned chunks, not 50-line windows.

## Architecture

### Why these four

- **C#** — already in the docs as supported, but `chunker_treesitter.py` only registered Py/JS/TS/Go/Rust. WinServiceScheduler showed the gap: 1169 .cs files all line-chunked. Easy win.
- **Java** — third-most-asked-about ecosystem; tree-sitter-java is mature.
- **C++** — `.cpp/.hpp/.h`. Templates make it trickier; document edge cases.
- **Markdown** — chunk by heading hierarchy. Useful for repos where the README is the user's primary "what is this thing" interface; today it's line-chunked which loses heading context.

### Tree-sitter wiring (per language)

For each language, the addition has the same shape:

1. **Grammar import** — `tree-sitter-language-pack` already bundles all four. No new dependency.
2. **`chunker_treesitter.py`**: register the language → grammar mapping, plus the node-types → chunk-kind mapping:

```python
# Sprint 11 additions
"csharp": LanguageSpec(
    grammar="c_sharp",
    chunk_node_types={
        "class_declaration": "class",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "interface_declaration": "interface",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "record_declaration": "record",
        "namespace_declaration": "namespace",  # large; cap by lines
    },
    name_node="identifier",
),
"java": LanguageSpec(
    grammar="java",
    chunk_node_types={
        "class_declaration": "class",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
    },
    name_node="identifier",
),
"cpp": LanguageSpec(
    grammar="cpp",
    chunk_node_types={
        "class_specifier": "class",
        "struct_specifier": "struct",
        "function_definition": "function",
        "namespace_definition": "namespace",
        "template_declaration": "template",  # wraps function/class
    },
    # Templates wrap the actual decl; descend one more level.
    name_node="identifier",
),
"markdown": LanguageSpec(
    grammar="markdown",
    chunk_node_types={
        "atx_heading": "section",
        "setext_heading": "section",
        # Implementation note: we collect "section = heading + everything until next heading at same or higher level"
    },
    name_node=None,  # heading text is the name
),
```

3. **`extract_definitions`** for the symbol index: same per-language mapping but only for top-level declared names.

4. **Extension → language map**:

```python
_EXT_TO_LANG = {
    # existing
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".go": "go", ".rs": "rust",
    # Sprint 11
    ".cs": "csharp",
    ".java": "java",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".h": "cpp",  # treat .h as cpp; C-vs-C++ ambiguity, document
    ".md": "markdown", ".markdown": "markdown",
}
```

### Chunker version bump

`chunker_version` in metadata bumps from `dispatcher(treesitter-v2|line-50-10-v1)-v1` → `treesitter-v3|line-50-10-v1)-v1`. Triggers full reindex on first v1.3.0 startup. Same dirty_set-driven flow as v0.8 / v1.2.

### Markdown chunker quirks

Markdown's tree-sitter representation is "block-and-inline"; a section isn't a single node but "heading + following block-level nodes until next heading at the same or higher level." Implementation:

```python
def _markdown_chunks(tree, content):
    sections = []
    headings = [n for n in tree.walk() if n.type in ("atx_heading", "setext_heading")]
    for i, h in enumerate(headings):
        end_byte = headings[i + 1].start_byte if i + 1 < len(headings) else len(content)
        sections.append(Chunk(
            line_start=h.start_point[0] + 1,
            line_end=content[:end_byte].count("\n") + 1,
            snippet=content[h.start_byte:end_byte],
            ...
        ))
    return sections
```

`.md` files become section-aligned chunks, better for the "what does this part of the docs say" queries.

## Tasks

### T1 — Verify which languages are actually wired in v1.0.0

- Audit `chunker_treesitter.py`. The Sprint 1 plan said "5 languages" but verify which actually have grammars + chunk maps. Document the gap.
- Build a regression test that asserts the EXACT supported language list (so future drift breaks CI).

### T2 — Add C# tree-sitter

- Register `c_sharp` grammar in `chunker_treesitter.py`.
- Define node-type → chunk-kind map (see Architecture section).
- `extract_definitions` for C# symbols (class / method / interface / struct / enum / record / namespace).
- Unit tests with sample C# code (use snippets from `WinServiceScheduler` as fixtures).
- Integration test: chunker emits expected chunks for a `class { method1; method2 }` file.

### T3 — Add Java tree-sitter

- Same pattern as T2. Use sample Java fixtures (could pull from a mature OSS Java repo's snippets).

### T4 — Add C++ tree-sitter

- Same pattern. Edge case: templates wrap the actual decl. Test with `template <typename T> class Foo { ... }`.
- Document `.h` vs `.c++` extension classification. We treat `.h` as cpp; if it's C-only, the grammar still parses (C is a subset for our purposes).

### T5 — Add Markdown tree-sitter

- Section-based chunking implementation (see Architecture).
- `extract_definitions` extracts heading text as a "section" symbol so `find_definition("Configuration")` works on docs.
- Tests with a sample `README.md` fixture.

### T6 — Extension → language map update

- Single source of truth: `_EXT_TO_LANG`.
- `chunker_dispatcher` consults it. Tests for fall-through (unknown ext → line chunker).

### T7 — Chunker version bump

- Update the version string. Verify dirty_set forces full reindex on upgrade in a test.

### T8 — Run eval baseline

- Eval × 3 configs × 3 repos with the new chunker. Save as `v1.3.0_*.csv`.
- Compare to v1.2.0 baseline. Acceptance: no regression on the existing 35-csharp queries (note: chunks shifted, so query top-1 paths might shift one column too — re-tune queries if needed).
- New language-specific gain: re-run the C# subset and check NDCG@10 — chunks now AST-aligned, should lift hit@1 because the chunk text is denser.

### T9 — Docs update

- `docs/configuration.md`: chunker support matrix updated.
- `README.md`: 9 supported languages now (was 5).
- `CHANGELOG.md`: v1.3.0 entry calling out chunker_version bump → one-time full reindex on first v1.3 start.

### T10 — Bump + tag v1.3.0

- Standard release flow.

## Acceptance criteria

- All 4 new languages have unit tests + integration tests.
- Smoke against WinServiceScheduler: .cs files now have ~3 AST chunks per typical class file (was ~7 line-windows).
- Eval doesn't regress on combined NDCG@10; ideally lifts on the C# subset by 0.02-0.05.
- v1.3.0 published to PyPI.

## Risks

- **C++ template handling.** `template <T> class Foo` parses as `template_declaration > class_specifier`. We need to descend into the inner decl to extract the class name; otherwise the symbol DB stores "template" not "Foo". Implementation detail; tests cover.
- **`.h` ambiguity.** C-only headers parsed as C++ work fine because tree-sitter-cpp accepts C, but the symbol kind might say "function" when it's a C declaration. Acceptable.
- **Markdown chunks can be huge** (a section with no sub-headings = the rest of the doc). Cap by lines: if `section_lines > _SECTION_HARD_CAP`, fall back to line chunker for that section.
- **Chunker version bump triggers full reindex on every existing user's first v1.3 startup.** Same pattern as Sprint 6/8/10; document loudly.
- **`tree-sitter-language-pack` already bundles all 4 grammars** so no install bloat. But if a future v1.x sprint adds a language not in the pack, we'd need a new dep. Keep an eye on bundle size.
