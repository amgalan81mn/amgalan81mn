import { fileToImage, imageToDataUrl, computeEmbeddings, loadModel } from './imagefeatures.js';

const app = document.getElementById('app');

// ---------- жижиг туслахууд ----------
class Raw { constructor(s) { this.s = s; } }
const raw = (s) => new Raw(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => {
    const part = Array.isArray(v) ? v.map((x) => (x instanceof Raw ? x.s : esc(x))).join('')
      : v instanceof Raw ? v.s : esc(v);
    out += part + strings[i + 1];
  });
  return raw(out);
}
const render = (r) => { app.innerHTML = r.s; window.scrollTo(0, 0); };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json' },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Алдаа гарлаа');
  return data;
}

const fmtMoney = (n) => (n ? Number(n).toLocaleString('mn-MN') + '₮' : '—');
const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const stars = (n) => '★'.repeat(Math.round(n)) + '☆'.repeat(5 - Math.round(n));
const scoreClass = (s) => (s === null ? '' : s >= 70 ? 'good' : s >= 50 ? 'mid' : 'bad');
const failClass = (f) => (f === null ? '' : f >= 0.3 ? 'bad' : f >= 0.12 ? 'mid' : 'good');
const confText = { none: 'Сэтгэгдэл алга', low: 'Өгөгдөл бага', medium: 'Дунд зэрэг итгэлтэй', high: 'Итгэлтэй' };

// Зургаар хайсны дараа "бараа нэмэх" рүү шилжихэд зургийг дамжуулах
let pendingImage = null;
let lastSearch = null;

// ---------- бүрэлдэхүүн ----------
function productCard(p, extra = '') {
  const s = p.stats;
  return html`<a class="card pcard" href="#/p/${p.id}">
    ${raw(extra)}
    <div class="thumb">${p.image ? html`<img src="${p.image}" alt="" loading="lazy">` : '📦'}</div>
    <div class="name">${p.name}</div>
    <div class="muted small">${[p.brand, p.model].filter(Boolean).join(' · ') || p.category} · ${fmtMoney(p.price)}</div>
    <div class="row">
      <span class="badge ${scoreClass(s.score)}">Оноо ${s.score ?? '—'}</span>
      ${s.reviewCount
        ? html`<span class="badge ${failClass(s.failRate)}">Эвдрэл ${pct(s.failRate)}</span>
               <span class="muted small">${s.reviewCount} сэтгэгдэл</span>`
        : html`<span class="muted small">Сэтгэгдэл алга</span>`}
    </div>
    ${s.topBrokenParts[0] ? html`<div class="small" style="color:var(--bad)">⚠ Ихэвчлэн: ${s.topBrokenParts[0].part}</div>` : ''}
  </a>`;
}

// ---------- хуудсууд ----------
async function homePage(params) {
  const category = params.get('category') || '';
  const sort = params.get('sort') || 'score';
  const term = params.get('q') || '';
  render(html`<div class="spinner">Ачаалж байна…</div>`);
  const [cats, list] = await Promise.all([
    api('/api/categories'),
    api(`/api/products?${new URLSearchParams({ category, sort, q: term })}`),
  ]);

  const link = (over) => '#/?' + new URLSearchParams({ q: term, category, sort, ...over });
  render(html`
    <section class="card hero">
      <h1>Худалдаж авахаасаа өмнө шалга</h1>
      <p class="muted">Авах гэж буй барааныхаа зургийг оруул. Бусад хэрэглэгчид түүнийг хэр удаан хэрэглэсэн,
        юу нь эвдэрсэн, аль нь илүү дээр байсныг харуулна.</p>
      <label class="drop" id="drop">
        <input type="file" accept="image/*" id="photo">
        <div class="big">📷</div>
        <b>Зургаар хайх</b>
        <div class="muted small">Зураг аваад эсвэл сонгоод оруулна уу</div>
      </label>
      <form class="searchbar" id="sf">
        <input name="q" placeholder="Эсвэл нэрээр хайх: төмс арилгагч, индүү, гутал…" value="${term}">
        <button>Хайх</button>
      </form>
    </section>

    <h2>${category ? `"${category}" ангиллын жагсаалт` : 'Шилдэг бараанууд'}</h2>
    <div class="chips">
      <a class="chip ${category ? '' : 'on'}" href="${link({ category: '' })}">Бүгд</a>
      ${cats.map((c) => html`<a class="chip ${c.category === category ? 'on' : ''}" href="${link({ category: c.category })}">${c.category} (${c.count})</a>`)}
    </div>
    <div class="row" style="margin-bottom:12px">
      <span class="muted small">Эрэмбэлэх:</span>
      <select id="sort">
        ${[['score', 'Нийт оноо'], ['value', 'Үнэ цэнэ (үнэдээ хүрсэн)'], ['reviews', 'Сэтгэгдлийн тоо'], ['failRate', 'Хамгийн их эвдэрдэг'], ['new', 'Шинээр нэмэгдсэн']]
          .map(([v, t]) => html`<option value="${v}" ${raw(v === sort ? 'selected' : '')}>${t}</option>`)}
      </select>
    </div>
    ${list.length
      ? html`<div class="grid">${list.map((p, i) => productCard(p, category ? `<span class="rankno">#${i + 1}</span>` : ''))}</div>`
      : html`<div class="card muted">Бараа олдсонгүй. <a href="#/add">Шинээр нэмэх үү?</a></div>`}
  `);

  document.getElementById('sf').onsubmit = (e) => {
    e.preventDefault();
    location.hash = link({ q: new FormData(e.target).get('q').trim() });
  };
  document.getElementById('sort').onchange = (e) => { location.hash = link({ sort: e.target.value }); };
  setupDrop(document.getElementById('drop'), document.getElementById('photo'), photoSearch);
  loadModel(); // зураг сонгохоос өмнө загварыг урьдчилан ачаалж эхэлнэ
}

