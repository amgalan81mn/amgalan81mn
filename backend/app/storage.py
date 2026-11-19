"""Зураг хадгалах давхарга.

Одоо серверийн дискэнд хадгална. Интернэтэд байршуулахдаа S3-тэй нийцтэй объект
хадгалах сан (Cloudflare R2, Backblaze B2 гэх мэт) руу шилжинэ: ижил
`save / url / delete` гэсэн гурван функцтэй шинэ класс бичихэд л хангалттай.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def save(self, data: bytes, ext: str) -> str: ...
    def url(self, key: str | None) -> str | None: ...
    def delete(self, key: str | None) -> None: ...


class LocalStorage:
    def __init__(self, root: str | Path, url_prefix: str = "/media"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.url_prefix = url_prefix

    def _path(self, key: str) -> Path:
        # Түлхүүрийг бид өөрсдөө үүсгэдэг; гаднаас ирсэн зам руу бичихгүй.
        if "/" in key or "\\" in key or key.startswith("."):
            raise ValueError("Буруу түлхүүр")
        return self.root / key

    def save(self, data: bytes, ext: str) -> str:
        key = f"{uuid.uuid4().hex}.{ext}"
        self._path(key).write_bytes(data)
        return key

    def url(self, key: str | None) -> str | None:
        return f"{self.url_prefix}/{key}" if key else None

    def delete(self, key: str | None) -> None:
        if key:
            self._path(key).unlink(missing_ok=True)
