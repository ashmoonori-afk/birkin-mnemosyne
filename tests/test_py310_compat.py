"""The package must stay importable on Python 3.10 (``requires-python``)."""

from __future__ import annotations

import ast
from pathlib import Path

# Names that exist only on Python 3.11+, by the stdlib module that defines them.
PY311_NAMES = {
    "typing": {
        "Self",
        "LiteralString",
        "Never",
        "assert_never",
        "assert_type",
        "reveal_type",
        "Required",
        "NotRequired",
        "Unpack",
        "TypeVarTuple",
        "dataclass_transform",
    },
    "datetime": {"UTC"},
    "enum": {"StrEnum"},
    "itertools": {"batched"},
}
PY311_MODULES = {"tomllib"}


def find_py310_violations(package_root: Path) -> list[str]:
    """Report 3.11+ imports, attribute accesses and syntax in ``*.py`` under
    ``package_root``.  A file that does not parse on the running interpreter
    is reported too, which is how ``except*`` shows up when this runs on 3.10."""
    violations: list[str] = []
    for path in sorted(package_root.glob("*.py")):
        rel = f"{package_root.name}/{path.name}"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{rel} does not parse on this interpreter: {exc.msg}")
            continue
        modules: dict[str, str] = {}  # local name -> stdlib module imported as it
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in PY311_MODULES:
                        violations.append(f"{rel} imports {alias.name}")
                    modules[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in PY311_MODULES:
                    violations.append(f"{rel} imports from {node.module}")
                for alias in node.names:
                    if alias.name in PY311_NAMES.get(node.module, ()):
                        violations.append(f"{rel} imports {node.module}.{alias.name}")
            elif isinstance(node, getattr(ast, "TryStar", ())):
                violations.append(f"{rel} uses except*")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                module = modules.get(node.value.id)
                if node.attr in PY311_NAMES.get(module, ()):
                    violations.append(f"{rel} uses {module}.{node.attr}")
    return sorted(set(violations))


def test_package_does_not_use_py311_only_features() -> None:
    package_root = Path(__file__).resolve().parents[1] / "birkin_mnemosyne"
    assert find_py310_violations(package_root) == []


def test_scanner_flags_every_py311_construct(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "from_import.py").write_text(
        "from typing import Self\n"
        "from datetime import UTC\n"
        "from enum import StrEnum\n"
        "from itertools import batched\n"
        "from tomllib import loads\n",
        encoding="utf-8",
    )
    (pkg / "attribute.py").write_text(
        "import typing\n"
        "import datetime as dt\n"
        "import enum, itertools, tomllib\n"
        "a = typing.Never\n"
        "b = dt.UTC\n"
        "c = enum.StrEnum\n"
        "d = itertools.batched\n",
        encoding="utf-8",
    )
    (pkg / "star.py").write_text(
        "try:\n    pass\nexcept* ValueError:\n    pass\n", encoding="utf-8"
    )
    found = "\n".join(find_py310_violations(pkg))
    for expected in (
        "from_import.py imports typing.Self",
        "from_import.py imports datetime.UTC",
        "from_import.py imports enum.StrEnum",
        "from_import.py imports itertools.batched",
        "from_import.py imports from tomllib",
        "attribute.py imports tomllib",
        "attribute.py uses typing.Never",
        "attribute.py uses datetime.UTC",
        "attribute.py uses enum.StrEnum",
        "attribute.py uses itertools.batched",
        "star.py",  # "uses except*" on 3.11+, "does not parse" on 3.10
    ):
        assert expected in found


def test_scanner_accepts_py310_code(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "from __future__ import annotations\n"
        "import datetime\n"
        "from typing import Optional\n"
        "x: Optional[int] = None\n"
        "y = datetime.timezone.utc\n"
        "class Local:\n    UTC = 1\n"
        "z = Local.UTC\n",
        encoding="utf-8",
    )
    assert find_py310_violations(tmp_path) == []
