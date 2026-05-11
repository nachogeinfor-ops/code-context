"""Tests for Sprint 14 setup_logging behavior.

Covers:
  - CC_LOG_FILE: adds a FileHandler in addition to the stderr handler.
  - CC_HF_HUB_VERBOSE: when off (default), huggingface_hub /
    transformers / sentence_transformers loggers are clamped to ERROR.
  - load_config picks up both env vars.
  - Bad CC_LOG_FILE path: warns and continues (does NOT crash).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from code_context._composition import setup_logging
from code_context.config import load_config


@pytest.fixture(autouse=True)
def _reset_logging():
    """Snapshot + restore root + noisy loggers around each test.

    setup_logging mutates root and three sentinel loggers; without
    teardown, levels leak between tests.
    """
    root = logging.getLogger()
    snapshot = {
        "root_level": root.level,
        "root_handlers": list(root.handlers),
    }
    snap_noisy = {
        name: logging.getLogger(name).level
        for name in ("huggingface_hub", "transformers", "sentence_transformers")
    }
    yield
    root.handlers = snapshot["root_handlers"]
    root.setLevel(snapshot["root_level"])
    for name, level in snap_noisy.items():
        logging.getLogger(name).setLevel(level)


def test_log_file_defaults_to_none(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.log_file is None


def test_log_file_reads_from_env(tmp_path: Path) -> None:
    log_target = tmp_path / "cc.log"
    with patch.dict(os.environ, {"CC_LOG_FILE": str(log_target)}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.log_file == str(log_target)


def test_log_file_empty_string_treated_as_unset(tmp_path: Path) -> None:
    """`CC_LOG_FILE=` (empty) should be None, not the empty path."""
    with patch.dict(os.environ, {"CC_LOG_FILE": ""}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.log_file is None


def test_hf_hub_verbose_defaults_to_false(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.hf_hub_verbose is False


def test_hf_hub_verbose_enabled_via_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"CC_HF_HUB_VERBOSE": "on"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.hf_hub_verbose is True


def test_setup_logging_attaches_file_handler(tmp_path: Path) -> None:
    log_target = tmp_path / "cc.log"
    with patch.dict(os.environ, {"CC_LOG_FILE": str(log_target)}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    setup_logging(cfg)

    handlers = logging.getLogger().handlers
    file_handlers = [h for h in handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == log_target.resolve()


def test_setup_logging_no_file_handler_when_unset(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    setup_logging(cfg)

    handlers = logging.getLogger().handlers
    assert not any(isinstance(h, logging.FileHandler) for h in handlers)


def test_setup_logging_writes_to_file(tmp_path: Path) -> None:
    """End-to-end smoke: emit a log line and confirm it lands in the file."""
    log_target = tmp_path / "cc.log"
    with patch.dict(
        os.environ,
        {"CC_LOG_FILE": str(log_target), "CC_LOG_LEVEL": "INFO"},
        clear=True,
    ):
        cfg = load_config(default_repo_root=tmp_path)
    setup_logging(cfg)

    logging.getLogger("code_context.test").info("hello sprint 14")
    # Flush all handlers — FileHandler buffers without explicit flush.
    for h in logging.getLogger().handlers:
        h.flush()

    content = log_target.read_text(encoding="utf-8")
    assert "hello sprint 14" in content


def test_setup_logging_silences_hf_hub_by_default(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    setup_logging(cfg)

    for name in ("huggingface_hub", "transformers", "sentence_transformers"):
        assert logging.getLogger(name).level == logging.ERROR, name


def test_setup_logging_leaves_hf_hub_alone_when_verbose(tmp_path: Path) -> None:
    # First, force them to a known non-ERROR level so we'd notice if setup_logging
    # clamps anyway.
    for name in ("huggingface_hub", "transformers", "sentence_transformers"):
        logging.getLogger(name).setLevel(logging.WARNING)
    with patch.dict(os.environ, {"CC_HF_HUB_VERBOSE": "on"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    setup_logging(cfg)

    for name in ("huggingface_hub", "transformers", "sentence_transformers"):
        # We explicitly want NOT clamped to ERROR. It can stay at WARNING (what
        # we set) or whatever the user's prior level was.
        assert logging.getLogger(name).level != logging.ERROR, name


def test_setup_logging_bad_log_file_does_not_crash(tmp_path: Path) -> None:
    """A CC_LOG_FILE that can't be opened should warn and continue."""
    # Use a path inside a non-existent + non-creatable directory. On POSIX,
    # writing under /this/path/does/not/exist/at/all triggers ENOENT; on
    # Windows we use a path with an illegal character.
    if os.name == "nt":
        bad_path = "C:\\Windows\\System32\\<not-a-real-file>\\cc.log"
    else:
        bad_path = "/this/path/does/not/exist/at/all/cc.log"

    with patch.dict(os.environ, {"CC_LOG_FILE": bad_path}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)

    # Must not raise.
    setup_logging(cfg)

    # Server should still have at least the stderr handler.
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)
