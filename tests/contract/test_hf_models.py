"""Contract test: every entry in MODEL_REGISTRY exists on Hugging Face.

This test catches the v0.3.0 class of bug where a planning error introduced
`BAAI/bge-code-v1.5` (which never existed) as the default. We ping the HF
API for each registered name. Marked with the `network` pytest marker so
it can be skipped on offline / sandboxed builds; CI runs it as a separate
job that needs network egress.

Run only this test with:
    pytest -m network tests/contract/test_hf_models.py
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from code_context.adapters.driven.embeddings_local import MODEL_REGISTRY

# A short alias like "all-MiniLM-L6-v2" without an org prefix is a
# sentence-transformers shortcut — the canonical HF id is
# "sentence-transformers/all-MiniLM-L6-v2". The HF API only knows the
# canonical form, so we skip aliases (they're documented as such in the
# MODEL_REGISTRY entries).
_KNOWN_ALIASES = {"all-MiniLM-L6-v2"}


@pytest.mark.network
@pytest.mark.parametrize("model_id", sorted(MODEL_REGISTRY.keys()))
def test_model_exists_on_huggingface(model_id: str) -> None:
    """Pings huggingface.co/api/models/<id>; expects HTTP 200.

    Skips known short aliases (e.g. all-MiniLM-L6-v2 — the canonical id is
    sentence-transformers/all-MiniLM-L6-v2 which is also in the registry).
    """
    if model_id in _KNOWN_ALIASES:
        pytest.skip(f"{model_id!r} is a sentence-transformers short alias, not a canonical HF id")
    url = f"https://huggingface.co/api/models/{model_id}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            assert resp.status == 200, (
                f"{model_id!r} listed in MODEL_REGISTRY but HF API returned "
                f"HTTP {resp.status}. Did you fabricate the identifier "
                f"(remember v0.3.0)?"
            )
    except urllib.error.HTTPError as exc:
        pytest.fail(
            f"{model_id!r} listed in MODEL_REGISTRY but HF API returned "
            f"HTTP {exc.code}. Verify the identifier on huggingface.co. "
            f"(v0.3.0 lesson: every default must be reachable.)"
        )
    except urllib.error.URLError as exc:
        pytest.skip(f"network unreachable: {exc}")