function setupDrop(drop, input, onFile) {
  input.onchange = () => input.files[0] && onFile(input.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]);
  };
}

async function prepareImage(file) {
  const img = await fileToImage(file);
  const dataUrl = imageToDataUrl(img);
  const { embBasic, embMl } = await computeEmbeddings(img);
  return { dataUrl, embBasic, embMl };
}

async function photoSearch(file) {
  render(html`<div class="spinner">Зургийг шинжилж байна…<br><span class="small">Анх удаа бол зураг таних загвар ачаалагдахад хэдэн секунд болно.</span></div>`);
  try {
    const prepared = await prepareImage(file);
    pendingImage = prepared;
    const results = await api('/api/search/image', { method: 'POST', body: { embBasic: prepared.embBasic, embMl: prepared.embMl } });
    lastSearch = { prepared, results };
    if (location.hash === '#/search') searchPage();
    else location.hash = '#/search';
  } catch (e) {
    render(html`<div class="card err">${e.message}</div>`);
  }
}

function searchPage() {
  if (!lastSearch) { location.hash = '#/'; return; }
  const { prepared, results } = lastSearch;
  {
    const matches = results.filter((r) => r.isMatch);
    const similar = results.filter((r) => !r.isMatch).slice(0, 8);

    render(html`
      <div class="card row" style="gap:16px">
        <img src="${prepared.dataUrl}" alt="Таны зураг" style="width:120px;border-radius:8px">
        <div>
          <h1 style="margin:0">Зургаар хайсан үр дүн</h1>
          ${prepared.embMl ? '' : html`<div class="muted small">Ухаалаг зураг таних загвар ачаалагдаагүй тул зөвхөн маш төстэй зургийг олно.</div>`}
          <div class="row" style="margin-top:8px">
            <a class="btn" href="#/add">Энэ барааг шинээр нэмэх</a>
            <a class="btn ghost" href="#/">Дахин хайх</a>
          </div>
        </div>
      </div>
      ${matches.length ? html`
        <h2>Яг энэ бараа байж магадгүй</h2>
        <div class="grid">${matches.map((p) => productCard(p, `<span class="rankno">${Math.round(p.similarity * 100)}% ижил</span>`))}</div>` : html`
        <div class="info">Яг энэ бараа манай санд хараахан алга. Та хамгийн түрүүнд нэмж, бусдад туслаарай!</div>`}
      ${similar.length ? html`
        <h2>Төстэй бараанууд</h2>
        <div class="grid">${similar.map((p) => productCard(p, `<span class="rankno">${Math.max(0, Math.round(p.similarity * 100))}%</span>`))}</div>` : ''}
    `);
  }
}

