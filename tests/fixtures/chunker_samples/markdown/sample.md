# code-context

A semantic code-search tool for large monorepos.

It indexes your repository with tree-sitter and sentence-transformers,
then exposes search via an MCP server compatible with Claude Code.

## Installation

Install from PyPI:

```bash
pip install code-context-mcp
```

Or with uv:

```bash
uv pip install code-context-mcp
```

### Prerequisites

- Python 3.11+
- An OpenAI-compatible embeddings endpoint (or local model)

### Optional dependencies

Extra packages for local embedding:

```
pip install code-context-mcp[local]
```

## Configuration

Configuration is read from `~/.code-context/config.toml` by default.

```toml
[server]
host = "127.0.0.1"
port = 8080

[embeddings]
model = "text-embedding-3-small"
```

### Server options

| Key    | Default       | Description       |
|--------|---------------|-------------------|
| host   | 127.0.0.1     | Bind address      |
| port   | 8080          | TCP port          |

### Embeddings options

| Key   | Default                   | Description            |
|-------|---------------------------|------------------------|
| model | text-embedding-3-small    | OpenAI model name      |

## Usage

Start the server:

```bash
code-context start
```

Then configure your MCP client to connect to `http://localhost:8080`.

### Search

Use `search_repo` to find relevant code:

```
search_repo("how is authentication handled")
```

### Find definitions

Use `find_definition` to locate symbols:

```
find_definition("UserService")
```

## Architecture

The system is structured around a hexagonal (ports-and-adapters) architecture.

Core domain logic lives in `src/code_context/domain/`.
Adapters live in `src/code_context/adapters/`.

### Chunking

Files are split into overlapping chunks by the chunker pipeline:

1. TreeSitterChunker — AST-aware chunking for supported languages.
2. LineChunker — sliding-window fallback for everything else.

### Indexing

Chunks are embedded and stored in a NumPy vector store.
A SQLite keyword index handles exact-match lookups.

## Contributing

We welcome pull requests.

Please run `make lint` and `make test` before submitting.

### Development setup

```bash
git clone https://github.com/example/code-context
cd code-context
uv sync
```

### Running tests

```bash
python -m pytest tests/ -x --tb=short
```
