"""FindDefinitionUseCase — delegates to SymbolIndex."""

from __future__ import annotations

from dataclasses import dataclass

from code_context.domain.models import SymbolDef
from code_context.domain.ports import SymbolIndex


@dataclass
class FindDefinitionUseCase:
    """Use case for the find_definition MCP tool.

    Thin delegate over SymbolIndex.find_definition. Ranking, language
    filtering, and max-count semantics live in the adapter; this layer
    only exists to keep the MCP driving adapter free of port-specific
    knowledge (mirrors the pattern of RecentChangesUseCase and
    GetSummaryUseCase).
    """

    symbol_index: SymbolIndex

    def run(
        self,
        name: str,
        language: str | None = None,
        max_count: int = 5,
    ) -> list[SymbolDef]:
        return self.symbol_index.find_definition(name, language=language, max_count=max_count)