async function productPage(id) {
  render(html`<div class="spinner">Ачаалж байна…</div>`);
  const d = await api('/api/products/' + id);
  const p = d.product;
  const s = p.stats;
  const maxPart = s.topBrokenParts[0]?.count || 1;

  render(html`
    <div class="card phead">
      <div>
        <div class="thumb" style="aspect-ratio:1">${p.images[0] ? html`<img id="mainimg" src="${p.images[0].url}" alt="${p.name}">` : '📦'}</div>
        ${p.images.length > 1 ? html`<div class="gallery">${p.images.map((i) => html`<img src="${i.url}" alt="" data-full="${i.url}">`)}</div>` : ''}
        <label class="btn ghost small" style="margin-top:8px">
          + Өөр өнцгөөс зураг нэмэх <input type="file" accept="image/*" id="addimg" hidden>
        </label>
      </div>
      <div>
        <div class="muted small"><a href="#/?category=${encodeURIComponent(p.category)}">${p.category}</a></div>
        <h1>${p.name}</h1>
        <div class="muted">${[p.brand, p.model, 'Ойролцоо үнэ ' + fmtMoney(p.price)].filter(Boolean).join(' · ')}</div>
        <div class="row" style="gap:16px;margin-top:14px">
          <div class="score ${scoreClass(s.score) || 'stat'}">${s.score ?? '?'}<small>/100</small></div>
          <div>
            <div><b>Ангилалдаа ${d.rank}/${d.categorySize}-р байр</b></div>
            <div class="muted small">${confText[s.confidence]} · ${s.reviewCount} сэтгэгдэл</div>
            ${p.value ? html`<div class="small">Үнэ цэнэ: <b>${p.value}</b> ${p.value >= 1.1 ? '— үнэдээ хүрсэн сайн сонголт' : p.value < 0.9 ? '— үнэдээ хүрэхгүй' : '— дундаж'}</div>` : ''}
          </div>
        </div>
        ${s.failRate !== null && s.failRate >= 0.3 && s.reviewCount >= 3 ? html`
          <div class="warn"><b>⚠ Анхааруулга:</b> Хэрэглэгчдийн ${pct(s.failRate)} нь энэ бараа эвдэрсэн гэж мэдээлсэн${s.topBrokenParts[0] ? html` — ихэвчлэн <b>${s.topBrokenParts[0].part}</b>` : ''}.</div>` : ''}
        <div class="stats">
          <div class="stat"><b>${s.avgRating ? s.avgRating.toFixed(1) + ' ★' : '—'}</b><span>Дундаж үнэлгээ</span></div>
          <div class="stat"><b class="${failClass(s.failRate)}" style="background:none">${pct(s.failRate)}</b><span>Эвдэрсэн гэсэн</span></div>
          <div class="stat"><b>${s.medianMonthsToFail !== null ? s.medianMonthsToFail + ' сар' : '—'}</b><span>Эвдрэх хүртэлх хугацаа (медиан)</span></div>
          <div class="stat"><b>${pct(s.buyAgainRate)}</b><span>Дахин авна гэсэн</span></div>
        </div>
        <div class="row" style="margin-top:16px">
          <a class="btn" href="#/p/${p.id}/review">Өөрийн туршлагаа бичих</a>
        </div>
      </div>
    </div>

    ${p.description ? html`<p>${p.description}</p>` : ''}

    ${s.topBrokenParts.length ? html`
      <h2>Юу нь ихэвчлэн эвдэрдэг вэ?</h2>
      <div class="card bars">
        ${s.topBrokenParts.map((b) => html`<div class="bar"><span>${b.part}</span>
          <div class="track"><div class="fill" style="width:${Math.round((b.count / maxPart) * 100)}%"></div></div>
          <span class="muted small">${b.count} удаа</span></div>`)}
      </div>` : ''}

    ${d.recommendedInstead.length ? html`
      <h2>Хэрэглэгчид оронд нь санал болгосон</h2>
      <div class="grid">${d.recommendedInstead.map((x) => productCard(x, `<span class="rankno">${x.votes} хүн</span>`))}</div>` : ''}

    ${d.betterAlternatives.length ? html`
      <h2>Энэ ангилалд илүү өндөр үнэлгээтэй</h2>
      <div class="grid">${d.betterAlternatives.map((x) => productCard(x))}</div>` : ''}

    <h2>Хэрэглэгчдийн туршлага (${d.reviews.length})</h2>
    ${d.reviews.length ? d.reviews.map(reviewView) : html`<div class="card muted">Одоогоор сэтгэгдэл алга. Анхны сэтгэгдлийг та бичээрэй.</div>`}
  `);

  document.querySelectorAll('.gallery img').forEach((im) => {
    im.onclick = () => { document.getElementById('mainimg').src = im.dataset.full; };
  });
  document.getElementById('addimg').onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const prep = await prepareImage(f);
      await api(`/api/products/${p.id}/images`, { method: 'POST', body: { image: prep.dataUrl, embBasic: prep.embBasic, embMl: prep.embMl } });
      productPage(p.id);
    } catch (err) { alert(err.message); }
  };
}

