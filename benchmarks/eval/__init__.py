"""code-context retrieval eval suite (Sprint 8 / v1.0.0).

Run with:

    python -m benchmarks.eval.runner \
        --repo C:/path/to/repo \
        --queries benchmarks/eval/queries.json

Set env vars from `benchmarks/eval/configs/*.yaml` to switch
retrieval modes (vector_only, hybrid, hybrid_rerank).
"""
