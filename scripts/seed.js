'use strict';
// ЖИШЭЭ ӨГӨГДӨЛ — зөвхөн програмыг турших, үзүүлэхэд зориулсан зохиомол бараа, сэтгэгдэл.
// Бодит ашиглалтад оруулахдаа үүнийг ажиллуулахгүй.
const path = require('node:path');
const { openDb } = require('../server/db');

const dataDir = process.env.DATA_DIR || path.join(__dirname, '..', 'data');
const db = openDb(path.join(dataDir, 'baraa.db'));

if (db.prepare('SELECT COUNT(*) AS n FROM products').get().n > 0) {
  console.log('Сан хоосон биш тул жишээ өгөгдөл нэмсэнгүй.');
  process.exit(0);
}

const products = [
  { key: 'a', name: 'Төмс арилгагч (жишээ)', brand: 'Брэнд А', model: 'P-100', category: 'Гал тогооны хэрэгсэл', price: 8000 },
  { key: 'b', name: 'Төмс арилгагч Y хэлбэр (жишээ)', brand: 'Брэнд Б', model: 'Y-2', category: 'Гал тогооны хэрэгсэл', price: 15000 },
  { key: 'c', name: 'Ногоо хэрчигч (жишээ)', brand: 'Брэнд В', model: 'Slice', category: 'Гал тогооны хэрэгсэл', price: 25000 },
  { key: 'd', name: 'Индүү (жишээ)', brand: 'Брэнд Г', model: 'S-1200', category: 'Гэр ахуйн цахилгаан', price: 65000 },
  { key: 'e', name: 'Индүү уурын (жишээ)', brand: 'Брэнд Д', model: 'Steam Pro', category: 'Гэр ахуйн цахилгаан', price: 120000 },
];

// [rating, broke, part, months, buyAgain, betterAltKey]
const reviews = {
  a: [[2, 1, 'ир нь мохорсон', 2, 0, 'b'], [1, 1, 'бариул хугарсан', 1, 0, 'b'], [2, 1, 'ир нь мохорсон', 3, 0, null],
      [3, 0, '', 4, null, null], [2, 1, 'ир нь мохорсон', 2, 0, 'b']],
  b: [[5, 0, '', 14, 1, null], [4, 0, '', 10, 1, null], [5, 0, '', 20, 1, null], [4, 1, 'зэвэрсэн', 18, 1, null]],
  c: [[4, 0, '', 6, 1, null], [3, 1, 'хуванцар таг хагарсан', 5, 0, null], [4, 0, '', 8, 1, null]],
  d: [[2, 1, 'дулаан тохируулагч', 7, 0, 'e'], [3, 1, 'утас нь тасарсан', 11, 0, null], [2, 1, 'дулаан тохируулагч', 5, 0, 'e']],
  e: [[5, 0, '', 24, 1, null], [4, 0, '', 15, 1, null], [4, 1, 'ус гоожсон', 20, 1, null], [5, 0, '', 30, 1, null]],
};

const ids = {};
const insP = db.prepare('INSERT INTO products (name, brand, model, category, price, description) VALUES (?, ?, ?, ?, ?, ?)');
for (const p of products) {
  ids[p.key] = Number(insP.run(p.name, p.brand, p.model, p.category, p.price, 'Жишээ өгөгдөл — бодит бараа биш.').lastInsertRowid);
}
const insR = db.prepare(`INSERT INTO reviews (product_id, rating, broke, broken_part, months_used, would_buy_again, body, better_alt_id)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?)`);
for (const [key, list] of Object.entries(reviews)) {
  for (const [rating, broke, part, months, again, alt] of list) {
    insR.run(ids[key], rating, broke, part, months, again, 'Жишээ сэтгэгдэл.', alt ? ids[alt] : null);
  }
}
console.log(`Жишээ өгөгдөл нэмэгдлээ: ${products.length} бараа.`);
