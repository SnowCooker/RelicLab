# Local Vault API

Status: S03 implementation, pre-release. The Vault is a synchronous, database-free
storage library in `reliclab.vault`. It is intended for a **trusted local filesystem
managed by the host**, not an adversarial filesystem or process sandbox. Asset
syntax and validation remain defined by [SPEC.md](SPEC.md).

## Quick Start

```python
from tempfile import TemporaryDirectory

from reliclab.schema import validate_module
from reliclab.vault import CommitReceipt, Vault

document = validate_module({
    "schema_version": "1.0", "kind": "persona", "id": "editor",
    "version": "1.0.0", "name": "Editor", "identity": "A careful editor",
})
changes: list[CommitReceipt] = []
with TemporaryDirectory() as root:
    vault = Vault(root, on_change=changes.append)
    original = vault.create(document)
    changed = vault.update(
        original.key,
        document.model_copy(update={"name": "Reviewer"}),
        expected_hash=original.content_hash,
    )
    backup = changes[-1].backup_path
    assert backup is not None
    restored = vault.restore(backup, expected_hash=changed.content_hash)
    assert restored.content == original.content
    vault.delete(restored.key, expected_hash=restored.content_hash)
    assert vault.list() == ()
```

`model_copy(update=...)` does not validate by itself; Vault mutations revalidate
before writing. Stale revisions raise `RelicError(code="SOURCE_CHANGED")`.
Reload current content and merge the intended changes before retrying. Never
replace the expected hash merely to force a stale document through.

## API and Data

| API | Result and behavior |
|---|---|
| `Vault(root, file_ops=None, limits=CodecLimits(), on_change=None, max_modules=10000, max_catalog_bytes=67108864)` | Creates the local root and four kind directories if absent |
| `get(key)` | `ModuleSnapshot`; missing key is `NOT_FOUND` |
| `list(query=ModuleQuery())` | Tuple of `ModuleSummary`, freshly scanned and filtered |
| `create(document)` | Snapshot; cannot overwrite a key or destination |
| `update(key, document, expected_hash)` | Snapshot; identity cannot change; identical DTOs do not rewrite bytes |
| `delete(key, expected_hash)` | `None`; refuses referenced assets and preserves a backup |
| `restore(backup_path, expected_hash=None)` | Snapshot; restores exact validated backup bytes |

S04 adds `snapshot() -> CatalogSnapshot`, with two validated scans under one
cooperating-client lock and immutable captured bytes. See [RESOLVE.md](RESOLVE.md)
for its consistency limits and the resolution/lock API.

Public exports also include `FileOps`, `LocalFileOps`, `CommitReceipt`, and
`PostCommitError`. Configuration errors use `ValueError`; invalid key/query DTOs
use Pydantic validation errors. Asset, filesystem, and conflict failures use
`RelicError` with English, value-free messages.

A frozen snapshot contains `key`, `relative_path`, lowercase SHA-256
`content_hash`, immutable raw `content: bytes`, and codec `limits`. The hash is
over those exact bytes, not normalized metadata. `snapshot.document` returns a
fresh decoded DTO on each access; mutable extension mappings cannot corrupt the
stored snapshot. This also avoids trusting DTOs changed after a read.

A summary contains key, name, description, tags, relative path, and content hash.
`ModuleQuery` supports optional kind/id, case-insensitive substring `text`
(id/name/description), all-required exact tags, offset >= 0, and limit 1-1000
(default 100). Sorting is lexical `(kind, id, version)`, **not SemVer selection**.
Pagination is stable for an unchanged catalog; separate page calls are not a
multi-call snapshot if another writer changes the catalog.

## Layout and Scanning

```text
vault/
  .reliclab.lock
  personas/{id}@{version}.md
  skills/{id}@{version}.md
  memory/{id}@{version}.md
  compositions/{id}@{version}.md
```

Each kind directory is flat. Existing portable `.md` filenames may differ from
the canonical name; their validated metadata determines identity. Updates retain
their path. Creation, including restoring a deleted key, uses the canonical name.
Body kind must match its directory. Nested directories, symbolic links, junctions,
other reparse points, and externally hard-linked files are rejected.

Every operation rescans the four directories under the application lock; there
is no database or persistent cache. Duplicate keys or case-folded path collisions
fail with `VERSION_CONFLICT`, even if query filters would hide the duplicate.
Malformed assets fail closed rather than producing an incomplete successful list.
Other files are not modules, but still must pass path/link checks.

Default catalog limits are 10000 modules and 64 MiB of raw asset bytes.
`LocalFileOps` additionally limits each directory to 20000 entries, including
backups and temporary files. Hosts may change these positive-integer bounds and
codec limits. Prospective creates/updates/restores are checked against catalog
limits before writing. Reads allocate at most the configured codec byte limit
plus delimiter/BOM overhead and one extra byte to detect overflow. Failed limits
never silently truncate content or return partial successful catalogs.

## Commit and Recovery

