import pytest
from pathlib import Path
import json

import compiler.compile as compile_mod


def test_format_scalar_bool_and_number():
    assert compile_mod._format_scalar("flag", True) == "flag: true\n"
    assert compile_mod._format_scalar("n", 42) == "n: 42\n"


def test_format_scalar_multiline_and_quoting():
    s = "line1\nline2"
    assert "|" in compile_mod._format_scalar("desc", s)
    assert compile_mod._format_scalar("k", "a:b") == 'k: "a:b"\n'


def test_compile_entity_basic(tmp_path):
    # Simple entity with tools and model
    entity = {
        "name": "tst",
        "description": "desc",
        "prompt": "do it",
        "model": "claude-2",
        "tools": ["git", "fs"],
        "providers": {"claude": True},
    }

    out = compile_mod.compile_entity_for_provider(
        entity, "claude", template_type="agents"
    )
    assert isinstance(out, str)
    assert "model:" in out or "claude-2" in out
