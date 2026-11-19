"""Бараа Толь — REST API (FastAPI).

Ажиллуулах:  uvicorn app.main:app --reload
Баримт бичиг: http://localhost:8000/docs
"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid
from pathlib import Path
from statistics import median
from typing import Literal

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Database
from .embedders import Embedder, get_embedder
from .scoring import compute_stats, value_index
from .vision import ImageError, decode_image, encode_jpeg, read_video_frames, select_scan_frames, sharpness

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 150 * 1024 * 1024
MAX_PHOTOS_PER_REQUEST = 10

SortKey = Literal["score", "value", "reviews", "fail_rate", "new"]


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    broke: bool = False
    broken_part: str = Field("", max_length=80)
    months_used: int | None = Field(None, ge=0, le=600)
    price_paid: int | None = Field(None, ge=0)
    would_buy_again: bool | None = None
    pros: str = Field("", max_length=1000)
    cons: str = Field("", max_length=1000)
    body: str = Field("", max_length=4000)
    better_alt_id: int | None = None


class VectorIndex:
    """Бүх зургийн хээг санах ойд матриц болгон барина. Шинэ зураг нэмэгдэхэд шинэчлэгдэнэ.

    Хэдэн зуун мянган зураг хүртэл хангалттай хурдан. Түүнээс олон бол pgvector/FAISS руу шилжинэ.
    """

    def __init__(self, db: Database, model: str):
        self.db, self.model = db, model
        self.lock = threading.Lock()
        self._loaded = False
        self.product_ids = np.zeros(0, np.int64)
        self.matrix = np.zeros((0, 0), np.float32)

    def invalidate(self):
        with self.lock:
            self._loaded = False

    def _load(self):
        rows = self.db.all(
            """SELECT i.product_id, e.vector FROM image_embeddings e
               JOIN product_images i ON i.id = e.image_id WHERE e.model = ?""",
            self.model,
        )
        self.product_ids = np.array([r["product_id"] for r in rows], np.int64)
        self.matrix = (
            np.stack([np.frombuffer(r["vector"], np.float32) for r in rows]) if rows else np.zeros((0, 0), np.float32)
        )
        self._loaded = True

    def search(self, queries: np.ndarray, top: int = 12) -> list[tuple[int, float]]:
        with self.lock:
            if not self._loaded:
                self._load()
            if not len(self.product_ids):
                return []
            sims = (self.matrix @ queries.T).max(axis=1)  # зураг бүрийн хамгийн их төстэй байдал
            best: dict[int, float] = {}
            for pid, s in zip(self.product_ids.tolist(), sims.tolist()):
                if s > best.get(pid, -2):
                    best[pid] = s
        return sorted(best.items(), key=lambda kv: -kv[1])[:top]


def create_app(db_path: str | Path, media_dir: str | Path, embedder: Embedder | None = None) -> FastAPI:
    db = Database(db_path)
    media = Path(media_dir)
    media.mkdir(parents=True, exist_ok=True)
    emb = embedder or get_embedder()
    index = VectorIndex(db, emb.name)

    app = FastAPI(title="Бараа Толь API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/media", StaticFiles(directory=media), name="media")
    app.state.db, app.state.index, app.state.embedder = db, index, emb

    # ---------- туслах ----------
    def get_product(pid: int) -> dict:
        p = db.one("SELECT * FROM products WHERE id = ?", pid)
        if not p:
            raise HTTPException(404, "Бараа олдсонгүй")
        return p

    def images_for(pid: int) -> list[dict]:
        rows = db.all("SELECT id, file, source FROM product_images WHERE product_id = ? ORDER BY id", pid)
        return [{"id": r["id"], "url": "/media/" + r["file"], "source": r["source"]} for r in rows]

    def category_median(category: str) -> float | None:
        prices = [r["price"] for r in db.all("SELECT price FROM products WHERE category = ? AND price > 0", category)]
        return median(prices) if prices else None

    def summarize(p: dict, cache: dict) -> dict:
        stats = compute_stats(db.all("SELECT * FROM reviews WHERE product_id = ?", p["id"]))
        if p["category"] not in cache:
            cache[p["category"]] = category_median(p["category"])
        first = db.one("SELECT file FROM product_images WHERE product_id = ? ORDER BY id LIMIT 1", p["id"])
        return {
            **p,
            "image": "/media/" + first["file"] if first else None,
            "stats": stats,
            "value": value_index(stats["score"], p["price"], cache[p["category"]]),
        }

    def neg(x):
        return -(x if x is not None else -1)

    sorters = {
        "score": lambda x: (neg(x["stats"]["score"]), -x["stats"]["review_count"]),
        "value": lambda x: (neg(x["value"]), neg(x["stats"]["score"])),
        "reviews": lambda x: -x["stats"]["review_count"],
        "fail_rate": lambda x: neg(x["stats"]["fail_rate"]),
        "new": lambda x: -x["id"],
    }

    async def read_limited(f: UploadFile, limit: int) -> bytes:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"Файл {limit // (1024 * 1024)}MB-аас бага байх ёстой")
        return data

    def store_images(pid: int, rgbs: list[np.ndarray], source: str, sharp: list[float] | None = None,
                     embs: np.ndarray | None = None) -> int:
        if embs is None:
            embs = emb.embed(rgbs)
        for i, rgb in enumerate(rgbs):
            file = f"{uuid.uuid4().hex}.jpg"
            (media / file).write_bytes(encode_jpeg(rgb))
            image_id = db.run(
                "INSERT INTO product_images (product_id, file, source, sharpness) VALUES (?, ?, ?, ?)",
                pid, file, source, sharp[i] if sharp else sharpness(rgb),
            )
            db.run("INSERT INTO image_embeddings (image_id, model, vector) VALUES (?, ?, ?)",
                   image_id, emb.name, embs[i].astype(np.float32).tobytes())
        index.invalidate()
        return len(rgbs)

    async def decode_photos(photos: list[UploadFile]) -> list[np.ndarray]:
        if len(photos) > MAX_PHOTOS_PER_REQUEST:
            raise HTTPException(400, f"Нэг удаад {MAX_PHOTOS_PER_REQUEST}-аас олонгүй зураг")
        try:
            return [decode_image(await read_limited(f, MAX_PHOTO_BYTES)) for f in photos]
        except ImageError as e:
            raise HTTPException(400, str(e))

    async def process_scan(pid: int, video: UploadFile) -> int:
        with tempfile.NamedTemporaryFile(suffix=Path(video.filename or "v.mp4").suffix or ".mp4") as tmp:
            size = 0
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(413, "Видео 150MB-аас бага байх ёстой")
                tmp.write(chunk)
            tmp.flush()
            try:
                frames = select_scan_frames(read_video_frames(tmp.name), emb)
            except ImageError as e:
                raise HTTPException(400, str(e))
        return store_images(pid, [f.rgb for f in frames], "scan", [f.sharpness for f in frames],
                            np.stack([f.embedding for f in frames]))

    # ---------- API ----------
    @app.get("/api/health")
    def health():
        return {"ok": True, "embedder": emb.name}

    @app.get("/api/categories")
    def categories():
        return db.all("SELECT category, COUNT(*) AS count FROM products GROUP BY category ORDER BY count DESC, category")

    @app.get("/api/products")
    def list_products(q: str = Query("", max_length=100), category: str = Query("", max_length=60),
                      barcode: str = Query("", max_length=32), sort: SortKey = "score"):
        sql, args = "SELECT * FROM products WHERE 1=1", []
        if q.strip():
            like = "%" + q.strip().replace("%", "").replace("_", "") + "%"
            sql += " AND (name LIKE ? OR brand LIKE ? OR model LIKE ? OR category LIKE ?)"
            args += [like] * 4
        if category:
            sql += " AND category = ?"
            args.append(category)
        if barcode:
            sql += " AND barcode = ?"
            args.append(barcode.strip())
        cache: dict = {}
        items = [summarize(p, cache) for p in db.all(sql + " ORDER BY id DESC LIMIT 200", *args)]
        return sorted(items, key=sorters[sort])

    @app.post("/api/products", status_code=201)
    async def create_product(
        name: str = Form(..., min_length=1, max_length=120),
        category: str = Form(..., min_length=1, max_length=60),
        brand: str = Form("", max_length=60),
        model: str = Form("", max_length=60),
        barcode: str = Form("", max_length=32),
        price: int | None = Form(None, ge=0),
        description: str = Form("", max_length=2000),
        photos: list[UploadFile] = File(default=[]),
        video: UploadFile | None = File(default=None),
    ):
        bc = barcode.strip() or None
        if bc and db.one("SELECT id FROM products WHERE barcode = ?", bc):
            existing = db.one("SELECT id FROM products WHERE barcode = ?", bc)
            raise HTTPException(409, {"message": "Энэ баркодтой бараа бүртгэлтэй байна", "id": existing["id"]})
        rgbs = await decode_photos(photos)
        pid = db.run(
            "INSERT INTO products (name, brand, model, category, barcode, price, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            name.strip(), brand.strip(), model.strip(), category.strip(), bc, price, description.strip(),
        )
        added = store_images(pid, rgbs, "photo") if rgbs else 0
        if video is not None and video.filename:
            added += await process_scan(pid, video)
        return {"id": pid, "images_added": added}

    @app.post("/api/products/{pid}/photos", status_code=201)
    async def add_photos(pid: int, photos: list[UploadFile] = File(...)):
        get_product(pid)
        return {"images_added": store_images(pid, await decode_photos(photos), "photo")}

    @app.post("/api/products/{pid}/scan", status_code=201)
    async def add_scan(pid: int, video: UploadFile = File(...)):
        """Барааг тал бүрээс нь бичсэн видео. Тод, өөр өнцгийн кадруудыг автоматаар сонгоно."""
        get_product(pid)
        return {"images_added": await process_scan(pid, video)}

    @app.get("/api/products/{pid}")
    def product_detail(pid: int):
        p = get_product(pid)
        cache: dict = {}
        product = summarize(p, cache)
        reviews = db.all("SELECT * FROM reviews WHERE product_id = ? ORDER BY created_at DESC, id DESC", pid)
        for r in reviews:
            alt = r["better_alt_id"] and db.one("SELECT id, name, brand, model FROM products WHERE id = ?", r["better_alt_id"])
            r["better_alt"] = alt or None

        peers = sorted((summarize(x, cache) for x in db.all("SELECT * FROM products WHERE category = ?", p["category"])),
                       key=sorters["score"])
        rank = next(i for i, x in enumerate(peers, 1) if x["id"] == pid)
        my = product["stats"]["score"] if product["stats"]["score"] is not None else -1
        better = [x for x in peers if x["id"] != pid and (x["stats"]["score"] if x["stats"]["score"] is not None else -1) > my][:4]

        instead = [
            {**summarize(get_product(r["id"]), cache), "votes": r["votes"]}
            for r in db.all(
                """SELECT better_alt_id AS id, COUNT(*) AS votes FROM reviews
                   WHERE product_id = ? AND better_alt_id IS NOT NULL
                   GROUP BY better_alt_id ORDER BY votes DESC LIMIT 5""", pid)
        ]
        return {
            "product": {**product, "images": images_for(pid)},
            "reviews": reviews,
            "rank": rank,
            "category_size": len(peers),
            "better_alternatives": better,
            "recommended_instead": instead,
        }

    @app.post("/api/products/{pid}/reviews", status_code=201)
    def add_review(pid: int, r: ReviewIn):
        get_product(pid)
        alt = r.better_alt_id
        if alt is not None and (alt == pid or not db.one("SELECT id FROM products WHERE id = ?", alt)):
            alt = None
        rid = db.run(
            """INSERT INTO reviews (product_id, rating, broke, broken_part, months_used, price_paid,
                 would_buy_again, pros, cons, body, better_alt_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            pid, r.rating, int(r.broke), r.broken_part.strip() if r.broke else "", r.months_used, r.price_paid,
            None if r.would_buy_again is None else int(r.would_buy_again),
            r.pros.strip(), r.cons.strip(), r.body.strip(), alt,
        )
        return {"id": rid}

    @app.get("/api/products/{pid}/parts")
    def broken_parts(pid: int):
        """Бусдын бичсэн эвдрэлийн нэрс — нэг ижил нэрээр бичүүлэхэд тусална."""
        return [r["part"] for r in db.all(
            "SELECT DISTINCT broken_part AS part FROM reviews WHERE product_id = ? AND broken_part != '' ORDER BY part", pid)]

    @app.post("/api/search/image")
    async def search_image(photos: list[UploadFile] = File(...), barcode: str = Form("", max_length=32)):
        """Нэг буюу хэд хэдэн зургаар хайна. Баркод өгвөл эхлээд түүгээр яг таарахыг хайна."""
        cache: dict = {}
        results = []
        if barcode.strip():
            p = db.one("SELECT * FROM products WHERE barcode = ?", barcode.strip())
            if p:
                results.append({**summarize(p, cache), "similarity": 1.0, "is_match": True, "match_by": "barcode"})
        queries = emb.embed(await decode_photos(photos))
        for pid, sim in index.search(queries):
            if any(r["id"] == pid for r in results):
                continue
            results.append({
                **summarize(get_product(pid), cache),
                "similarity": round(sim, 3),
                "is_match": sim >= emb.match_threshold,
                "match_by": "image",
            })
        return {"embedder": emb.name, "threshold": emb.match_threshold, "results": results}

    return app


def _default_app() -> FastAPI:
    data = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    return create_app(data / "baraa.db", data / "media")


app = _default_app() if os.environ.get("BARAA_NO_DEFAULT_APP") != "1" else None
