import ast
from pathlib import Path


PY310_INCOMPATIBLE_TYPING_NAMES = {"Self", "LiteralString", "Never", "assert_never"}


def test_package_does_not_import_py311_typing_symbols() -> None:
    package_root = Path(__file__).resolve().parents[1] / "birkin_mnemosyne"
    violations: list[str] = []

    for path in sorted(package_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "typing":
                continue
            imported = {alias.name for alias in node.names}
            forbidden = imported & PY310_INCOMPATIBLE_TYPING_NAMES
            for name in sorted(forbidden):
                violations.append(f"{path.relative_to(package_root.parent)} imports typing.{name}")

    assert violations == []
