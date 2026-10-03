"""Validate catalog contracts, revision preconditions, and immutable snapshots."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from reliclab.codec import CodecLimits, serialize_module
from reliclab.schema import RelicError
from reliclab.vault import LocalFileOps, ModuleQuery, Vault

from tests.support.vault import asset


@pytest.mark.parametrize("kind", ["persona", "skill", "memory", "composition"])
def test_crud_snapshot_hash_and_backup_restore(tmp_path: Path, kind: str) -> None:
    vault = Vault(tmp_path)
    original = vault.create(asset(kind))
    assert original.content_hash == hashlib.sha256(original.content).hexdigest()
    assert vault.get(original.key) == original
    changed = asset(kind, name="Changed")
    updated = vault.update(original.key, changed, original.content_hash)
    assert updated.document.name == "Changed"
    assert updated.content_hash != original.content_hash
    backups = list(tmp_path.glob("*/.reliclab-backup-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original.content
    restored = vault.restore(backups[0].relative_to(tmp_path).as_posix(), updated.content_hash)
    assert restored.content == original.content
    vault.delete(restored.key, restored.content_hash)
    assert vault.list() == ()
    with pytest.raises(RelicError) as caught:
        vault.get(restored.key)
    assert caught.value.code == "NOT_FOUND"
    assert vault.restore(backups[0].relative_to(tmp_path).as_posix()).content == original.content


def test_fresh_document_mapping_cannot_corrupt_snapshot(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    snapshot = vault.create(asset(extensions={"x-settings": {"tone": "plain"}}))
    snapshot.document.extensions["x-settings"] = "corrupted"
    assert snapshot.document.extensions == {"x-settings": {"tone": "plain"}}
    assert vault.get(snapshot.key) == snapshot


def test_noop_preserves_comments_and_original_bytes_without_event(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    original = (
        "---\r\n# Keep this comment\r\nschema_version: '1.0'\r\nid: sample\r\n"
        "kind: persona\r\nversion: 1.0.0\r\nname: Sample\r\nidentity: Editor\r\n---\r\n"
    )
    path = tmp_path / "personas/custom-name.md"
    path.write_bytes(original.encode())
    before = vault.get(asset().key)
    vault.on_change = lambda event: pytest.fail("No-op emitted a change")
    assert vault.update(before.key, before.document, before.content_hash) == before
    assert path.read_bytes() == before.content
    assert list(tmp_path.glob("*/.reliclab-backup-*")) == []


def test_external_edits_are_not_hidden_by_a_catalog_cache(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    before = vault.create(asset())
    path = tmp_path / before.relative_path
    external = serialize_module(asset(name="External editor")).encode()
    path.write_bytes(external)
    assert vault.get(before.key).content == external
    assert vault.list()[0].name == "External editor"
    for operation in (
        lambda: vault.update(before.key, asset(name="Stale"), before.content_hash),
        lambda: vault.delete(before.key, before.content_hash),
    ):
        with pytest.raises(RelicError) as caught:
            operation()
        assert caught.value.code == "SOURCE_CHANGED"
        assert path.read_bytes() == external


def test_duplicate_keys_fail_even_when_query_would_hide_them(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    snapshot = vault.create(asset())
    (tmp_path / "personas/copy.md").write_bytes(snapshot.content)
    with pytest.raises(RelicError) as caught:
        vault.list(ModuleQuery(kind="skill"))
    assert caught.value.code == "VERSION_CONFLICT"


def test_directory_kind_mismatch_and_invalid_asset_fail_closed(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    path = tmp_path / "skills/wrong.md"
    path.write_text(serialize_module(asset()), encoding="utf-8")
    with pytest.raises(RelicError) as caught:
        vault.list()
    assert caught.value.code == "SCHEMA_INVALID"
    path.write_bytes(b"not an asset")
    with pytest.raises(RelicError) as caught:
        vault.list()
    assert caught.value.code == "PARSE_ERROR"


def test_query_filters_stable_sort_and_offset_pagination(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    for identifier, version in [("zeta", "1.0.0"), ("alpha", "2.0.0"), ("alpha", "1.0.0")]:
        vault.create(
            asset(id=identifier, version=version, tags=["editor"], description="Exact NOTES")
        )
    vault.create(asset("skill", id="review"))
    assert [(item.key.kind, item.key.id, item.key.version) for item in vault.list()] == [
        ("persona", "alpha", "1.0.0"),
        ("persona", "alpha", "2.0.0"),
        ("persona", "zeta", "1.0.0"),
        ("skill", "review", "1.0.0"),
    ]
    assert (
        len(vault.list(ModuleQuery(kind="persona", id="alpha", tags=("editor",), text="notes")))
        == 2
    )
    assert vault.list(ModuleQuery(text="not-present")) == ()
    assert vault.list(ModuleQuery(tags=("missing",))) == ()
    assert vault.list(ModuleQuery(offset=1, limit=2)) == vault.list()[1:3]
    assert vault.list(ModuleQuery(offset=99)) == ()


@pytest.mark.parametrize(
    "query",
    [
        {"offset": -1},
        {"limit": 0},
        {"limit": 1001},
        {"limit": True},
        {"kind": "other"},
        {"id": "../x"},
        {"text": "x" * 201},
        {"unknown": 1},
    ],
)
def test_query_validation(query: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ModuleQuery(**query)


def test_existing_create_missing_mutations_and_changed_key(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    first = vault.create(asset())
    with pytest.raises(RelicError) as caught:
        vault.create(asset(name="Overwrite"))
    assert caught.value.code == "VERSION_CONFLICT"
    with pytest.raises(RelicError) as caught:
        vault.update(first.key, asset(id="different"), first.content_hash)
    assert caught.value.code == "SCHEMA_INVALID"
    with pytest.raises(RelicError) as caught:
        vault.update(asset(id="missing").key, asset(id="missing"), first.content_hash)
    assert caught.value.code == "NOT_FOUND"
    with pytest.raises(RelicError):
        vault.delete(asset(id="missing").key, first.content_hash)


@pytest.mark.parametrize("digest", ["", "0" * 63, "0" * 65, "A" * 64, "z" * 64, None, 1])
def test_invalid_revision_rejected_before_writes(tmp_path: Path, digest: Any) -> None:
    vault = Vault(tmp_path)
    with pytest.raises(ValueError, match="SHA-256"):
        vault.update(asset().key, asset(), digest)
    assert vault.list() == ()


@pytest.mark.parametrize(
    "path", ["../backup.bak", "/backup.bak", "personas/sample.md", "skills/.reliclab-backup-no.bak"]
)
def test_restore_only_accepts_recovery_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(RelicError) as caught:
        Vault(tmp_path).restore(path)
    assert caught.value.code == "PATH_DENIED"


def test_restore_precondition_validation(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    initial = vault.create(asset())
    vault.update(initial.key, asset(name="Changed"), initial.content_hash)
    backup = next(tmp_path.glob("*/.reliclab-backup-*")).relative_to(tmp_path).as_posix()
    with pytest.raises(RelicError) as caught:
        vault.restore(backup)
    assert caught.value.code == "VERSION_CONFLICT"
    with pytest.raises(ValueError):
        vault.restore(backup, "bad")


@pytest.mark.parametrize(
    "target,reference",
    [
        (asset(), asset(id="child", extends="sample@2")),
        (asset(), asset("composition", modules={"persona": "sample"})),
        (asset("skill"), asset("composition", modules={"skills": ["sample@^1.0.0"]})),
        (asset("memory"), asset("composition", modules={"memory": ["sample"]})),
    ],
)
def test_referenced_deletion_is_conservatively_rejected(
    tmp_path: Path, target: Any, reference: Any
) -> None:
    vault = Vault(tmp_path)
    snapshot = vault.create(target)
    dependent = vault.create(reference)
    with pytest.raises(RelicError) as caught:
        vault.delete(snapshot.key, snapshot.content_hash)
    assert caught.value.code == "VERSION_CONFLICT"
    vault.delete(dependent.key, dependent.content_hash)
    vault.delete(snapshot.key, snapshot.content_hash)


def test_other_kind_and_other_id_references_do_not_block_deletion(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    snapshot = vault.create(asset())
    vault.create(asset("composition", modules={"skills": ["sample"]}))
    vault.create(asset(id="child", extends="another"))
    vault.delete(snapshot.key, snapshot.content_hash)


def test_recovery_artifacts_are_not_catalog_modules(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    (tmp_path / "personas/.reliclab-tmp-abandoned.tmp").write_bytes(b"partial bytes")
    (tmp_path / "personas/.reliclab-backup-old.bak").write_bytes(b"backup")
    assert vault.list() == ()


def test_fileops_root_must_match_and_codec_limits_propagate(tmp_path: Path) -> None:
    ops = LocalFileOps(tmp_path / "other")
    with pytest.raises(ValueError, match="root"):
        Vault(tmp_path, file_ops=ops)
    vault = Vault(tmp_path, limits=CodecLimits(max_body_bytes=2))
    with pytest.raises(RelicError):
        vault.create(asset(body="too large"))
    assert vault.list() == ()


@pytest.mark.parametrize(
    "limits",
    [
        {"max_modules": 0},
        {"max_catalog_bytes": -1},
        {"max_modules": True},
        {"max_catalog_bytes": 1.5},
    ],
)
def test_catalog_limit_validation(tmp_path: Path, limits: Any) -> None:
    with pytest.raises(ValueError):
        Vault(tmp_path, **limits)


def test_catalog_limits_apply_to_reads_and_prospective_writes(tmp_path: Path) -> None:
    vault = Vault(tmp_path, max_modules=1)
    initial = vault.create(asset())
    with pytest.raises(RelicError, match="catalog exceeds"):
        vault.create(asset(id="another"))
    assert len(vault.list()) == 1
    limited = Vault(tmp_path, max_catalog_bytes=len(initial.content))
    with pytest.raises(RelicError, match="catalog exceeds"):
        limited.update(initial.key, asset(name="Much longer name"), initial.content_hash)
    with pytest.raises(RelicError, match="catalog exceeds"):
        Vault(tmp_path, max_catalog_bytes=1).list()
    (tmp_path / "personas/second.md").write_bytes(serialize_module(asset(id="second")).encode())
    with pytest.raises(RelicError, match="catalog exceeds"):
        vault.list()


def test_case_only_version_paths_cannot_be_created(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    first = vault.create(asset(version="1.0.0+BUILD"))
    with pytest.raises(RelicError) as caught:
        vault.create(asset(version="1.0.0+build"))
    assert caught.value.code == "VERSION_CONFLICT"
    assert vault.get(first.key) == first


def test_unavailable_filesystem_errors_are_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = Vault(tmp_path)

    def inaccessible(directory: str) -> tuple[str, ...]:
        raise PermissionError("private path and content")

    monkeypatch.setattr(vault.files, "entries", inaccessible)
    with pytest.raises(RelicError) as caught:
        vault.list()
    assert caught.value.code == "IO_ERROR"
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__
