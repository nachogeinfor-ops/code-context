"""Tree-sitter S-expression queries: one per supported language.

Each query captures the AST nodes we want to emit as chunks. A node is
"chunk-worthy" when it represents a complete top-level semantic unit:

- Python: function_definition, class_definition.
- JavaScript / TypeScript: function_declaration, class_declaration,
  method_definition, arrow function assigned at module scope.
- Go: function_declaration, method_declaration, type_declaration.
- Rust: function_item, struct_item, enum_item, impl_item, trait_item.
- C#: method_declaration, constructor_declaration, class_declaration,
  interface_declaration, struct_declaration, record_declaration,
  enum_declaration.

Smaller nodes (assignments, single statements) are NOT captured — they
are rolled up into a synthetic "module-prelude" chunk in the chunker
(future work; v0.2.0 simply skips them).
"""

from __future__ import annotations

PYTHON = """
(function_definition) @chunk
(class_definition) @chunk
"""

JAVASCRIPT = """
(function_declaration) @chunk
(class_declaration) @chunk
(method_definition) @chunk
(variable_declarator
  name: (identifier)
  value: (arrow_function)) @chunk
"""

# TypeScript inherits all JS captures plus interface and type alias.
TYPESCRIPT = (
    JAVASCRIPT
    + """
(interface_declaration) @chunk
(type_alias_declaration) @chunk
"""
)

GO = """
(function_declaration) @chunk
(method_declaration) @chunk
(type_declaration) @chunk
"""

RUST = """
(function_item) @chunk
(struct_item) @chunk
(enum_item) @chunk
(impl_item) @chunk
(trait_item) @chunk
"""

CSHARP = """
(method_declaration) @chunk
(constructor_declaration) @chunk
(class_declaration) @chunk
(interface_declaration) @chunk
(struct_declaration) @chunk
(record_declaration) @chunk
(enum_declaration) @chunk
"""

QUERIES_BY_LANG: dict[str, str] = {
    "python": PYTHON,
    "javascript": JAVASCRIPT,
    "typescript": TYPESCRIPT,
    "go": GO,
    "rust": RUST,
    "csharp": CSHARP,
}
