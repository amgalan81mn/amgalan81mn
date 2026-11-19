'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createApp } = require('../server/index');
const { computeStats, cosine } = require('../server/scoring');

// 1x1 PNG
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

let server, base, tmp;
before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'baraa-'));
  const app = createApp({ dbFile: ':memory:', uploadsDir: path.join(tmp, 'uploads') });
  await new Promise((r) => { server = app.listen(0, r); });
  base = `http://127.0.0.1:${server.address().port}`;
});
after(() => { server.close(); fs.rmSync(tmp, { recursive: true, force: true }); });

const post = (p, body) => fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const get = (p) => fetch(base + p).then((r) => r.json());

test('scoring: эвдэрдэг бараа доогуур оноотой, эвдрэлийн хэсгийг тоолно', () => {
  const bad = computeStats([
    { rating: 2, broke: 1, broken_part: 'Ир ', months_used: 2 },
    { rating: 1, broke: 1, broken_part: 'ир', months_used: 4 },
    { rating: 2, broke: 1, broken_part: 'бариул', months_used: 3 },
  ]);
  const good = computeStats([
    { rating: 5, broke: 0 }, { rating: 4, broke: 0 }, { rating: 5, broke: 0 },
  ]);
  assert.ok(good.score > bad.score);
  assert.equal(bad.failRate, 1);
  assert.deepEqual(bad.topBrokenParts[0], { part: 'ир', count: 2, share: 2 / 3 });
  assert.equal(bad.medianMonthsToFail, 3);
  assert.equal(computeStats([]).score, null);
});

test('cosine', () => {
  assert.equal(cosine([1, 0], [1, 0]), 1);
  assert.equal(cosine([1, 0], [0, 1]), 0);
  assert.equal(cosine([1], [1, 2]), null);
});

test('бараа нэмэх, сэтгэгдэл, оронд нь санал болгох, зургаар хайх', async () => {
  let r = await post('/api/products', { name: 'Peeler A', category: 'Kitchen', price: 8000, image: PNG, embBasic: [1, 0, 0], embMl: [1, 0, 0, 0] });
  assert.equal(r.status, 201);
  const a = (await r.json()).id;
  r = await post('/api/products', { name: 'Peeler B', category: 'Kitchen', price: 15000, image: PNG, embBasic: [0, 1, 0], embMl: [0, 1, 0, 0] });
  const b = (await r.json()).id;

  for (let i = 0; i < 3; i++) {
    r = await post(`/api/products/${a}/reviews`, { rating: 2, broke: true, brokenPart: 'blade', monthsUsed: 2, betterAltId: b, wouldBuyAgain: false });
    assert.equal(r.status, 201);
    await post(`/api/products/${b}/reviews`, { rating: 5, broke: false, monthsUsed: 12, wouldBuyAgain: true });
  }

  const d = await get(`/api/products/${a}`);
  assert.equal(d.product.stats.failRate, 1);
  assert.equal(d.product.stats.topBrokenParts[0].part, 'blade');
  assert.equal(d.rank, 2);
  assert.equal(d.betterAlternatives[0].id, b);
  assert.equal(d.recommendedInstead[0].id, b);
  assert.equal(d.recommendedInstead[0].votes, 3);
  assert.equal(d.product.images.length, 1);

  const list = await get('/api/products?category=Kitchen');
  assert.deepEqual(list.map((x) => x.id), [b, a]);

  // ML хээгээр хайхад A хамгийн түрүүнд, "ижил" гэж тэмдэглэгдэнэ
  r = await post('/api/search/image', { embBasic: [0.1, 1, 0], embMl: [0.99, 0.05, 0, 0] });
  const found = await r.json();
  assert.equal(found[0].id, a);
  assert.equal(found[0].isMatch, true);
  assert.equal(found[1].isMatch, false);
});

test('буруу оролтыг татгалзана', async () => {
  assert.equal((await post('/api/products', { name: '', category: 'x' })).status, 400);
  assert.equal((await post('/api/products', { name: 'x', category: 'y', image: 'data:image/svg+xml;base64,PHN2Zz4=' })).status, 400);
  const { id } = await (await post('/api/products', { name: 'x', category: 'y' })).json();
  assert.equal((await post(`/api/products/${id}/reviews`, { rating: 9 })).status, 400);
  assert.equal((await post('/api/products/99999/reviews', { rating: 3 })).status, 404);
  assert.equal((await post('/api/search/image', {})).status, 400);
});
