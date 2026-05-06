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
- Java: class_declaration, method_declaration, constructor_declaration,
  interface_declaration, enum_declaration, record_declaration.
- C++: class_specifier, struct_specifier, function_definition (top-level
  or namespace-level, not class methods), namespace_definition, and the
  outer template_declaration for templated classes/structs/functions.
  Template handling uses containment dedup: both the outer
  template_declaration and inner class_specifier/function_definition are
  captured by separate patterns; the chunker removes inner nodes that are
  fully contained within an outer @chunk. _kind_from_node descends into
  template_declaration children to determine the actual kind.

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

# Java shares C#'s overall shape (same node names for most declarations).
# The struct_declaration from C# has no Java equivalent — omitted.
JAVA = """
(class_declaration
  name: (identifier) @name) @chunk
(method_declaration
  name: (identifier) @name) @chunk
(constructor_declaration
  name: (identifier) @name) @chunk
(interface_declaration
  name: (identifier) @name) @chunk
(enum_declaration
  name: (identifier) @name) @chunk
(record_declaration
  name: (identifier) @name) @chunk
"""

# C++ node-type mapping:
#   class_specifier       -> class
#   struct_specifier      -> struct
#   function_definition   -> function  (only top-level/namespace-level, since class methods
#                                       use field_identifier as the declarator name, not
#                                       identifier, so they won't match this pattern)
#   namespace_definition  -> namespace
#   template_declaration  -> class|struct|function  (kind determined by first inner decl)
#
# Template edge case: tree-sitter matches BOTH the outer template_declaration AND the inner
# class_specifier/function_definition for templated declarations. The chunker applies a
# containment-dedup step (see _dedup_contained_nodes in chunker_treesitter.py) that removes
# inner captures fully enclosed by an outer @chunk. This ensures the template_declaration is
# kept as the single chunk, with the inner name extracted for SymbolDef.
#
# Extension note: .h is treated as cpp. Pure C files are a valid subset that the C++ grammar
# can parse; any C-only constructs will simply produce no chunks (unknown node types).
CPP = """
(class_specifier
  name: (type_identifier) @name) @chunk
(struct_specifier
  name: (type_identifier) @name) @chunk
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name)) @chunk
(namespace_definition
  name: (namespace_identifier) @name) @chunk
(template_declaration
  (class_specifier
    name: (type_identifier) @name)) @chunk
(template_declaration
  (struct_specifier
    name: (type_identifier) @name)) @chunk
(template_declaration
  (function_definition
    declarator: (function_declarator
      declarator: (identifier) @name))) @chunk
"""

QUERIES_BY_LANG: dict[str, str] = {
    "python": PYTHON,
    "javascript": JAVASCRIPT,
    "typescript": TYPESCRIPT,
    "go": GO,
    "rust": RUST,
    "csharp": CSHARP,
    "java": JAVA,
    "cpp": CPP,
}
