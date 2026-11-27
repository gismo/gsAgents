"""Tests for codex_setup.py and for the Codex side of scripts/guard-agent-model.py.

The Codex CLI is never called: ``codex_version`` and ``model_catalog`` are replaced by stubs,
and every test works in a throwaway ``CODEX_HOME``. The role files are generated from the
plugin's real ``agents/*.md``.
"""
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parents[2]
GUARD = PLUGIN_ROOT / "scripts" / "guard-agent-model.py"
ROLE_KEYS = {"name", "description", "developer_instructions", "model", "model_reasoning_effort"}

spec = importlib.util.spec_from_file_location("codex_setup", HERE / "codex_setup.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

CATALOG = {
    "gpt-5.6-luna": {"low", "medium", "high"},
    "gpt-5.6-terra": {"low", "medium", "high"},
    "gpt-5.6-sol": {"low", "medium", "high"},
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "codex_version", lambda: (0, 154, 0))
    monkeypatch.setattr(cs, "model_catalog", lambda home: CATALOG)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return tmp_path / "codex-home"


def run(capsys, *argv):
    code = cs.main(list(argv))
    return code, capsys.readouterr().out


def agent_files():
    return sorted((PLUGIN_ROOT / "agents").glob("*.md"))


# --- conversion ---------------------------------------------------------------------------


def test_frontmatter_parser_matches_yaml():
    yaml = pytest.importorskip("yaml")
    for path in agent_files():
        text = path.read_text()
        fields, _ = cs.parse_agent(text)
        expected = yaml.safe_load(text.split("---", 2)[1])
        assert fields == {k: str(v) for k, v in expected.items()}, path.name


def test_every_agent_converts_to_a_valid_role():
    tiers = dict(cs.DEFAULT_TIERS)
    roles = cs.expected_roles(PLUGIN_ROOT, tiers)
    assert len(roles) == len(agent_files())
    for path in agent_files():
        fields, _ = cs.parse_agent(path.read_text())
        text, info = roles[f"gismo-{path.stem}.toml"]
        assert text.startswith(cs.MARKER)
        role = tomllib.loads(text)
        assert set(role) <= ROLE_KEYS, path.name
        assert role["name"] == f"gismo:{fields['name']}"
        assert role["description"] == fields["description"]
        assert role["model"] == tiers[fields["model"]]
        assert role.get("model_reasoning_effort") == fields.get("effort")
        assert "CLAUDE_PLUGIN_ROOT" not in role["developer_instructions"]
        assert role["developer_instructions"].startswith("## Running under OpenAI Codex")


def test_plugin_root_is_substituted():
    text, _ = cs.convert_agent(PLUGIN_ROOT / "agents" / "task-lead.md", cs.DEFAULT_TIERS, PLUGIN_ROOT, "x")
    assert f"{PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md" in tomllib.loads(text)["developer_instructions"]


def test_tool_limits_follow_the_claude_tools_line():
    roles = cs.expected_roles(PLUGIN_ROOT, cs.DEFAULT_TIERS)
    scout = tomllib.loads(roles["gismo-scout.toml"][0])["developer_instructions"]
    implementer = tomllib.loads(roles["gismo-implementer.toml"][0])["developer_instructions"]
    assert "do not create or modify files" in scout and "do not spawn agents" in scout
    assert "do not create or modify files" not in implementer


@pytest.mark.parametrize("value", [
    'plain', 'a "quoted" word', 'back\\slash \\n literal', 'triple """ quotes', 'ends with "',
    'ends with \\', 'tab\tand\ncontrol\x01\x7f', '\n\nleading newlines', 'unicode — ✓',
])
def test_toml_strings_round_trip(value):
    assert tomllib.loads(f"a = {cs.toml_string(value)}")["a"] == value
    assert tomllib.loads(f"a = {cs.toml_multiline(value)}")["a"] == value


def test_unknown_tier_leaves_model_unset(tmp_path):
    agent = tmp_path / "x.md"
    agent.write_text('---\nname: x\ndescription: "d"\nmodel: fable\n---\nbody\n')
    text, info = cs.convert_agent(agent, cs.DEFAULT_TIERS, tmp_path, "v")
    assert "model" not in tomllib.loads(text) and info["model"] is None


def test_empty_description_is_refused(tmp_path):
    agent = tmp_path / "x.md"
    agent.write_text("---\nname: x\nmodel: haiku\n---\nbody\n")
    with pytest.raises(cs.SetupError):
        cs.convert_agent(agent, cs.DEFAULT_TIERS, tmp_path, "v")


# --- max_depth editing --------------------------------------------------------------------


@pytest.mark.parametrize("before", [
    "",
    'model = "m"',
    'model = "m"\n',
    '[agents]\nmax_threads = 4\n\n[tui]\nx = 1\n',
    '[agents]\nmax_depth = 1 # default\n[tui]\nx = 1\n',
    '[agents.reviewer]\nconfig_file = "r.toml"\n',
    '[features]\nmulti_agent = true\n',
])
def test_set_depth_text(before):
    after = cs.set_max_depth_text(before, 3)
    parsed = tomllib.loads(after)
    assert parsed["agents"]["max_depth"] == 3
    original = tomllib.loads(before)
    for key, value in original.items():
        if key != "agents":
            assert parsed[key] == value
    for key, value in original.get("agents", {}).items():
        if key != "max_depth":
            assert parsed["agents"][key] == value


@pytest.mark.parametrize("before", ["agents.max_threads = 4\n", "agents = { max_threads = 4 }\n"])
def test_set_depth_refuses_forms_it_cannot_edit(before):
    with pytest.raises(cs.SetupError):
        cs.set_max_depth_text(before, 3)


# --- commands -----------------------------------------------------------------------------


def test_check_install_set_depth_cycle(home, capsys):
    code, out = run(capsys, "check", "--codex-home", str(home))
    assert code == 1
    assert "FAIL max_depth: 1 from Codex default" in out
    assert "FAIL agents: missing:" in out

    code, out = run(capsys, "install", "--codex-home", str(home))
    assert code == 0 and out.rstrip().endswith("STATUS: OK")
    assert len(list((home / "agents").glob("gismo-*.toml"))) == len(agent_files())

    (home / "config.toml").write_text('model = "gpt-5.6-luna"\n')
    code, out = run(capsys, "set-depth", "--codex-home", str(home))
    assert code == 0
    assert list(home.glob("config.toml.bak-gismo-*"))[0].read_text() == 'model = "gpt-5.6-luna"\n'
    assert tomllib.loads((home / "config.toml").read_text()) == {
        "model": "gpt-5.6-luna", "agents": {"max_depth": 3}}

    code, out = run(capsys, "check", "--codex-home", str(home))
    assert code == 0, out
    assert f"OK agents: {len(agent_files())} roles installed" in out

    code, out = run(capsys, "set-depth", "--codex-home", str(home))
    assert code == 0 and "already 3" in out


def test_check_reports_edited_and_orphaned_roles(home, capsys):
    run(capsys, "install", "--codex-home", str(home))
    scout = home / "agents" / "gismo-scout.toml"
    scout.write_text(scout.read_text() + "\n# local edit\n")
    orphan = home / "agents" / "gismo-retired.toml"
    orphan.write_text(f"{cs.MARKER} from retired.md\n")
    code, out = run(capsys, "check", "--codex-home", str(home))
    assert code == 1
    assert "out of date: gismo-scout.toml" in out
    assert "no longer shipped: gismo-retired.toml" in out

    run(capsys, "install", "--codex-home", str(home))
    assert not orphan.exists()
    assert "# local edit" not in scout.read_text()


def test_check_flags_models_missing_from_the_catalog(home, capsys, monkeypatch):
    monkeypatch.setattr(cs, "model_catalog", lambda home: {"gpt-5.6-terra": {"low", "medium", "high"}})
    run(capsys, "install", "--codex-home", str(home))
    code, out = run(capsys, "check", "--codex-home", str(home))
    assert code == 1
    assert "model 'gpt-5.6-sol' is not in this account's Codex catalog" in out
    assert "Fix: install --tier opus=<model>" in out


def test_tier_override_is_remembered(home, capsys):
    run(capsys, "install", "--codex-home", str(home), "--tier", "opus=gpt-5.6-terra")
    run(capsys, "install", "--codex-home", str(home))
    role = tomllib.loads((home / "agents" / "gismo-task-reviewer.toml").read_text())
    assert role["model"] == "gpt-5.6-terra"
    assert json.loads((home / cs.STATE_FILE).read_text())["tiers"]["opus"] == "gpt-5.6-terra"


def test_install_leaves_foreign_files_alone(home, capsys):
    (home / "agents").mkdir(parents=True)
    mine = home / "agents" / "gismo-scout.toml"
    mine.write_text('name = "my-scout"\n')
    code, out = run(capsys, "install", "--codex-home", str(home))
    assert code == 1 and "was not written by codex-setup" in out
    assert mine.read_text() == 'name = "my-scout"\n'


def test_bad_tier_argument(home, capsys):
    code, out = run(capsys, "install", "--codex-home", str(home), "--tier", "gpt=x")
    assert code == 2 and "--tier expects" in out


def test_project_depth_overrides_user_depth(home, capsys, tmp_path):
    run(capsys, "install", "--codex-home", str(home))
    run(capsys, "set-depth", "--codex-home", str(home))
    project = tmp_path / "gismo"
    (project / ".codex").mkdir(parents=True)
    (project / ".codex" / "config.toml").write_text("[agents]\nmax_depth = 2\n")
    code, out = run(capsys, "check", "--codex-home", str(home), "--project", str(project))
    assert code == 1 and "FAIL max_depth: 2 from" in out


# --- guard hook under Codex ---------------------------------------------------------------


def guard(tool_input, tool_name="spawn_agent"):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input}
    result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] if result.stdout else "allow"


@pytest.mark.parametrize("tool_input, decision", [
    ({"agent_type": "gismo:scout", "message": "m"}, "allow"),
    ({"agent_type": "gismo:task-reviewer", "message": "m"}, "allow"),
    ({"agent_type": "gismo:scout", "model": "gpt-5.6-sol", "message": "m"}, "deny"),
    ({"agent_type": "explorer", "message": "m"}, "deny"),
    ({"agent_type": "worker", "message": "m"}, "deny"),
    ({"message": "m"}, "deny"),
    ({"subagent_type": "Explore", "prompt": "p"}, "deny"),
    ({"subagent_type": "gismo:scout", "prompt": "p"}, "allow"),
])
def test_guard_reads_codex_agent_type(tool_input, decision):
    assert guard(tool_input) == decision