function reviewView(r) {
  return html`<div class="card review">
    <div class="row" style="justify-content:space-between">
      <span class="stars" aria-label="${r.rating} од">${stars(r.rating)}</span>
      <span class="muted small">${r.created_at.slice(0, 10)}</span>
    </div>
    <div class="row">
      ${r.broke ? html`<span class="badge bad">Эвдэрсэн${r.broken_part ? ': ' + r.broken_part : ''}${r.months_used !== null ? ` (${r.months_used} сард)` : ''}</span>`
        : html`<span class="badge good">Эвдрээгүй${r.months_used !== null ? ` · ${r.months_used} сар хэрэглэсэн` : ''}</span>`}
      ${r.would_buy_again === 1 ? html`<span class="badge good">Дахин авна</span>` : r.would_buy_again === 0 ? html`<span class="badge bad">Дахин авахгүй</span>` : ''}
      ${r.price_paid ? html`<span class="muted small">${fmtMoney(r.price_paid)}-өөр авсан</span>` : ''}
    </div>
    ${r.pros ? html`<div><b style="color:var(--good)">+</b> ${r.pros}</div>` : ''}
    ${r.cons ? html`<div><b style="color:var(--bad)">−</b> ${r.cons}</div>` : ''}
    ${r.body ? html`<div>${r.body}</div>` : ''}
    ${r.better_alt ? html`<div class="small">👉 Илүү дээр нь: <a href="#/p/${r.better_alt.id}">${[r.better_alt.brand, r.better_alt.name, r.better_alt.model].filter(Boolean).join(' ')}</a></div>` : ''}
  </div>`;
}

async function addPage() {
  const cats = await api('/api/categories');
  const img = pendingImage;
  render(html`
    <h1>Шинэ бараа нэмэх</h1>
    <p class="muted">Нэг бараа давхардахгүйн тулд эхлээд <a href="#/">зургаар хайж</a> үзээрэй.</p>
    <form class="card" id="f">
      <div class="field">
        <label class="lbl">Зураг</label>
        <label class="drop" id="drop">
          <input type="file" accept="image/*" id="photo">
          ${img ? html`<img class="preview" src="${img.dataUrl}" alt="">` : html`<div class="big">📷</div>`}
          <div class="muted small">${img ? 'Өөр зураг сонгох' : 'Барааны зураг (заавал биш, гэхдээ зургаар хайхад хэрэгтэй)'}</div>
        </label>
      </div>
      <div class="field"><label class="lbl" for="name">Барааны нэр *</label>
        <input id="name" name="name" required maxlength="120" placeholder="ж: Төмс арилгагч"></div>
      <div class="two">
        <div class="field"><label class="lbl" for="brand">Брэнд / үйлдвэрлэгч</label><input id="brand" name="brand" maxlength="60"></div>
        <div class="field"><label class="lbl" for="model">Загвар / модель</label><input id="model" name="model" maxlength="60"></div>
      </div>
      <div class="two">
        <div class="field"><label class="lbl" for="category">Ангилал *</label>
          <input id="category" name="category" required maxlength="60" list="cats" placeholder="ж: Гал тогооны хэрэгсэл">
          <datalist id="cats">${cats.map((c) => html`<option value="${c.category}">`)}</datalist></div>
        <div class="field"><label class="lbl" for="price">Ойролцоо үнэ (₮)</label><input id="price" name="price" type="number" min="0" step="100"></div>
      </div>
      <div class="field"><label class="lbl" for="description">Тайлбар</label>
        <textarea id="description" name="description" maxlength="2000" placeholder="Хаанаас авч болох, ямар хэмжээтэй гэх мэт"></textarea></div>
      <div id="msg"></div>
      <button>Хадгалах</button>
    </form>
  `);

  setupDrop(document.getElementById('drop'), document.getElementById('photo'), async (file) => {
    document.getElementById('msg').textContent = 'Зургийг боловсруулж байна…';
    pendingImage = await prepareImage(file);
    addPage();
  });

  document.getElementById('f').onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button');
    btn.disabled = true;
    const fd = Object.fromEntries(new FormData(e.target));
    try {
      const body = { ...fd, price: fd.price || null };
      if (pendingImage) Object.assign(body, { image: pendingImage.dataUrl, embBasic: pendingImage.embBasic, embMl: pendingImage.embMl });
      const { id } = await api('/api/products', { method: 'POST', body });
      pendingImage = null;
      location.hash = `#/p/${id}/review`;
    } catch (err) {
      document.getElementById('msg').innerHTML = html`<p class="err">${err.message}</p>`.s;
      btn.disabled = false;
    }
  };
}