Cooperating clients use the same native cross-process lock at `.reliclab.lock`.
`LocalFileOps(root, lock_timeout=5, max_entries=20000)` configures lock waiting.
Lock contention beyond the timeout raises retryable `IO_ERROR`; reload before
retrying. The lock file remains in place. Do not remove it while clients run.
Native locking is provided by [filelock](https://py-filelock.readthedocs.io/en/latest/);
soft-lock fallback is explicitly disabled.

Changed assets follow this sequence:

1. Scan under the lock; verify identity and expected content hash.
2. Serialize/validate proposed content and check prospective limits.
3. For update/delete/overwrite-restore, write a byte-exact recovery backup, flush
   and fsync its file, publish it without replacement, and sync its directory
   where supported. If this fails, do not mutate the original.
4. Prepare a same-directory temporary file; flush and fsync its bytes.
5. Read the destination again and compare the expected hash immediately before
   replacing or deleting it. An ordinary external edit causes `SOURCE_CHANGED`.
6. Publish a create with atomic no-replace hard-link creation, update with
   `os.replace`, or delete with unlink. Remove the temporary name and sync the
   directory where supported. New/replaced file modes request `0600`; old ACLs
   and permissions are not copied.
7. Release the lock, then send an optional change notification.

Backup names are `.reliclab-backup-{uuid}.bak` in the asset's kind directory;
temporary names are `.reliclab-tmp-{uuid}.tmp`. Neither is a Markdown module.
Backups retain comments, BOM, and original newlines. They are not automatically
pruned. `CommitReceipt(operation, key, content_hash, backup_path)` gives a relative
backup path for changed existing assets; delete receipts have no new content hash.
Without a callback, recovery files can be inspected in the corresponding directory.

`restore(backup_path)` requires the original key to be absent. To restore over an
existing asset, provide its freshly read hash. Restoration validates backup bytes,
uses the same transaction path, and backs up the replaced version before writing.
It does not restore the original filename after deletion, permissions, or ACLs.
Invalid catalog files must first be quarantined by the host while clients are
stopped; normal APIs intentionally do not bypass parsing or path guards to repair
arbitrary corrupted files.

### Errors After Commit

Directory sync, temporary cleanup, lock release, or notification can fail **after**
the mutation has happened. Such failures raise `PostCommitError` with
`committed=True`, `retryable=False`, and a `receipt`; they do not roll back or repeat
the write. Reload and inspect the receipt and recovery files. Notifications are
best-effort, not a durable event queue. Fresh scans do not depend on their delivery.

A crash or cleanup failure during no-replace publication can leave a temporary
hard link to a complete asset/backup. Link checks then refuse that file until
recovery. Stop all clients, inspect the reserved `.tmp` entries and their targets,
remove only the abandoned temporary names, and reload. Do not recursively delete
the Vault, backups, or lock file. An interrupted precommit write can also leave
a partial `.tmp`, never a partially published `.md`.

## Filesystem Guarantees and Limits

- File content is fsynced before publication. Directory fsync is attempted on
  supported POSIX hosts; `LocalFileOps.sync` explicitly returns false on Windows.
  Windows power-loss directory durability is therefore not guaranteed. Atomic
  visibility does not imply universal crash durability.
- Local filesystems must support native locking and atomic same-directory replace
  and hard-link publication. Network shares, UNC/device paths, and soft fallback
  are unsupported. Unsupported filesystem operations fail instead of weakening
  publication semantics.
- Roots and asset paths reject traversal, device names, ADS, wildcard paths,
  invalid UTF-8 paths, and protected `.git`, `.env`, `.ssh`, `.aws`, `.codex` paths.
  Paths are checked component by component. Reads use `O_NOFOLLOW` where available,
  validate handle identity/type, and compare path/handle metadata before/after
  reading. Windows path/handle `ctime` values are compared only within the same API.
- **This is not an OS sandbox.** Repeated path checks and final-component no-follow
  do not establish a complete descriptor-relative ancestry guarantee on all hosts.
  A malicious process concurrently replacing ancestors can still race path-based
  write operations. Keep roots and ancestors host-controlled; use an isolated or
  fully handle-relative backend before admitting adversarial filesystem writers.
- **Hash comparison is not atomic CAS with uncooperative editors.** An external
  write after the final hash check can still be overwritten. Recovery backups
  preserve the version observed by the Vault, not an unobserved last-moment edit.
  Preserve editor conflict copies and compare all versions before recovery.
- Deletion rejects any same-kind reference to the module ID, including selectors
  that might resolve to another version. This conservative rule remains independent
  of the S04 resolver and has no force-delete escape hatch.

## FileOps and Verification

The injectable `FileOps` port owns `root`, `locked`, `entries`, bounded `read`,
`stage`, `publish`, `remove`, and `sync`. Custom implementations are trusted host
components and must preserve containment, lock exclusion, and atomic publication.
`stage` must clean partial files on ordinary failures; `publish`/asset `remove`
must not return a precommit exception after successfully changing the destination.
Post-publication cleanup/sync failures are separate operations. The adapter root
must exactly match the absolute Vault root; do not inject an untrusted adapter.

Run `python scripts/check.py --stage S03 --offline` and the packaging gate.
Tests use real temporary files, cross-process/thread competition, original-byte
recovery, injected write/fsync/replace/delete/notification failures, POSIX symlinks
or actual Windows junctions, hard links, and controlled path-swap races. Independent
statement and branch gates for the entire Vault are both 95%. Isolated wheel
installations exercise actual Vault create/read/delete in all five combinations.
