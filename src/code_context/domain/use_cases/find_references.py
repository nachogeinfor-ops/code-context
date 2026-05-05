"""FindReferencesUseCase — delegates to SymbolIndex."""

from __future__ import annotations

from dataclasses import dataclass

from code_context.domain.models import SymbolRef
from code_context.domain.ports import SymbolIndex


@dataclass
class FindReferencesUseCase:
    """Use case for the find_references MCP tool.

    Thin delegate over SymbolIndex.find_references. Word-boundary matching
    and result ordering are the adapter's responsibility.
    """

    symbol_index: SymbolIndex

    def run(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        return self.symbol_index.find_references(name, max_count=max_count)
