// Зургийн "хээ" (embedding) тооцоолох — бүгд хэрэглэгчийн хөтөч дээр ажиллана.
//
// 1) basicEmbedding: өнгөний тархалт + хэлбэрийн бүдүүвч. Интернэтгүй ч ажилладаг,
//    гэхдээ зөвхөн маш төстэй зургийг л найдвартай таньна.
// 2) mlEmbedding: MobileNet (TensorFlow.js) — зургийн агуулгыг "ойлгодог" тул
//    өөр өнцгөөс авсан ижил барааг ч олох чадвартай. CDN-ээс ачаалагдана.

const TFJS_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js';
const MOBILENET_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/mobilenet@2.1.1/dist/mobilenet.min.js';

export function fileToImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Зургийг уншиж чадсангүй')); };
    img.src = url;
  });
}

/** Хадгалахад зориулж зургийг багасгаж JPEG болгоно. */
export function imageToDataUrl(img, maxSide = 900) {
  const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
  const c = document.createElement('canvas');
  c.width = Math.round(img.naturalWidth * scale);
  c.height = Math.round(img.naturalHeight * scale);
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.85);
}

function squareCrop(img, size) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  const s = Math.min(img.naturalWidth, img.naturalHeight);
  const sx = (img.naturalWidth - s) / 2;
  const sy = (img.naturalHeight - s) / 2;
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, size, size);
  ctx.drawImage(img, sx, sy, s, s, 0, 0, size, size);
  return ctx.getImageData(0, 0, size, size).data;
}

function centerAndNormalize(v) {
  const mean = v.reduce((a, x) => a + x, 0) / v.length;
  const out = v.map((x) => x - mean);
  const norm = Math.sqrt(out.reduce((a, x) => a + x * x, 0)) || 1;
  return out.map((x) => x / norm);
}

export function basicEmbedding(img) {
  const N = 32;
  const px = squareCrop(img, N);

  // Арын дэвсгэрийн өнгө = захын пикселүүдийн дундаж. Түүнээс ялгаатай пиксел = бараа.
  let br = 0, bg = 0, bb = 0, bn = 0;
  for (let i = 0; i < N; i++) {
    for (const [x, y] of [[i, 0], [i, N - 1], [0, i], [N - 1, i]]) {
      const k = (y * N + x) * 4;
      br += px[k]; bg += px[k + 1]; bb += px[k + 2]; bn++;
    }
  }
  br /= bn; bg /= bn; bb /= bn;

  const hist = new Array(64).fill(0); // барааны өнгө (RGB тус бүр 4 түвшин)
  const shape = new Array(64).fill(0); // 8x8 барааны дүрс
  let fg = 0;
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const k = (y * N + x) * 4;
      const r = px[k], g = px[k + 1], b = px[k + 2];
      const d = Math.abs(r - br) + Math.abs(g - bg) + Math.abs(b - bb);
      if (d < 60) continue;
      fg++;
      hist[(r >> 6) * 16 + (g >> 6) * 4 + (b >> 6)] += 1;
      shape[(y >> 2) * 8 + (x >> 2)] += 1;
    }
  }
  if (fg === 0) { hist[0] = 1; shape[0] = 1; }
  const h = centerAndNormalize(hist.map(Math.sqrt));
  const sh = centerAndNormalize(shape);
  // Өнгө 60%, дүрс 40% жинтэй
  return [...h.map((x) => x * Math.sqrt(0.6)), ...sh.map((x) => x * Math.sqrt(0.4))];
}

let modelPromise = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.crossOrigin = 'anonymous';
    s.onload = resolve;
    s.onerror = () => reject(new Error('Скрипт ачаалагдсангүй: ' + src));
    document.head.appendChild(s);
  });
}

function withTimeout(p, ms) {
  return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms))]);
}

export function loadModel() {
  if (!modelPromise) {
    modelPromise = withTimeout((async () => {
      if (!window.tf) await loadScript(TFJS_URL);
      if (!window.mobilenet) await loadScript(MOBILENET_URL);
      return window.mobilenet.load({ version: 2, alpha: 1.0 });
    })(), 30000).catch((e) => {
      console.warn('MobileNet ачаалагдсангүй, энгийн хээ ашиглана:', e);
      return null;
    });
  }
  return modelPromise;
}

export async function mlEmbedding(img) {
  const model = await loadModel();
  if (!model) return null;
  return window.tf.tidy(() => Array.from(model.infer(img, true).dataSync()));
}

/** Хоёр төрлийн хээг хамт буцаана. */
export async function computeEmbeddings(img) {
  const embBasic = basicEmbedding(img);
  let embMl = null;
  try { embMl = await mlEmbedding(img); } catch (e) { console.warn(e); }
  return { embBasic, embMl };
}
