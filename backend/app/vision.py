"""Зураг, видео боловсруулалт.

Видео скан: хэрэглэгч барааг тал бүрээс нь бичихэд бид видеоноос
1) тод (бүдэг биш), 2) гэрэл зөв, 3) бие биенээсээ өөр өнцгийн кадруудыг
автоматаар сонгоно. Ингэснээр нэг бараа олон өнцгийн "хээ"-тэй болж, хайж буй
хүн ямар ч өнцгөөс зураг авсан олдох магадлал өндөрснө.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps

from .embedders import Embedder

MAX_PIXELS = 40_000_000
STORE_MAX_SIDE = 1024
THUMB_MAX_SIDE = 320


class ImageError(ValueError):
    pass


def decode_image(data: bytes) -> np.ndarray:
    """Байт → RGB uint8. Утасны EXIF эргүүлэлтийг засна."""
    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS:
            raise ImageError("Зураг хэт том байна")
        im = ImageOps.exif_transpose(im).convert("RGB")
    except ImageError:
        raise
    except Exception as e:
        raise ImageError("Зургийг уншиж чадсангүй (JPEG, PNG, WebP, HEIC биш байж магадгүй)") from e
    return np.asarray(im)


def encode_webp(rgb: np.ndarray, max_side: int = STORE_MAX_SIDE, quality: int = 80) -> bytes:
    """WebP нь ижил чанартай JPEG-ээс ~40% бага зай эзэлнэ."""
    im = Image.fromarray(rgb)
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def sharpness(rgb: np.ndarray) -> float:
    """Лапласын дисперс: их байх тусам тод. Хэмжээнээс хамаарахгүйн тулд 512px болгоно."""
    h, w = rgb.shape[:2]
    scale = 512 / max(h, w)
    small = cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def exposure_ok(rgb: np.ndarray) -> bool:
    m = float(rgb.mean())
    return 25 <= m <= 235


@dataclass
class Frame:
    rgb: np.ndarray
    sharpness: float
    embedding: np.ndarray


def read_video_frames(path: str, max_candidates: int = 90) -> list[np.ndarray]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ImageError("Видеог уншиж чадсангүй")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    step = max(1, total // max_candidates) if total else 5
    frames, i = [], 0
    while len(frames) < max_candidates:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, bgr = cap.retrieve()
            if ok:
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        i += 1
    cap.release()
    if not frames:
        raise ImageError("Видеоноос кадр олдсонгүй")
    return frames


def select_scan_frames(
    frames: list[np.ndarray],
    embedder: Embedder,
    max_frames: int = 16,
    min_distance: float = 0.03,
) -> list[Frame]:
    """Тод, гэрэл зөв, бие биенээсээ хамгийн өөр кадруудыг сонгоно."""
    scored = [(f, sharpness(f)) for f in frames if exposure_ok(f)]
    if not scored:
        raise ImageError("Бүх кадр хэт харанхуй эсвэл хэт гэрэлтэй байна")
    # Бүдэг кадрыг хаях: медианы 40%-иас доош тодролтой бол
    med = float(np.median([s for _, s in scored]))
    scored = [(f, s) for f, s in scored if s >= 0.4 * med] or scored

    embs = embedder.embed([f for f, _ in scored])
    # Хамгийн хол цэгийн сонголт (farthest point sampling): эхлээд хамгийн тод кадр,
    # дараа нь сонгосон бүх кадраас хамгийн ялгаатайг нэг нэгээр нэмнэ.
    first = int(np.argmax([s for _, s in scored]))
    chosen = [first]
    min_dist = 1 - embs @ embs[first]
    while len(chosen) < min(max_frames, len(scored)):
        nxt = int(np.argmax(min_dist))
        if min_dist[nxt] < min_distance:  # үлдсэн нь бүгд давхардал
            break
        chosen.append(nxt)
        min_dist = np.minimum(min_dist, 1 - embs @ embs[nxt])
    return [Frame(scored[i][0], scored[i][1], embs[i]) for i in chosen]
