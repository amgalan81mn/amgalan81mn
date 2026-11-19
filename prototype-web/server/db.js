'use strict';
// Өгөгдлийн сан: Node-ийн суурь SQLite (нэмэлт сан хэрэггүй).
const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');
const path = require('node:path');

function openDb(file) {
  if (file !== ':memory:') fs.mkdirSync(path.dirname(file), { recursive: true });
  const db = new DatabaseSync(file);
  db.exec(`
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS products (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      name        TEXT NOT NULL,
      brand       TEXT NOT NULL DEFAULT '',
      model       TEXT NOT NULL DEFAULT '',
      category    TEXT NOT NULL,
      price       INTEGER,              -- төгрөгөөр, ойролцоо зах зээлийн үнэ
      description TEXT NOT NULL DEFAULT '',
      created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Нэг бараа олон зурагтай байж болно. Зураг бүрийн "хээ" (embedding)-г
    -- хадгалж, шинэ зурагтай харьцуулж ижил барааг олно.
    CREATE TABLE IF NOT EXISTS product_images (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      file        TEXT NOT NULL,
      emb_basic   TEXT,                 -- өнгө/хэлбэрийн энгийн хээ (JSON массив)
      emb_ml      TEXT,                 -- MobileNet хээ (JSON массив), байвал
      created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS reviews (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      rating          INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
      broke           INTEGER NOT NULL DEFAULT 0,   -- эвдэрсэн эсэх
      broken_part     TEXT NOT NULL DEFAULT '',     -- юу нь эвдэрсэн
      months_used     INTEGER,                      -- хэдэн сар хэрэглэсэн / хэдэн сард эвдэрсэн
      price_paid      INTEGER,
      would_buy_again INTEGER,                      -- 1 / 0 / NULL
      pros            TEXT NOT NULL DEFAULT '',
      cons            TEXT NOT NULL DEFAULT '',
      body            TEXT NOT NULL DEFAULT '',
      better_alt_id   INTEGER REFERENCES products(id) ON DELETE SET NULL, -- "энэ илүү дээр байсан"
      created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
    CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
    CREATE INDEX IF NOT EXISTS idx_images_product ON product_images(product_id);
  `);
  return db;
}

module.exports = { openDb };
