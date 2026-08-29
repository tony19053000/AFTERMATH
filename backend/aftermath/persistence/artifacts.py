"""Content-addressed artifact store.

Every published number must be traceable to a stored artifact
(`docs/PROJECT_REQUIREMENTS.md` §10), so artifacts are written once, hashed, and
never mutated in place. The hash is the integrity check that a later phase's
evidence chain (and eventually the TEE vault) builds on.
"""

from __future__ import annotations

from pathlib import Path

from aftermath.core.hashing import content_hash, hash_file


class ArtifactStore:
    """Writes and reads immutable artifacts under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, kind: str, name: str) -> Path:
        return self.root / kind / name

    def write_text(self, kind: str, name: str, content: str) -> Path:
        """Write an artifact, refusing to silently overwrite differing content.

        Re-writing identical content is a no-op, which keeps re-runs idempotent.

        Raises:
            FileExistsError: if the artifact exists with different content.
        """
        path = self.path_for(kind, name)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return path
            raise FileExistsError(
                f"artifact {path} already exists with different content; "
                "artifacts are immutable evidence and must not be overwritten"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_text(self, path: Path | str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def hash_of(self, path: Path | str) -> str:
        return hash_file(str(path))

    def verify(self, path: Path | str, expected_hash: str) -> bool:
        """Check an artifact still hashes to what was recorded."""
        return self.hash_of(path) == expected_hash

    @staticmethod
    def hash_content(payload: object) -> str:
        return content_hash(payload)
