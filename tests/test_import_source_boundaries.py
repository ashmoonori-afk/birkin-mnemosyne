"""Raw import identity and empty-selection freshness are checked before writes."""

from pathlib import Path

import pytest

from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import ReviewError


def test_import_file_beneath_linked_parent_is_refused(tmp_path: Path) -> None:
    real, alias = tmp_path / "real", tmp_path / "alias"
    real.mkdir()
    _ = (real / "data.txt").write_bytes(b"Original data")
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("The filesystem cannot create the required directory symlink.")
    with pytest.raises(MemoryIndexError):
        _ = plan_init(tmp_path / "vault", import_dir=alias / "data.txt")
    assert not (tmp_path / "vault").exists()


def test_empty_import_selection_is_rechecked_before_publication(tmp_path: Path) -> None:
    external, vault = tmp_path / "source", tmp_path / "vault"
    external.mkdir()
    plan = plan_init(vault, import_dir=external)
    assert plan.imports == ()
    _ = (external / "arrived.txt").write_bytes(b"Arrived after preview")
    with pytest.raises(ReviewError):
        _ = run_init(plan, apply=True)
    assert not MemoryIndex(vault).directory.exists()
    assert not tuple(vault.rglob("*.md"))


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_non_json_numeric_constants_are_warned_and_preserved(
    tmp_path: Path, constant: bytes,
) -> None:
    source = tmp_path / "export.json"
    _ = source.write_bytes(constant)
    plan = plan_init(tmp_path / "vault", import_dir=source)
    report = run_init(plan)
    assert report.warnings
    assert plan.imports[0].preimage == constant
    assert constant in plan.imports[0].destination.raw
    assert not (tmp_path / "vault").exists()
