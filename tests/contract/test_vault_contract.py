"""Store every public example through the same API used by future thin shells."""

from pathlib import Path

from reliclab.codec import parse_module
from reliclab.vault import Vault

ROOT = Path(__file__).resolve().parents[2]


def test_public_examples_share_one_plain_text_vault(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    snapshots = [
        vault.create(parse_module(path.read_bytes()))
        for path in sorted((ROOT / "examples").glob("*/*.md"))
    ]
    assert len(snapshots) == 15
    assert len(vault.list()) == len(snapshots)
    for snapshot in snapshots:
        assert vault.get(snapshot.key) == snapshot
        assert (tmp_path / snapshot.relative_path).read_bytes() == snapshot.content
    assert list(tmp_path.glob("*.db")) == []
