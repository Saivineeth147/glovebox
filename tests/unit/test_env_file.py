"""The documented setup path is `cp .env.example .env`; these tests hold it honest."""

from __future__ import annotations

import os
from pathlib import Path

from glovebox.envfile import load_env_file, parse_env_file


def test_should_parse_key_value_pairs_and_ignore_comments_and_blanks(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# a comment\n\nGLOVEBOX_MODEL=anthropic/claude-sonnet-5\n")

    assert parse_env_file(env) == {"GLOVEBOX_MODEL": "anthropic/claude-sonnet-5"}


def test_should_strip_export_prefix_and_surrounding_quotes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('export GLOVEBOX_APP_PASSWORD="teller1-pass"\n')

    assert parse_env_file(env) == {"GLOVEBOX_APP_PASSWORD": "teller1-pass"}


def test_should_keep_hash_inside_a_value(tmp_path: Path) -> None:
    """An API key may contain '#', so an unquoted value is never truncated at one."""
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=sk-or-v1-a#b\n")

    assert parse_env_file(env)["OPENROUTER_API_KEY"] == "sk-or-v1-a#b"


def test_should_return_empty_mapping_when_file_is_absent(tmp_path: Path) -> None:
    assert parse_env_file(tmp_path / "nonexistent.env") == {}


def test_should_not_override_a_variable_already_in_the_environment(
    tmp_path: Path, monkeypatch
) -> None:
    """A real export (CI secret, operator shell) must beat a stale checked-out file."""
    monkeypatch.setenv("GLOVEBOX_MODEL", "openai/gpt-5.6-sol")
    env = tmp_path / ".env"
    env.write_text("GLOVEBOX_MODEL=anthropic/claude-sonnet-5\n")

    load_env_file(env)

    assert os.environ["GLOVEBOX_MODEL"] == "openai/gpt-5.6-sol"


def test_should_report_the_names_it_set_without_exposing_values(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=sk-or-secret\n")

    assert load_env_file(env) == ["OPENROUTER_API_KEY"]


def test_should_load_the_project_dotenv_before_a_command_runs(tmp_path: Path, monkeypatch) -> None:
    """Wiring test: every CLI command, including `studio` and `discover`, gets the file."""
    from typer.testing import CliRunner

    from glovebox import cli

    monkeypatch.delenv("GLOVEBOX_MARKER", raising=False)
    (tmp_path / ".env").write_text("GLOVEBOX_MARKER=loaded\n")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    CliRunner().invoke(cli.app, ["schema"])

    assert os.environ["GLOVEBOX_MARKER"] == "loaded"
