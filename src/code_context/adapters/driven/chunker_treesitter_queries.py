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

Each query also captures the symbol's identifier as ``@name`` so callers
that want to mine ``SymbolDef`` objects (extract_definitions) can pair
the chunk node with its name child. Existing chunk-only consumers that
filter ``captures["chunk"]`` continue to work unchanged.

Smaller nodes (assignments, single statements) are NOT captured — they
are rolled up into a synthetic "module-prelude" chunk in the chunker
(future work; v0.2.0 simply skips them).
"""

from __future__ import annotations

PYTHON = """
(function_definition
  name: (identifier) @name) @chunk
(class_definition
  name: (identifier) @name) @chunk
"""

JAVASCRIPT = """
(function_declaration
  name: (identifier) @name) @chunk
(class_declaration
  name: (identifier) @name) @chunk
(method_definition
  name: (property_identifier) @name) @chunk
(variable_declarator
  name: (identifier) @name
  value: (arrow_function)) @chunk
"""

# TypeScript shares JS's overall shape but the grammar names the class with
# (type_identifier) rather than (identifier), so we cannot reuse the JS
# string verbatim — the TS class_declaration pattern needs its own form.
TYPESCRIPT = """
(function_declaration
  name: (identifier) @name) @chunk
(class_declaration
  name: (type_identifier) @name) @chunk
(method_definition
  name: (property_identifier) @name) @chunk
(variable_declarator
  name: (identifier) @name
  value: (arrow_function)) @chunk
(interface_declaration
  name: (type_identifier) @name) @chunk
(type_alias_declaration
  name: (type_identifier) @name) @chunk
"""

GO = """
(function_declaration
  name: (identifier) @name) @chunk
(method_declaration
  name: (field_identifier) @name) @chunk
(type_declaration
  (type_spec name: (type_identifier) @name)) @chunk
"""

RUST = """
(function_item
  name: (identifier) @name) @chunk
(struct_item
  name: (type_identifier) @name) @chunk
(enum_item
  name: (type_identifier) @name) @chunk
(impl_item
  type: (type_identifier) @name) @chunk
(trait_item
  name: (type_identifier) @name) @chunk
"""

CSHARP = """
(method_declaration
  name: (identifier) @name) @chunk
(constructor_declaration
  name: (identifier) @name) @chunk
(class_declaration
  name: (identifier) @name) @chunk
(interface_declaration
  name: (identifier) @name) @chunk
(struct_declaration
  name: (identifier) @name) @chunk
(record_declaration
  name: (identifier) @name) @chunk
(enum_declaration
  name: (identifier) @name) @chunk
"""

QUERIES_BY_LANG: dict[str, str] = {
    "python": PYTHON,
    "javascript": JAVASCRIPT,
    "typescript": TYPESCRIPT,
    "go": GO,
    "rust": RUST,
    "csharp": CSHARP,
}
