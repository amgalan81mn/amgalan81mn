"""Зургийн "хээ" (embedding) гаргагч загварууд.

Хоёр загвартай:
- `basic`: өнгө + дүрс дээр суурилсан энгийн хээ. Ямар ч татах зүйлгүй, хурдан,
  гэхдээ өнцөг, гэрэл өөрчлөгдвөл амархан андуурна. Тест, туршилтад зориулсан.
- `dinov2`: Meta-гийн DINOv2 загвар. Зургийн агуулгыг "ойлгодог" тул өөр өнцөг,
  гэрэл, сүүдэртэй зургаас ч ижил барааг таньдаг. Анх ачаалахад huggingface.co-оос
  жин татна (`requirements-ml.txt`).

Аль загварыг ашиглахыг `EMBEDDER` орчны хувьсагчаар сонгоно.
"""
from __future__ import annotations

import os
from typing import Protocol

import cv2
import numpy as np


class Embedder(Protocol):
    name: str
    dim: int
    match_threshold: float  # энэ утгаас дээш бол "ижил бараа" гэж үзнэ
    duplicate_threshold: float  # энэ утгаас дээш бол давхардсан зураг

    def embed(self, images: list[np.ndarray]) -> np.ndarray:
        """RGB uint8 зургууд → (N, dim) float32, L2-нормчилсон."""
        ...


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return (v / np.maximum(n, 1e-12)).astype(np.float32)


def _center(v: np.ndarray) -> np.ndarray:
    return _l2(v - v.mean())


def _soft_hist1d(pos: np.ndarray, n: int, circular: bool = False) -> np.ndarray:
    """Зөөлөн гистограм: утга бүрийг хөрш хоёр нүдэнд зайнаас нь хамааруулж хуваана.
    Хатуу заагтай гистограмаас ялгаатай нь бага зэрэг өөрчлөлтөд үсрэхгүй."""
    pos = np.asarray(pos, np.float32) - 0.5
    lo = np.floor(pos)
    w_hi = pos - lo
    lo = lo.astype(np.int64)
    hi = lo + 1
    if circular:
        lo, hi = lo % n, hi % n
    else:
        lo, hi = np.clip(lo, 0, n - 1), np.clip(hi, 0, n - 1)
    h = np.zeros(n, np.float32)
    np.add.at(h, lo, 1 - w_hi)
    np.add.at(h, hi, w_hi)
    return h


def _soft_hist2d(pos_a: np.ndarray, pos_b: np.ndarray, na: int, nb: int) -> np.ndarray:
    """2D зөөлөн гистограм. Эхний тэнхлэг (өнгөний аяс) тойрог: 0 ба 179 хоёулаа улаан."""
    h = np.zeros((na, nb), np.float32)
    pa, pb = np.asarray(pos_a, np.float32) - 0.5, np.asarray(pos_b, np.float32) - 0.5
    la, lb = np.floor(pa), np.floor(pb)
    wa, wb = pa - la, pb - lb
    la, lb = la.astype(np.int64), lb.astype(np.int64)
    for da, fa in ((0, 1 - wa), (1, wa)):
        for db, fb in ((0, 1 - wb), (1, wb)):
            np.add.at(h, ((la + da) % na, np.clip(lb + db, 0, nb - 1)), fa * fb)
    return h.ravel()


class BasicEmbedder:
    name = "basic-v1"
    dim = 48 + 64
    match_threshold = float(os.environ.get("MATCH_THRESHOLD_BASIC", 0.9))
    duplicate_threshold = 0.995  # үүнээс дээш бол бараг ижил зураг: дахин хадгалахгүй

    def embed(self, images: list[np.ndarray]) -> np.ndarray:
        return np.stack([self._one(im) for im in images]) if images else np.zeros((0, self.dim), np.float32)

    def _one(self, rgb: np.ndarray) -> np.ndarray:
        n = 32
        h, w = rgb.shape[:2]
        s = min(h, w)
        y0, x0 = (h - s) // 2, (w - s) // 2
        small = cv2.resize(rgb[y0:y0 + s, x0:x0 + s], (n, n), interpolation=cv2.INTER_AREA)

        # Арын дэвсгэр = захын пикселүүдийн медиан өнгө. Түүнээс ялгаатай = бараа.
        border = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]]).astype(np.float32)
        bg = np.median(border, axis=0)
        mask = np.abs(small.astype(np.float32) - bg).sum(axis=2) >= 60
        if not mask.any():
            mask[:] = True

        # Өнгө: HSV-д гэрлийн хүч (V)-ийг сул тооцож өнгөний аяс (H) ба ханалт (S)-ыг гол болгоно.
        hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
        hue, sat, val = hsv[..., 0][mask], hsv[..., 1][mask], hsv[..., 2][mask]
        # Харанхуй пикселийн өнгө (S) шахалт, шуугианаас болж тогтворгүй тул саарал гэж үзнэ.
        colored = (sat >= 50) & (val >= 60)
        hs = _soft_hist2d(hue[colored] / 180 * 10, (sat[colored].astype(np.float32) - 50) / 206 * 4, 10, 4)
        gray = _soft_hist1d(val[~colored] / 256 * 8, 8)
        color = _center(np.sqrt(np.concatenate([hs, gray]).astype(np.float32)))

        shape = mask.reshape(8, 4, 8, 4).sum(axis=(1, 3)).ravel().astype(np.float32)
        shape = _center(shape)
        return _l2(np.concatenate([color * np.sqrt(0.6), shape * np.sqrt(0.4)]))


class Dinov2Embedder:
    match_threshold = float(os.environ.get("MATCH_THRESHOLD_DINOV2", 0.6))
    duplicate_threshold = 0.97

    def __init__(self, model_id: str | None = None):
        import torch  # noqa: F401 — заавал биш сан, зөвхөн энэ загварт хэрэгтэй
        from transformers import AutoImageProcessor, AutoModel

        self.model_id = model_id or os.environ.get("DINOV2_MODEL", "facebook/dinov2-small")
        self.name = "dinov2:" + self.model_id
        self.processor = AutoImageProcessor.from_pretrained(self.model_id)
        self.model = AutoModel.from_pretrained(self.model_id).eval()
        self.dim = self.model.config.hidden_size * 2

    def embed(self, images: list[np.ndarray]) -> np.ndarray:
        import torch

        if not images:
            return np.zeros((0, self.dim), np.float32)
        out = []
        for i in range(0, len(images), 16):
            batch = self.processor(images=images[i:i + 16], return_tensors="pt")
            with torch.inference_mode():
                hidden = self.model(**batch).last_hidden_state
            # CLS токен (ерөнхий утга) + патчуудын дундаж (нарийн хэсгүүд)
            feat = torch.cat([hidden[:, 0], hidden[:, 1:].mean(dim=1)], dim=1)
            out.append(feat.numpy())
        return _l2(np.concatenate(out))


_cache: dict[str, Embedder] = {}


def get_embedder(kind: str | None = None) -> Embedder:
    kind = kind or os.environ.get("EMBEDDER", "basic")
    if kind not in _cache:
        if kind == "basic":
            _cache[kind] = BasicEmbedder()
        elif kind == "dinov2":
            _cache[kind] = Dinov2Embedder()
        else:
            raise ValueError(f"Тодорхойгүй EMBEDDER: {kind}")
    return _cache[kind]
