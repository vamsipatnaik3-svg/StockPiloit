from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.core.config import settings


class WorkbookStorage(Protocol):
    """Provider boundary for private workbook persistence."""

    def store(self, upload_id: UUID, content: bytes) -> str: ...
    def read(self, object_key: str) -> bytes: ...
    def delete(self, object_key: str) -> None: ...


class LocalWorkbookStorage:
    """Local development provider. object keys remain provider-neutral at the API layer."""

    scheme = "local://"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def store(self, upload_id: UUID, content: bytes) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        object_key = f"{self.scheme}{upload_id}.xlsx"
        self._path(object_key).write_bytes(content)
        return object_key

    def read(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()

    def delete(self, object_key: str) -> None:
        self._path(object_key).unlink(missing_ok=True)

    def exists(self, object_key: str) -> bool:
        return self._path(object_key).is_file()

    def _path(self, object_key: str) -> Path:
        if object_key.startswith(self.scheme):
            name = object_key[len(self.scheme):]
            if Path(name).name != name or not name.endswith(".xlsx"):
                raise ValueError("Invalid local workbook object key.")
            return self.root / name

        # Read keys created by the earlier local-storage implementation.
        legacy = Path(object_key).resolve()
        if legacy.parent != self.root:
            raise ValueError("Workbook key is outside the configured storage directory.")
        return legacy


def get_workbook_storage() -> WorkbookStorage:
    return LocalWorkbookStorage(settings.upload_storage_dir)