async function reviewPage(id) {
  const d = await api('/api/products/' + id);
  const p = d.product;
  const [peers, parts] = await Promise.all([
    api('/api/products?' + new URLSearchParams({ category: p.category })),
    api('/api/parts?productId=' + p.id),
  ]);
  const state = { rating: 0, broke: null, wouldBuyAgain: null };

  render(html`
    <a href="#/p/${p.id}">← ${p.name}</a>
    <h1>Таны туршлага</h1>
    <p class="muted">Үнэн бодит туршлага чинь дараагийн хэрэглэгчийг хохирохоос сэргийлнэ.</p>
    <form class="card" id="f">
      <div class="field"><span class="lbl">Ерөнхий үнэлгээ *</span>
        <div class="starpick" id="stars">${[1, 2, 3, 4, 5].map((n) => html`<button type="button" data-v="${n}" aria-label="${n} од">★</button>`)}</div></div>
      <div class="field"><span class="lbl">Эвдэрсэн үү?</span>
        <div class="seg" id="broke"><button type="button" data-v="0">Үгүй, сайн ажиллаж байна</button><button type="button" data-v="1">Тийм, эвдэрсэн</button></div></div>
      <div class="field" id="partbox" hidden><label class="lbl" for="brokenPart">Юу нь эвдэрсэн бэ?</label>
        <input id="brokenPart" name="brokenPart" maxlength="80" list="parts" placeholder="ж: ир нь мохорсон, бариул хугарсан">
        <datalist id="parts">${parts.map((x) => html`<option value="${x}">`)}</datalist>
        ${parts.length ? html`<span class="muted small">Бусад хэрэглэгчдийн бичсэн: ${parts.join(', ')}</span>` : ''}</div>
      <div class="two">
        <div class="field"><label class="lbl" for="monthsUsed" id="mlabel">Хэдэн сар хэрэглэсэн бэ?</label><input id="monthsUsed" name="monthsUsed" type="number" min="0" max="600"></div>
        <div class="field"><label class="lbl" for="pricePaid">Хэдээр авсан бэ? (₮)</label><input id="pricePaid" name="pricePaid" type="number" min="0" step="100"></div>
      </div>
      <div class="field"><span class="lbl">Дахин худалдаж авах уу?</span>
        <div class="seg" id="again"><button type="button" data-v="1">Тийм</button><button type="button" data-v="0">Үгүй</button></div></div>
      <div class="field"><label class="lbl" for="pros">Давуу тал</label><input id="pros" name="pros" maxlength="1000"></div>
      <div class="field"><label class="lbl" for="cons">Сул тал</label><input id="cons" name="cons" maxlength="1000"></div>
      <div class="field"><label class="lbl" for="body">Дэлгэрэнгүй</label><textarea id="body" name="body" maxlength="4000"></textarea></div>
      <div class="field"><label class="lbl" for="betterAltId">Энэ ангилалд илүү дээр гэж бодсон бараа байна уу?</label>
        <select id="betterAltId" name="betterAltId"><option value="">— Байхгүй / мэдэхгүй —</option>
          ${peers.filter((x) => x.id !== p.id).map((x) => html`<option value="${x.id}">${[x.brand, x.name, x.model].filter(Boolean).join(' ')}</option>`)}
        </select>
        <span class="muted small">Жагсаалтад байхгүй бол эхлээд <a href="#/add">тэр барааг нэмээрэй</a>.</span></div>
      <div id="msg"></div>
      <button id="submit">Илгээх</button>
    </form>
  `);

  const pickOne = (boxId, key, onPick) => {
    const box = document.getElementById(boxId);
    box.querySelectorAll('button').forEach((b) => {
      b.onclick = () => {
        state[key] = Number(b.dataset.v);
        box.querySelectorAll('button').forEach((x) => x.classList.toggle('on', boxId === 'stars' ? Number(x.dataset.v) <= state[key] : x === b));
        onPick?.();
      };
    });
  };
  pickOne('stars', 'rating');
  pickOne('again', 'wouldBuyAgain');
  pickOne('broke', 'broke', () => {
    document.getElementById('partbox').hidden = state.broke !== 1;
    document.getElementById('mlabel').textContent = state.broke === 1 ? 'Хэдэн сарын дараа эвдэрсэн бэ?' : 'Хэдэн сар хэрэглэсэн бэ?';
  });

  document.getElementById('f').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('msg');
    if (!state.rating) { msg.innerHTML = '<p class="err">Од дарж үнэлгээ өгнө үү.</p>'; return; }
    const fd = Object.fromEntries(new FormData(e.target));
    const btn = document.getElementById('submit');
    btn.disabled = true;
    try {
      await api(`/api/products/${p.id}/reviews`, {
        method: 'POST',
        body: {
          ...fd,
          rating: state.rating,
          broke: state.broke === 1,
          wouldBuyAgain: state.wouldBuyAgain === null ? null : state.wouldBuyAgain === 1,
        },
      });
      location.hash = `#/p/${p.id}`;
    } catch (err) {
      msg.innerHTML = html`<p class="err">${err.message}</p>`.s;
      btn.disabled = false;
    }
  };
}

