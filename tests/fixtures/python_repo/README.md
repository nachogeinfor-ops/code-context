# python_repo — eval fixture for code-context

This directory is a hand-crafted fixture used by the `code-context` retrieval
eval harness. It is **not** a working FastAPI application — it is realistic,
tutorial-grade Python code (~15 substantive source files) that models a small
FastAPI + pydantic + SQLAlchemy service. The fixture exists so the eval runner
can index it with tree-sitter and measure retrieval quality against a curated
set of natural-language queries (`benchmarks/eval/queries/python.json`).

The skeleton is deliberately kept larger than the minimum (~15 requested) to
provide more distinct retrieval targets: the spec's "~15 files" referred to
substantive source files, not counting `__init__.py` package boilerplate or
the test suite. Adding the full router/model/schema/service/repository split
makes the query set richer and the eval more representative of real codebases.
Do not import from this fixture in the main test suite (`tests/unit/` or
`tests/integration/`).
