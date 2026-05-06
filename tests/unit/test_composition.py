"""Unit tests for the composition layer."""

from __future__ import annotations


def test_null_symbol_index_set_source_tiers_is_noop() -> None:
    """_NullSymbolIndex.set_source_tiers must not raise with any list argument.

    Added as part of the I-2 review fix (T8 Sprint 10): _NullSymbolIndex now
    explicitly implements the SymbolIndex Protocol, so the composition layer's
    direct call to symbol_index.set_source_tiers() works without a hasattr guard.
    """
    from code_context._composition import _NullSymbolIndex

    null_idx = _NullSymbolIndex()
    # Must not raise for empty list.
    null_idx.set_source_tiers([])
    # Must not raise for non-empty list.
    null_idx.set_source_tiers(["src", "lib"])
    # find_references still returns [] after tiers are set.
    assert null_idx.find_references("anything") == []
    assert null_idx.find_definition("anything") == []