function aboutPage() {
  render(html`
    <div class="card">
      <h1>Бидний зорилго</h1>
      <p>Хэрэглэгч бүр худалдаж авахаасаа өмнө тухайн бараа <b>хэр удаан эдэлгээтэй, юу нь эвдэрдэг,
        аль нь үнэдээ хүрсэн</b> болохыг бусдын бодит туршлагаас мэдэх ёстой.</p>
      <p>Мэдээлэлтэй хэрэглэгч чанаргүй бараа авахаа болино. Ингэснээр:</p>
      <ol>
        <li>Амархан эвдэрдэг бараа зарагдахаа больж, худалдагч дахин захиалахаа болино.</li>
        <li>Үйлдвэрлэгч зах зээлээ алдахгүйн тулд <b>чанартай бараа</b> хийхийг зорино.</li>
        <li>Шударга, цэвэр өрсөлдөөн бий болно.</li>
        <li>Эвдэрсэн бараа хаягдал болдоггүй тул <b>байгаль орчинд ч ээлтэй</b>.</li>
      </ol>
      <h2>Оноо хэрхэн бодогддог вэ?</h2>
      <p class="muted">Оноо (0–100) = сэтгэл ханамж 50% + эвдрэхгүй байх магадлал 50%. Цөөн сэтгэгдэлтэй
        бараа азаар дээгүүр гарахгүйн тулд эхэндээ "дунд зэрэг" гэж үзээд, сэтгэгдэл нэмэгдэх тусам бодит
        дүн рүү ойртдог. Үнэ цэнэ нь тухайн ангиллын дундаж үнэтэй харьцуулсан оноо юм.</p>
      <h2>Удахгүй</h2>
      <ul class="muted">
        <li>Гомдол барагдуулах туслах: хууль ёсны эрх, гомдлын бичгийн загвар, хаана хандах</li>
        <li>Худалдан авалтаа баталгаажуулсан сэтгэгдэл (баримтын зураг)</li>
        <li>Хуурамч сэтгэгдэл илрүүлэх</li>
        <li>Дэлгүүр, худалдагчийн үнэлгээ</li>
      </ul>
    </div>
  `);
}

// ---------- чиглүүлэгч ----------
async function route() {
  const [path, query = ''] = location.hash.replace(/^#/, '').split('?');
  const params = new URLSearchParams(query);
  let m;
  try {
    if ((m = path.match(/^\/p\/(\d+)\/review$/))) await reviewPage(m[1]);
    else if ((m = path.match(/^\/p\/(\d+)$/))) await productPage(m[1]);
    else if (path === '/search') searchPage();
    else if (path === '/add') await addPage();
    else if (path === '/about') aboutPage();
    else await homePage(params);
  } catch (e) {
    render(html`<div class="card err">${e.message}</div>`);
  }
}
window.addEventListener('hashchange', route);
route();
