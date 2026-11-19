"""SQLite өгөгдлийн сан.

MVP-д SQLite хангалттай. Бараа олширвол PostgreSQL + pgvector руу шилжинэ
(схем нь ижил, зөвхөн embedding баганын төрөл өөрчлөгдөнө).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    brand       TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL,
    barcode     TEXT,                       -- EAN/UPC: байвал хамгийн найдвартай таних арга
    price       INTEGER,                    -- төгрөгөөр, ойролцоо зах зээлийн үнэ
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode) WHERE barcode IS NOT NULL;

-- Барааны зураг. Видео скан хийхэд олон өнцгийн кадр энд хадгалагдана.
CREATE TABLE IF NOT EXISTS product_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    file        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'photo',   -- 'photo' | 'scan'
    sharpness   REAL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_images_product ON product_images(product_id);

-- Зургийн хээ. Загвар бүр өөрийн хээтэй тул загвар солиход дахин тооцоолж болно.
CREATE TABLE IF NOT EXISTS image_embeddings (
    image_id    INTEGER NOT NULL REFERENCES product_images(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    vector      BLOB NOT NULL,                   -- float32, L2-нормчилсон
    PRIMARY KEY (image_id, model)
);

CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rating          INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    broke           INTEGER NOT NULL DEFAULT 0,
    broken_part     TEXT NOT NULL DEFAULT '',
    months_used     INTEGER,
    price_paid      INTEGER,
    would_buy_again INTEGER,
    pros            TEXT NOT NULL DEFAULT '',
    cons            TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    better_alt_id   INTEGER REFERENCES products(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
"""


class Database:
    """Нэг холболт + түгжээ. MVP-ийн ачаалалд хангалттай."""

    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def all(self, sql: str, *args) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, *args) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def run(self, sql: str, *args) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid
