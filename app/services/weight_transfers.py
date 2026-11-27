"""Resumable model weight storage for an authenticated compute worker."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import re
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.services.models import get_model_def
from app.services.scheduler import _atomic, _read

MAX_CHUNK_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
_DIGEST = r"^[0-9a-f]{64}$"
_FILE_ID = r"^[a-z][a-z0-9_]{0,63}$"
_MODEL_ID = r"^[a-z0-9][a-z0-9_.-]{0,95}(@[a-z0-9][a-z0-9_.-]{0,95})?$"


class WeightFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(pattern=_FILE_ID)
    path: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(strict=True, gt=0, le=1 << 40)
    sha256: str = Field(pattern=_DIGEST)
    shared_path: str | None = Field(default=None, max_length=1024)


class WeightManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(pattern=_MODEL_ID)
    files: list[WeightFile] = Field(min_length=1, max_length=32)
    source: Literal["copy", "shared"] = "copy"


class WeightTransfers:
    def __init__(self, root: Path, shared_root: Path | None = None):
        self.root = root
        self.shared_root = shared_root
        self._verification: dict[str, dict] = {}

    @contextmanager
    def _locked(self, transfer_id: str):
        if not re.fullmatch(_DIGEST, transfer_id):
            raise HTTPException(404, "WEIGHT_TRANSFER_NOT_FOUND")
        directory = self.root / transfer_id
        try:
            with (directory / ".lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield directory
        except FileNotFoundError:
            raise HTTPException(404, "WEIGHT_TRANSFER_NOT_FOUND") from None

    @staticmethod
    def _validate_files(manifest: WeightManifest) -> WeightManifest:
        key, _, variant = manifest.model_id.partition("@")
        try:
            model = get_model_def(key, variant)
        except (KeyError, ValueError):
            raise HTTPException(422, "UNKNOWN_WEIGHT_MODEL") from None
        roles = model["runtime"].get("roles") or {}
        files = {file.file_id: file for file in manifest.files}
        if len(files) != len(manifest.files) or files.keys() != ({"model"} | roles.keys()):
            raise HTTPException(422, "WEIGHT_FILE_SET_MISMATCH")
        for file in files.values():
            if (
                file.path in {".", ".."}
                or "/" in file.path
                or "\\" in file.path
                or any(ord(character) < 32 or ord(character) == 127 for character in file.path)
            ):
                raise HTTPException(422, "INVALID_WEIGHT_FILENAME")
            relative = file.shared_path
            if manifest.source == "shared":
                if (
                    not relative or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/"))
                    or Path(relative).name != file.path
                    or any(ord(character) < 32 or ord(character) == 127 for character in relative)
                ):
                    raise HTTPException(422, "INVALID_SHARED_WEIGHT_PATH")
            elif relative is not None:
                raise HTTPException(422, "INVALID_SHARED_WEIGHT_PATH")
        for role, path in roles.items():
            if files[role].path != Path(path).name:
                raise HTTPException(422, "WEIGHT_FILE_SET_MISMATCH")
        if Path(files["model"].path).suffix.lower() not in {".safetensors", ".ckpt", ".pt", ".pth", ".gguf"}:
            raise HTTPException(422, "INVALID_WEIGHT_FILENAME")
        registered = model["files"]
        if registered and Path(registered[0]).name != files["model"].path:
            raise HTTPException(422, "WEIGHT_FILE_SET_MISMATCH")
        return manifest.model_copy(update={"files": sorted(files.values(), key=lambda item: item.file_id)})

    @staticmethod
    def _manifest(directory: Path) -> WeightManifest:
        try:
            return WeightManifest.model_validate_json((directory / "manifest.json").read_bytes())
        except ValidationError:
            raise HTTPException(500, "WEIGHT_MANIFEST_UNREADABLE") from None

    @staticmethod
    def _file(directory: Path, file: WeightFile) -> Path:
        return directory / file.file_id / file.path

    def shared_available(self) -> bool:
        root = self.shared_root
        try:
            return root is not None and root.is_dir() and bool(os.statvfs(root).f_flag & os.ST_RDONLY)
        except OSError:
            return False

    def _shared_files(self, manifest: WeightManifest) -> dict[str, Path]:
        root = self.shared_root
        if root is None or not self.shared_available():
            raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE")
        try:
            paths = {}
            for file in manifest.files:
                path = root / file.shared_path
                pinned = path.parent.resolve(strict=True) / path.name
                resolved = pinned.resolve(strict=True)
                if (
                    not pinned.is_relative_to(root) or not resolved.is_relative_to(root) or not resolved.is_file()
                    or resolved.stat().st_size != file.size_bytes
                ):
                    raise OSError("shared model revision unavailable")
                paths[file.file_id] = pinned
            return paths
        except (OSError, KeyError, ValueError):
            raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE") from None

    def _prepared_files(self, directory: Path, manifest: WeightManifest) -> dict[str, Path]:
        if manifest.source == "copy":
            return {file.file_id: self._file(directory, file) for file in manifest.files}
        relative = _read(directory / "verified.json").get("shared_paths", {})
        if self.shared_root is None or not self.shared_available():
            return {}
        paths = {}
        for file in manifest.files:
            if file.file_id not in relative:
                continue
            try:
                path = self.shared_root / relative[file.file_id]
                if path.resolve(strict=True).is_relative_to(self.shared_root) and path.is_file():
                    paths[file.file_id] = path
            except OSError:
                continue
        return paths

    def _status(self, directory: Path, manifest: WeightManifest) -> dict:
        paths = self._prepared_files(directory, manifest)
        files = []
        for file in manifest.files:
            path = paths.get(file.file_id)
            try:
                size = path.stat().st_size if path else 0
            except OSError:
                size = 0
            files.append({"file_id": file.file_id, "received_bytes": size})
        verified = (directory / "verified.json").is_file() and all(
            state["received_bytes"] == file.size_bytes for state, file in zip(files, manifest.files)
        )
        return {
            "transfer_id": directory.name, "model_id": manifest.model_id,
            "files": files, "verified": verified, "source": manifest.source,
            "verification": (
                {"state": "verified", "bytes": sum(file.size_bytes for file in manifest.files)}
                if verified else self._verification.get(directory.name, {"state": "idle", "bytes": 0})
            ),
        }

    def begin(self, manifest: WeightManifest) -> dict:
        manifest = self._validate_files(manifest)
        if manifest.source == "shared":
            self._shared_files(manifest)
        transfer_id = hashlib.sha256(manifest.model_dump_json(exclude_defaults=True).encode()).hexdigest()
        (self.root / transfer_id).mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._locked(transfer_id) as directory:
            if not (directory / "manifest.json").exists():
                _atomic(directory / "manifest.json", manifest.model_dump())
            return self._status(directory, manifest)

    def status(self, transfer_id: str) -> dict:
        if not re.fullmatch(_DIGEST, transfer_id):
            raise HTTPException(404, "WEIGHT_TRANSFER_NOT_FOUND")
        directory = self.root / transfer_id
        try:
            return self._status(directory, self._manifest(directory))
        except FileNotFoundError:
            raise HTTPException(404, "WEIGHT_TRANSFER_NOT_FOUND") from None

    def verified_models(self) -> list[str]:
        if not self.root.is_dir():
            return []
        models = set()
        for directory in self.root.iterdir():
            if not (directory / "verified.json").is_file():
                continue
            status = self.status(directory.name)
            if status["verified"]:
                models.add(status["model_id"])
        return sorted(models)

    def verified_paths(self, transfer_id: str, model_id: str) -> dict[str, Path]:
        with self._locked(transfer_id) as directory:
            manifest = self._manifest(directory)
            if manifest.model_id != model_id or not self._status(directory, manifest)["verified"]:
                raise HTTPException(409, "WORKER_WEIGHTS_NOT_READY")
            return self._prepared_files(directory, manifest)

    def append(self, transfer_id: str, file_id: str, offset: int, content: bytes) -> dict:
        if not 0 < len(content) <= MAX_CHUNK_BYTES:
            raise HTTPException(413, "INVALID_WEIGHT_CHUNK_SIZE")
        with self._locked(transfer_id) as directory:
            manifest = self._manifest(directory)
            if manifest.source == "shared":
                raise HTTPException(409, "WEIGHT_SHARED_READ_ONLY")
            file = next((file for file in manifest.files if file.file_id == file_id), None)
            if file is None:
                raise HTTPException(404, "WEIGHT_FILE_NOT_FOUND")
            path = self._file(directory, file)
            received = path.stat().st_size if path.exists() else 0
            end = offset + len(content)
            if offset < 0 or offset > received or end > file.size_bytes:
                raise HTTPException(409, "WEIGHT_OFFSET_MISMATCH")
            if offset < received:
                with path.open("rb") as stream:
                    stream.seek(offset)
                    if end > received or stream.read(len(content)) != content:
                        raise HTTPException(409, "WEIGHT_OFFSET_MISMATCH")
                return {"received_bytes": received}
            if (directory / "verified.json").is_file():
                raise HTTPException(409, "WEIGHT_TRANSFER_COMPLETE")
            path.parent.mkdir(mode=0o700, exist_ok=True)
            try:
                with path.open("ab") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                if path.exists():
                    with path.open("r+b") as stream:
                        stream.truncate(received)
                raise
            return {"received_bytes": end}

    def complete(self, transfer_id: str) -> dict:
        with self._locked(transfer_id) as directory:
            manifest = self._manifest(directory)
            if (directory / "verified.json").is_file():
                status = self._status(directory, manifest)
                if status["verified"]:
                    return status
                if manifest.source == "shared":
                    raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE")
            self._verification[transfer_id] = {"state": "verifying", "bytes": 0}
            try:
                return self._verify_locked(directory, manifest)
            except HTTPException as exc:
                self._verification[transfer_id] = {
                    "state": "failed", "bytes": self._verification[transfer_id]["bytes"], "error": exc.detail,
                }
                raise
            finally:
                if self._verification.get(transfer_id, {}).get("state") != "failed":
                    self._verification.pop(transfer_id, None)

    def _verify_locked(self, directory: Path, manifest: WeightManifest) -> dict:
        paths = self._shared_files(manifest) if manifest.source == "shared" else self._prepared_files(directory, manifest)
        for file in manifest.files:
            path = paths[file.file_id]
            if not path.is_file() or path.stat().st_size != file.size_bytes:
                raise HTTPException(409, "WEIGHT_TRANSFER_INCOMPLETE")
        checked = 0
        for file in manifest.files:
            path = paths[file.file_id]
            def progress(size: int) -> None:
                self._verification[directory.name] = {"state": "verifying", "bytes": checked + size}

            try:
                matches = sha256_file(path, progress) == file.sha256
            except OSError:
                if manifest.source == "shared":
                    raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE") from None
                raise
            if not matches:
                if manifest.source == "shared":
                    raise HTTPException(409, "WEIGHT_SHARED_UNAVAILABLE")
                path.unlink()
                raise HTTPException(422, "WEIGHT_CHECKSUM_MISMATCH")
            checked += file.size_bytes
        receipt = {"model_id": manifest.model_id}
        if manifest.source == "shared":
            receipt["shared_paths"] = {key: str(path.relative_to(self.shared_root)) for key, path in paths.items()}
        _atomic(directory / "verified.json", receipt)
        return self._status(directory, manifest)


def sha256_file(path: Path, progress: Callable[[int], None] | None = None) -> str:
    digest = hashlib.sha256()
    received = 0
    next_update = monotonic()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MAX_CHUNK_BYTES), b""):
            digest.update(chunk)
            if progress:
                received += len(chunk)
                now = monotonic()
                if now >= next_update:
                    progress(received)
                    next_update = now + 0.5
    if progress:
        progress(received)
    return digest.hexdigest()


def require_worker_channel(authorization: str = Header(default="")) -> None:
    token = os.environ.get("V_SCHEDULER_BACKEND_CHANNEL_TOKEN", "")
    if not token or not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        raise HTTPException(401, "WORKER_CHANNEL_REQUIRED")


async def _bounded_body(request: Request, maximum: int) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > maximum:
            raise HTTPException(413, "WEIGHT_REQUEST_TOO_LARGE")
        content.extend(chunk)
    return bytes(content)


def transfer_routes(store: WeightTransfers) -> APIRouter:
    """Mount only in the worker's trusted transport router."""
    router = APIRouter(prefix="/scheduler/transfers", dependencies=[Depends(require_worker_channel)])

    @router.post("")
    async def begin(request: Request):
        if request.headers.get("content-type", "").partition(";")[0] != "application/json":
            raise HTTPException(415, "WEIGHT_MANIFEST_CONTENT_TYPE_REQUIRED")
        try:
            manifest = WeightManifest.model_validate_json(await _bounded_body(request, MAX_MANIFEST_BYTES))
        except ValidationError:
            raise HTTPException(422, "INVALID_WEIGHT_MANIFEST") from None
        return await run_in_threadpool(store.begin, manifest)

    @router.get("/{transfer_id}")
    def status(transfer_id: str):
        return store.status(transfer_id)

    @router.put("/{transfer_id}/files/{file_id}")
    async def append(transfer_id: str, file_id: str, offset: Annotated[int, Query(ge=0)], request: Request):
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(415, "WEIGHT_CHUNK_CONTENT_TYPE_REQUIRED")
        content = await _bounded_body(request, MAX_CHUNK_BYTES)
        return await run_in_threadpool(store.append, transfer_id, file_id, offset, content)

    @router.post("/{transfer_id}/complete")
    def complete(transfer_id: str):
        return store.complete(transfer_id)

    return router
