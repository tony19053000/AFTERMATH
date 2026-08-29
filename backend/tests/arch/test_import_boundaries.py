"""Architectural boundary enforcement.

This file defends the project's founding principle — AGENTS THINK, PYTHON TESTS
(`CLAUDE.md` §2). It is a static check over the source tree rather than a runtime
check, so it holds even for code paths no test exercises.

Two properties:

1. Deterministic layers (`replay`, `immunity`, `benchmark` except `baseline.py`)
   import no LLM module. If evidence generation could call a model, "the
   experiment proved it" would become "a model said so".
2. Vendor SDKs appear only in `llm/` and `companyagent/`, so a provider swap
   touches one file (D-006).

**Honest limitation (P1).** `replay/`, `immunity/`, and `benchmark/` are still
empty package stubs, so the checks over them currently pass with nothing to
inspect. They become load-bearing in P4 when the replay engine lands. The
detector itself is verified against a synthetic violating tree below, so the
guard is known to work before it has real code to guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "aftermath"

# `benchmark/baseline.py` is the single-LLM baseline: it *is* a model call by
# definition (D-007). The grader, metrics, and runner beside it stay deterministic.
DETERMINISTIC_PACKAGES = ("replay", "immunity", "benchmark")
LLM_EXEMPT = {("benchmark", "baseline.py")}

VENDOR_MODULES = ("google.genai", "google.generativeai", "openai", "anthropic", "langchain")
VENDOR_ALLOWED_PACKAGES = ("llm", "companyagent")


def imported_modules(path: Path) -> set[str]:
    """Every module name imported by a file, including deferred/in-function imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def find_llm_offenders(root: Path, package: str) -> list[str]:
    """Modules in ``package`` that import the LLM layer. Empty means compliant."""
    directory = root / package
    if not directory.exists():
        return []
    offenders: list[str] = []
    for module_path in sorted(directory.rglob("*.py")):
        if (package, module_path.name) in LLM_EXEMPT:
            continue
        llm_imports = {n for n in imported_modules(module_path) if n.startswith("aftermath.llm")}
        if llm_imports:
            offenders.append(f"{module_path.relative_to(root)} imports {sorted(llm_imports)}")
    return offenders


def find_vendor_offenders(root: Path) -> list[str]:
    """Modules outside the adapter packages that import a vendor SDK."""
    offenders: list[str] = []
    for module_path in root.rglob("*.py"):
        relative = module_path.relative_to(root)
        if relative.parts and relative.parts[0] in VENDOR_ALLOWED_PACKAGES:
            continue
        for imported in imported_modules(module_path):
            if any(imported.startswith(vendor) for vendor in VENDOR_MODULES):
                offenders.append(f"{relative} imports {imported}")
    return offenders


@pytest.mark.parametrize("package", DETERMINISTIC_PACKAGES)
def test_deterministic_layers_do_not_import_llm(package: str) -> None:
    """Evidence must never be produced by a model."""
    offenders = find_llm_offenders(PACKAGE_ROOT, package)

    assert not offenders, (
        f"deterministic layer '{package}' must not import aftermath.llm — "
        "outcomes, scoring and metrics are established by Python, not by a model. "
        f"Offenders: {offenders}"
    )


def test_vendor_sdks_confined_to_adapter_packages() -> None:
    """A provider swap must touch one file, not the whole codebase."""
    offenders = find_vendor_offenders(PACKAGE_ROOT)

    assert not offenders, (
        f"vendor SDKs may only be imported inside {VENDOR_ALLOWED_PACKAGES}. "
        f"Offenders: {offenders}"
    )


def test_core_has_no_internal_dependencies_beyond_core() -> None:
    """`core` sits at the bottom of the layering and depends on nothing above it."""
    offenders: list[str] = []
    for module_path in sorted((PACKAGE_ROOT / "core").rglob("*.py")):
        for imported in imported_modules(module_path):
            if imported.startswith("aftermath.") and not imported.startswith("aftermath.core"):
                offenders.append(f"{module_path.name} imports {imported}")

    assert not offenders, f"core must not depend on higher layers. Offenders: {offenders}"


def test_deterministic_packages_exist() -> None:
    """Guard the guard: if these directories vanish, the checks above pass vacuously."""
    for package in DETERMINISTIC_PACKAGES:
        assert (PACKAGE_ROOT / package).is_dir(), f"missing package: {package}"


class TestDetectorActuallyDetects:
    """A guard that cannot fail is decoration. Run the real logic on real violations."""

    def test_catches_module_level_llm_import(self, tmp_path: Path) -> None:
        (tmp_path / "replay").mkdir()
        (tmp_path / "replay" / "engine.py").write_text(
            "from aftermath.llm.base import LLMProvider\n", encoding="utf-8"
        )

        offenders = find_llm_offenders(tmp_path, "replay")

        assert len(offenders) == 1
        assert "engine.py" in offenders[0]

    def test_catches_llm_import_hidden_inside_a_function(self, tmp_path: Path) -> None:
        """The realistic violation: someone 'just needs a model here' locally."""
        (tmp_path / "replay").mkdir()
        (tmp_path / "replay" / "scoring.py").write_text(
            "def score(run):\n"
            "    from aftermath.llm.factory import build_provider\n"
            "    return build_provider(run)\n",
            encoding="utf-8",
        )

        assert find_llm_offenders(tmp_path, "replay")

    def test_honours_the_baseline_exemption(self, tmp_path: Path) -> None:
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "benchmark" / "baseline.py").write_text(
            "from aftermath.llm.base import LLMProvider\n", encoding="utf-8"
        )

        assert find_llm_offenders(tmp_path, "benchmark") == []

    def test_baseline_exemption_does_not_leak_to_siblings(self, tmp_path: Path) -> None:
        """The grader sits next to the baseline and must stay deterministic."""
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "benchmark" / "grader.py").write_text(
            "from aftermath.llm.base import LLMProvider\n", encoding="utf-8"
        )

        assert find_llm_offenders(tmp_path, "benchmark")

    def test_clean_module_produces_no_offenders(self, tmp_path: Path) -> None:
        (tmp_path / "replay").mkdir()
        (tmp_path / "replay" / "engine.py").write_text(
            "from aftermath.core.trace import Trace\n", encoding="utf-8"
        )

        assert find_llm_offenders(tmp_path, "replay") == []

    def test_catches_vendor_sdk_outside_adapters(self, tmp_path: Path) -> None:
        (tmp_path / "forensics").mkdir()
        (tmp_path / "forensics" / "agent.py").write_text(
            "from google import genai\nimport openai\n", encoding="utf-8"
        )

        assert find_vendor_offenders(tmp_path)

    def test_vendor_sdk_allowed_inside_llm_package(self, tmp_path: Path) -> None:
        (tmp_path / "llm").mkdir()
        (tmp_path / "llm" / "gemini.py").write_text("from google import genai\n", encoding="utf-8")

        assert find_vendor_offenders(tmp_path) == []
