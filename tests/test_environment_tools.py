import json
from pathlib import Path

import pytest

from scripts import browser_runtime, check_environment, setup_environment


def test_dependency_drift_fails_read_only_lock_check(monkeypatch):
    calls = []
    monkeypatch.setattr(check_environment, "uv_candidate", lambda: "test-uv")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "--version" in command:
            return {"returncode": 0, "stdout": f"uv {setup_environment.UV_VERSION}", "stderr": ""}
        return {"returncode": 1, "stdout": "", "stderr": "Environment requires synchronization"}

    monkeypatch.setattr(check_environment, "run_command", run)
    result = check_environment.locked_environment_report()

    assert result["status"] == "mismatch"
    assert result["synchronized"] is False
    assert {"--check", "--locked", "--offline", "--no-python-downloads"} <= set(calls[1][0])


def test_missing_uv_preflight_does_not_install_anything(monkeypatch):
    monkeypatch.setattr(check_environment, "uv_candidate", lambda: None)
    monkeypatch.setattr(check_environment, "run_command", lambda *args, **kwargs: pytest.fail("read-only preflight installed a tool"))
    assert check_environment.locked_environment_report()["status"] == "missing"


def test_database_failure_report_does_not_disclose_connection_credentials(monkeypatch):
    import sqlalchemy

    secret = "private-test-password"
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://tester:{secret}@localhost/test")

    def fail(*args, **kwargs):
        raise RuntimeError(f"failed connecting with {secret}")

    monkeypatch.setattr(sqlalchemy, "create_engine", fail)
    result = check_environment.schema_report()
    assert result["status"] == "unavailable"
    assert secret not in json.dumps(result)


def test_missing_local_playwright_never_falls_back_to_global_install(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_runtime, "LOCAL_PLAYWRIGHT_CORE", tmp_path / "missing-local-playwright")
    monkeypatch.setattr(browser_runtime.shutil, "which", lambda _command: pytest.fail("global tool lookup is not a local Playwright install"))
    with pytest.raises(browser_runtime.BrowserRuntimeError, match="project-local Playwright"):
        browser_runtime.resolve_playwright_core()


def test_explicit_browser_override_is_not_a_reproducible_pass(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_CHROME_PATH", "custom-browser")
    result = check_environment.chromium_report("test-node")
    assert result["status"] == "override"
    assert result["reproducible"] is False


def test_a_launchable_browser_with_the_wrong_version_is_not_a_pass(monkeypatch, tmp_path):
    monkeypatch.delenv("PLAYWRIGHT_CHROME_PATH", raising=False)
    monkeypatch.setattr(check_environment, "ROOT", tmp_path)
    package = tmp_path / "node_modules" / "playwright-core"
    package.mkdir(parents=True)
    (package / "package.json").write_text("{}", encoding="utf-8")
    (package / "browsers.json").write_text(json.dumps({"browsers": [{"name": "chromium", "browserVersion": "153.0.0"}]}), encoding="utf-8")
    executable = tmp_path / "browser"
    executable.touch()
    outputs = iter([str(executable), "152.0.0"])
    monkeypatch.setattr(check_environment, "run_command", lambda *args, **kwargs: {"returncode": 0, "stdout": next(outputs), "stderr": ""})
    result = check_environment.chromium_report("test-node")
    assert result["status"] == "mismatch"
    assert result["reproducible"] is False


def test_bootstrap_from_venv_uses_the_base_python_for_user_tool_install(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(setup_environment, "uv_candidate", lambda: None)
    monkeypatch.setattr(setup_environment.sys, "_base_executable", "base-python")
    monkeypatch.setattr(setup_environment, "user_scripts_directory", lambda: tmp_path)
    monkeypatch.setattr(setup_environment, "check_uv_version", lambda _path: None)

    def install(command, **kwargs):
        commands.append(command)
        (tmp_path / ("uv.exe" if setup_environment.os.name == "nt" else "uv")).touch()

    monkeypatch.setattr(setup_environment, "run", install)
    executable = setup_environment.ensure_uv(allow_bootstrap=True)
    assert Path(executable).is_file()
    assert commands[0][0] == "base-python"
    assert "--user" in commands[0]
