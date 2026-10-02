"""Resolve the repository-owned Playwright runtime for browser regressions."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_NODE_MODULES = ROOT / "node_modules"
LOCAL_PLAYWRIGHT_CORE = LOCAL_NODE_MODULES / "playwright-core"
LOCAL_BROWSER_CACHE = ROOT / ".playwright-browsers"


class BrowserRuntimeError(RuntimeError):
    """Raised when the project-local browser runtime is unavailable."""


def resolve_node() -> str:
    """Return the Node executable selected by the current environment."""

    node = shutil.which("node.exe") or shutil.which("node")
    if node is None:
        raise BrowserRuntimeError(
            "Could not find Node.js. Run scripts/setup_environment.py or install the "
            "Node version declared in .node-version."
        )
    return node


def resolve_playwright_core() -> str:
    """Return the repository's installed playwright-core package directory."""

    package_json = LOCAL_PLAYWRIGHT_CORE / "package.json"
    if package_json.is_file():
        return str(LOCAL_PLAYWRIGHT_CORE)
    raise BrowserRuntimeError(
        "Could not find the project-local Playwright package. Run "
        "scripts/setup_environment.py (it runs npm ci and installs Chromium); "
        "global npm packages are not used by regression gates."
    )


def browser_environment() -> dict[str, str]:
    """Return a child-process environment with a project-local browser cache."""

    environment = dict(os.environ)
    # Respect an explicit CI/operator override, including Playwright's special
    # value ``0``. Otherwise keep downloaded browsers inside the checkout.
    environment.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(LOCAL_BROWSER_CACHE))
    return environment
