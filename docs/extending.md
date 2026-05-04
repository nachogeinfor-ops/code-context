# Extending `code-context`

Every adapter implements a Protocol from `src/code_context/domain/ports.py`. Protocols are duck-typed — no inheritance.

## Adding a new embeddings provider

Suppose you want a Cohere-backed provider.

1. Add the file `src/code_context/adapters/driven/embeddings_cohere.py`:

```python
import numpy as np

class CohereProvider:
    def __init__(self, api_key: str, model: str = "embed-english-v3.0"):
        self.api_key = api_key
        self.model = model
        self._client = None

    @property
    def dimension(self) -> int:
        return 1024  # Cohere v3 default

    @property
    def model_id(self) -> str:
        return f"cohere:{self.model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._client is None:
            import cohere
            self._client = cohere.Client(self.api_key)
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        resp = self._client.embed(texts=texts, model=self.model)
        return np.array(resp.embeddings, dtype=np.float32)
```

2. Add a unit test mocking the cohere SDK (see `tests/unit/adapters/test_embeddings_openai.py` as a template).

3. Wire it in `src/code_context/_composition.py`'s `build_embeddings()`:

```python
if cfg.embeddings_provider == "cohere":
    from code_context.adapters.driven.embeddings_cohere import CohereProvider
    return CohereProvider(api_key=os.environ["COHERE_API_KEY"])
```

4. Document the new option in `docs/configuration.md`.

## Adding a new vector store

Same pattern. Implement `VectorStore` (see `src/code_context/domain/ports.py`). Common alternatives: ChromaDB, LanceDB, sqlite-vec.

## Adding a new chunker

For tree-sitter-based chunking:

1. Add `src/code_context/adapters/driven/chunker_treesitter.py` implementing `Chunker`.
2. The `version` property should be specific enough to differentiate from `LineChunker` (e.g., `treesitter-py-v1`).
3. Wire selection via a `CC_CHUNKER` env var.

## Tool Protocol changes

If you need to add or change an MCP tool, you must coordinate with the upstream contract in [context-template](https://github.com/nachogeinfor-ops/context-template). See `CONTRIBUTING.md`.
