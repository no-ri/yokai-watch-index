/* 妖怪さくいん（非公式ファンサイト）
 *
 * 静的サイト。docs/data/*.json を fetch してクライアント側で絞り込む（SPEC.md §10.1）。
 * API キーは一切含めない。ここは生成済み JSON を読むだけ（SPEC.md §10.1）。
 * 視聴履歴・所持メダルは localStorage のみ。サーバー送信しない（SPEC.md §10.2）。
 */
'use strict';

const PAGE = 60;                       // 一度に描く件数
const STORE_KEY = 'yokai-watch-index/v1';
const $ = (id) => document.getElementById(id);

const DB = { yokai: null, characters: null, episodes: null, segments: null, facets: null };
const INDEX = { yokai: new Map(), characters: new Map(), segsByEp: new Map() };

const state = {
  tab: 'yokai',
  y: { q: '', scope: 'both', sort: 'medallium', ownedOnly: false, facets: {}, shown: PAGE, seed: 1 },
  a: { q: '', scope: 'all', sort: 'old', unwatchedOnly: false, hideMovies: false,
       series: new Set(), years: new Set(), presence: new Set(), shown: PAGE, seed: 1 },
};

/* --- 記録（localStorage のみ。SPEC.md §10.2）------------------------------ */
const store = {
  data: { watched: [], owned: [] },
  load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        this.data.watched = Array.isArray(parsed.watched) ? parsed.watched : [];
        this.data.owned = Array.isArray(parsed.owned) ? parsed.owned : [];
      }
    } catch (e) { /* 壊れていたら初期状態で続ける */ }
    this.watched = new Set(this.data.watched);
    this.owned = new Set(this.data.owned);
  },
  save() {
    this.data.watched = [...this.watched];
    this.data.owned = [...this.owned];
    try { localStorage.setItem(STORE_KEY, JSON.stringify(this.data)); }
    catch (e) { msg('保存できませんでした。プライベートブラウズ中かもしれません。'); }
  },
  toggle(set, id) { set.has(id) ? set.delete(id) : set.add(id); this.save(); },
};

/* --- ちいさな道具 --------------------------------------------------------- */
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// 検索用の正規化。全角と半角、大文字と小文字を吸収する。
const norm = (s) => String(s ?? '').normalize('NFKC').toLowerCase();

function seededShuffle(arr, seed) {
  const out = arr.slice();
  let s = seed;
  for (let i = out.length - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const j = s % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function msg(text) { $('io-msg').textContent = text; }

/* --- 画像の代替表現（SPEC.md §10.4）-------------------------------------- */
function tribeBadge(y) {
  const label = (DB.facets?.tribe || {})[y.tribe] || y.tribe;
  if (y.tribe === 'unknown') return '<span class="badge none">種族なし</span>';
  return `<span class="badge"><i class="dot tribe-${esc(y.tribe)}"></i>${esc(label)}</span>`;
}
function attrBadge(y) {
  const label = (DB.facets?.attribute || {})[y.attribute] || y.attribute;
  if (y.attribute === 'unknown') return '';
  return `<span class="badge"><i class="diamond attr-${esc(y.attribute)}"></i>${esc(label)}</span>`;
}
function rankBadge(y) {
  const r = y.rank === 'unknown' ? 'unknown' : y.rank;
  return `<span class="badge rank rank-${esc(r)}">${y.rank === 'unknown' ? '?' : esc(y.rank)}</span>`;
}

/* ==========================================================================
 * 図鑑タブ
 * ======================================================================= */
function buildYokaiFacets() {
  const f = DB.facets;
  const groups = [
    ['tribe', '種族', Object.keys(f.tribe)],
    ['rank', 'ランク', Object.keys(f.rank)],
    ['attribute', '属性', Object.keys(f.attribute)],
    ['color', '色', Object.keys(f.color)],
    ['animal', '動物・すがた', Object.keys(f.animal)],
    ['special', 'とくべつ', Object.keys(f.special)],
    ['food', '好きなもの', Object.keys(f.food)],
    ['badfood', 'きらいなもの', Object.keys(f.badfood)],
    ['family', 'ファミリー', Object.keys(f.family)],
  ];
  $('y-facets').innerHTML = groups.map(([axis, title, values]) => {
    if (!values.length) return '';
    const items = values.map((v) => {
      const label = f[axis][v] ?? v;
      return `<label><input type="checkbox" data-axis="${esc(axis)}" value="${esc(v)}">${esc(label)}</label>`;
    }).join('');
    return `<div class="facet-group"><h3>${esc(title)}</h3><div class="facet-values">${items}</div></div>`;
  }).join('');

  $('y-facets').addEventListener('change', (ev) => {
    const el = ev.target;
    if (!el.dataset.axis) return;
    const axis = el.dataset.axis;
    const set = state.y.facets[axis] || (state.y.facets[axis] = new Set());
    el.checked ? set.add(el.value) : set.delete(el.value);
    if (!set.size) delete state.y.facets[axis];
    state.y.shown = PAGE;
    renderYokai();
  });
}

function yokaiMatchesFacets(y) {
  for (const [axis, set] of Object.entries(state.y.facets)) {
    let ok = false;
    if (axis === 'tribe') ok = set.has(y.tribe);
    else if (axis === 'rank') ok = set.has(y.rank);
    else if (axis === 'attribute') ok = set.has(y.attribute);
    else if (axis === 'family') ok = set.has(y.family);
    else ok = y.categories.some((c) => set.has(c));  // 色・動物・とくべつ・好物
    if (!ok) return false;
  }
  return true;
}

const RANK_ORDER = { E: 0, D: 1, C: 2, B: 3, A: 4, S: 5, SS: 6, unknown: 9 };

function filterYokai() {
  const q = norm(state.y.q).trim();
  const scope = state.y.scope;
  let out = DB.yokai.filter((y) => {
    if (state.y.ownedOnly && !store.owned.has(y.yokai_id)) return false;
    if (!yokaiMatchesFacets(y)) return false;
    if (!q) return true;
    const ja = scope !== 'en' ? norm(y.name_ja) : '';
    const en = scope !== 'ja' ? norm(y.name_en) + ' ' + norm(y.yokai_id) : '';
    return ja.includes(q) || en.includes(q);
  });

  const sort = state.y.sort;
  if (sort === 'random') return seededShuffle(out, state.y.seed);
  out.sort((a, b) => {
    if (sort === 'name') return a.name_ja.localeCompare(b.name_ja, 'ja');
    if (sort === 'rank') {
      const d = (RANK_ORDER[b.rank] ?? 9) - (RANK_ORDER[a.rank] ?? 9);
      if (d) return d;
      return a.name_ja.localeCompare(b.name_ja, 'ja');
    }
    const na = a.medallium_no?.yw ?? a.medallium_no?.yw2 ?? '9999';
    const nb = b.medallium_no?.yw ?? b.medallium_no?.yw2 ?? '9999';
    return String(na).padStart(5, '0').localeCompare(String(nb).padStart(5, '0'))
        || a.name_ja.localeCompare(b.name_ja, 'ja');
  });
  return out;
}

function yokaiCard(y) {
  const owned = store.owned.has(y.yokai_id);
  const no = y.medallium_no?.yw || y.medallium_no?.yw2 || '';
  return `<article class="card">
    <div class="card-main" tabindex="0" role="button" data-yokai="${esc(y.yokai_id)}">
      <div class="name-ja">${esc(y.name_ja === 'unknown' ? y.name_en : y.name_ja)}</div>
      <div class="name-en">${esc(y.name_en)}${no ? ' ・ No.' + esc(no) : ''}</div>
      <div class="card-meta">
        ${rankBadge(y)}${tribeBadge(y)}${attrBadge(y)}
        ${y.appears_in.length ? `<span class="badge">アニメ${y.appears_in.length}回</span>`
                              : '<span class="badge none">アニメ登場なし</span>'}
      </div>
    </div>
    <label class="own" title="持っているメダル">
      <input type="checkbox" data-own="${esc(y.yokai_id)}"${owned ? ' checked' : ''}>もってる
    </label>
  </article>`;
}

function renderYokai() {
  const list = filterYokai();
  $('y-count').textContent = `${list.length.toLocaleString()} 件`;
  const n = Object.values(state.y.facets).reduce((a, s) => a + s.size, 0);
  const chip = $('y-active-count');
  chip.hidden = !n;
  chip.textContent = n;
  $('y-list').innerHTML = list.slice(0, state.y.shown).map(yokaiCard).join('')
    || '<p class="note">みつかりませんでした。</p>';
  $('y-more').hidden = list.length <= state.y.shown;
}

/* ==========================================================================
 * アニメタブ
 * ======================================================================= */
const PRESENCE_LABEL = { main: 'メイン', cameo: 'ちょい役', flashback: '回想', mentioned: '名前だけ' };

function buildAnimeFacets() {
  $('a-series').innerHTML = [['gen1', '初代'], ['uta', '♪']].map(([v, l]) =>
    `<label><input type="checkbox" data-a="series" value="${v}">${l}</label>`).join('');

  const years = [...new Set(DB.episodes.filter((e) => e.air_date)
    .map((e) => e.air_date.slice(0, 4)))].sort();
  $('a-years').innerHTML = years.map((y) =>
    `<label><input type="checkbox" data-a="years" value="${y}">${y}年</label>`).join('');

  $('a-presence').innerHTML = Object.entries(PRESENCE_LABEL).map(([v, l]) =>
    `<label><input type="checkbox" data-a="presence" value="${v}">${l}</label>`).join('');

  document.querySelectorAll('[data-a]').forEach((el) => {
    el.addEventListener('change', () => {
      const set = state.a[el.dataset.a];
      el.checked ? set.add(el.value) : set.delete(el.value);
      state.a.shown = PAGE;
      renderAnime();
    });
  });
}

function episodeText(ep) {
  const segs = INDEX.segsByEp.get(ep.episode_id) || [];
  return norm(segs.map((s) => s.title_ja).join(' ') + ' ' + (ep.title_ja_full || ''));
}

function filterEpisodes() {
  const q = norm(state.a.q).trim();
  const scope = state.a.scope;

  let out = DB.episodes.filter((ep) => {
    if (ep.kind === 'movie') return false;      // 劇場版は別枠（SPEC.md §9.4）
    if (state.a.series.size && !state.a.series.has(ep.series)) return false;
    if (state.a.years.size && !(ep.air_date && state.a.years.has(ep.air_date.slice(0, 4)))) return false;
    if (state.a.unwatchedOnly && store.watched.has(ep.episode_id)) return false;
    if (state.a.presence.size) {
      const ok = ep.yokai.some((e) => state.a.presence.has(e.presence))
              || ep.humans.some((e) => state.a.presence.has(e.presence));
      if (!ok) return false;
    }
    if (!q) return true;

    const inTitle = () => episodeText(ep).includes(q);
    const inYokai = () => ep.yokai.some((e) => {
      const y = INDEX.yokai.get(e.yokai_id);
      return y && (norm(y.name_ja).includes(q) || norm(y.name_en).includes(q));
    });
    const inHuman = () => ep.humans.some((e) => {
      const c = INDEX.characters.get(e.character_id);
      return c && (norm(c.name_ja).includes(q) || norm(c.name_en).includes(q));
    });
    if (scope === 'title') return inTitle();
    if (scope === 'yokai') return inYokai();
    if (scope === 'human') return inHuman();
    return inTitle() || inYokai() || inHuman();
  });

  if (state.a.sort === 'random') return seededShuffle(out, state.a.seed);
  out.sort((a, b) => {
    const d = (a.series === b.series)
      ? a.episode_no - b.episode_no
      : (a.series === 'gen1' ? -1 : 1);
    return state.a.sort === 'new' ? -d : d;
  });
  return out;
}

function segmentRow(seg) {
  const badge = seg.yotube_video_id
    ? `<a class="play" href="https://www.youtube.com/watch?v=${esc(seg.yotube_video_id)}"
          rel="noopener noreferrer" target="_blank">▶ 見る</a>`
    : '<span class="badge none">動画なし</span>';
  const corner = seg.is_recurring ? '<span class="badge">コーナー</span>' : '';
  return `<li><span class="seg-title">${esc(seg.title_ja)}</span>${corner}${badge}</li>`;
}

function episodeCard(ep) {
  const segs = INDEX.segsByEp.get(ep.episode_id) || [];
  const watched = store.watched.has(ep.episode_id);
  const label = ep.series === 'gen1' ? '初代' : '♪';
  const tags = [
    ...ep.yokai.map((e) => {
      const y = INDEX.yokai.get(e.yokai_id);
      return y ? `<button class="tag ${esc(e.presence)}" data-yokai="${esc(y.yokai_id)}">${esc(y.name_ja === 'unknown' ? y.name_en : y.name_ja)}${e.presence !== 'main' ? `<span class="p"> ${esc(PRESENCE_LABEL[e.presence])}</span>` : ''}</button>` : '';
    }),
    ...ep.humans.map((e) => {
      const c = INDEX.characters.get(e.character_id);
      return c ? `<button class="tag ${esc(e.presence)}" data-character="${esc(c.character_id)}">${esc(c.name_ja === 'unknown' ? c.name_en : c.name_ja)}</button>` : '';
    }),
  ].join('');

  return `<article class="card">
    <div class="card-main">
      <div class="ep-head">
        <span class="ep-no">${esc(label)} 第${ep.episode_no}話</span>
        <span class="ep-date">${ep.air_date ? esc(ep.air_date) : '<span class="badge none">放送日なし</span>'}</span>
      </div>
      <ul class="segments">${segs.map(segmentRow).join('') || '<li class="note">サブタイトルのデータがありません</li>'}</ul>
      <div class="tags">${tags || '<span class="badge none">登場データなし</span>'}</div>
    </div>
    <label class="own" title="見た回">
      <input type="checkbox" data-watch="${esc(ep.episode_id)}"${watched ? ' checked' : ''}>見た
    </label>
  </article>`;
}

function renderAnime() {
  const list = filterEpisodes();
  $('a-count').textContent = `${list.length.toLocaleString()} 回`;
  $('a-list').innerHTML = list.slice(0, state.a.shown).map(episodeCard).join('')
    || '<p class="note">みつかりませんでした。</p>';
  $('a-more').hidden = list.length <= state.a.shown;

  // 劇場版は常時表示。「劇場版を除く」のときだけ隠す（SPEC.md §9.4）
  const movies = DB.episodes.filter((e) => e.kind === 'movie');
  $('movies').hidden = state.a.hideMovies;
  $('movies-note').textContent = movies.length
    ? '検索の対象外です。あらすじと動画のデータはありません。'
    : '劇場版のデータはまだありません。';
  $('movie-list').innerHTML = movies.map((m) => `<article class="card">
      <div class="card-main">
        <div class="name-ja">${esc(m.title_ja_full || m.episode_id)}</div>
        <div class="card-meta">
          ${m.air_date ? `<span class="badge">${esc(m.air_date.slice(0, 4))}年</span>` : ''}
          <span class="badge none">データなし（一覧のみ）</span>
        </div>
      </div></article>`).join('');
}

/* ==========================================================================
 * 詳細（相互参照。SPEC.md §9.3）
 * ======================================================================= */
function openDetail(html) {
  $('detail-body').innerHTML = html;
  $('detail').hidden = false;
  document.body.style.overflow = 'hidden';
  $('detail-close').focus();
}
function closeDetail() {
  $('detail').hidden = true;
  document.body.style.overflow = '';
}

function fandomLink(pageId) {
  // CC BY-SA の帰属は各ページで示す（SPEC.md §12.1）
  return `<p class="source-link">出典:
    <a href="https://yokaiwatch.fandom.com/wiki/${encodeURIComponent(pageId)}"
       rel="noopener noreferrer" target="_blank">Yo-kai Watch Wiki — ${esc(pageId)}</a>
    （CC BY-SA）</p>`;
}

function showYokai(id) {
  const y = INDEX.yokai.get(id);
  if (!y) return;
  const eps = y.appears_in.map((epId) => DB.episodes.find((e) => e.episode_id === epId))
    .filter(Boolean)
    .sort((a, b) => (a.series === b.series) ? a.episode_no - b.episode_no : (a.series === 'gen1' ? -1 : 1));

  const row = (label, value) => value ? `<dt>${label}</dt><dd>${value}</dd>` : '';
  const f = DB.facets;
  openDetail(`
    <h2>${esc(y.name_ja === 'unknown' ? y.name_en : y.name_ja)}</h2>
    <p class="name-en">${esc(y.name_en)}${y.name_romaji ? ' ・ ' + esc(y.name_romaji) : ''}</p>
    <div class="card-meta">${rankBadge(y)}${tribeBadge(y)}${attrBadge(y)}</div>
    <dl>
      ${row('ランク', y.rank === 'unknown' ? '<span class="badge none">データなし</span>' : esc(y.rank))}
      ${row('種族', y.tribe === 'unknown' ? '<span class="badge none">データなし</span>' : esc(f.tribe[y.tribe] || y.tribe))}
      ${row('属性', y.attribute === 'unknown' ? '<span class="badge none">データなし</span>' : esc(f.attribute[y.attribute] || y.attribute))}
      ${row('役割', y.role === 'unknown' ? '<span class="badge none">データなし</span>' : esc(y.role))}
      ${row('好きなもの', y.foods_loved.map(esc).join('、'))}
      ${row('きらいなもの', y.foods_disliked.map(esc).join('、'))}
      ${row('ファミリー', y.family ? esc(y.family) + (y.is_family_head ? '（代表）' : '') : '')}
      ${row('図鑑番号', Object.entries(y.medallium_no || {}).map(([g, n]) => `${esc(g)}: ${esc(n)}`).join(' / '))}
    </dl>
    <h3>アニメでの登場（${eps.length}回）</h3>
    ${eps.length ? `<div class="tags">${eps.map((e) => {
      const p = e.yokai.find((x) => x.yokai_id === id);
      return `<button class="tag ${esc(p ? p.presence : 'main')}" data-episode="${esc(e.episode_id)}">${e.series === 'gen1' ? '初代' : '♪'} 第${e.episode_no}話${p && p.is_debut ? '（初登場）' : ''}</button>`;
    }).join('')}</div>` : '<p class="note">アニメでの登場データはありません。</p>'}
    ${fandomLink(y.yokai_id)}`);
}

function showCharacter(id) {
  const c = INDEX.characters.get(id);
  if (!c) return;
  const eps = c.appears_in.map((epId) => DB.episodes.find((e) => e.episode_id === epId))
    .filter(Boolean)
    .sort((a, b) => (a.series === b.series) ? a.episode_no - b.episode_no : (a.series === 'gen1' ? -1 : 1));
  openDetail(`
    <h2>${esc(c.name_ja === 'unknown' ? c.name_en : c.name_ja)}</h2>
    <p class="name-en">${esc(c.name_en)}</p>
    <h3>アニメでの登場（${eps.length}回）</h3>
    ${eps.length ? `<div class="tags">${eps.map((e) =>
      `<button class="tag" data-episode="${esc(e.episode_id)}">${e.series === 'gen1' ? '初代' : '♪'} 第${e.episode_no}話</button>`).join('')}</div>`
      : '<p class="note">登場データはありません。</p>'}
    ${fandomLink(c.character_id)}`);
}

function showEpisode(id) {
  const ep = DB.episodes.find((e) => e.episode_id === id);
  if (!ep) return;
  const segs = INDEX.segsByEp.get(id) || [];
  const staff = Object.entries(ep.staff || {});
  const STAFF_LABEL = { screenplay: '脚本', storyboard: '絵コンテ', director: '演出',
                        amindirector: '作画監督', animation: '制作' };
  openDetail(`
    <h2>${ep.series === 'gen1' ? '初代' : '♪'} 第${ep.episode_no}話</h2>
    <p class="name-en">${ep.air_date ? esc(ep.air_date) + ' 放送' : 'データなし'}</p>
    <ul class="segments">${segs.map(segmentRow).join('') || '<li class="note">データなし</li>'}</ul>
    ${staff.length ? `<h3>スタッフ</h3><dl>${staff.map(([k, v]) =>
      `<dt>${esc(STAFF_LABEL[k] || k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>` : ''}
    ${ep.opening || ep.ending ? `<dl>
      ${ep.opening ? `<dt>OP</dt><dd>${esc(ep.opening)}</dd>` : ''}
      ${ep.ending ? `<dt>ED</dt><dd>${esc(ep.ending)}</dd>` : ''}</dl>` : ''}
    <h3>出てくる妖怪・人物</h3>
    <div class="tags">
      ${ep.yokai.map((e) => { const y = INDEX.yokai.get(e.yokai_id); return y
        ? `<button class="tag ${esc(e.presence)}" data-yokai="${esc(y.yokai_id)}">${esc(y.name_ja === 'unknown' ? y.name_en : y.name_ja)}</button>` : ''; }).join('')}
      ${ep.humans.map((e) => { const c = INDEX.characters.get(e.character_id); return c
        ? `<button class="tag ${esc(e.presence)}" data-character="${esc(c.character_id)}">${esc(c.name_ja === 'unknown' ? c.name_en : c.name_ja)}</button>` : ''; }).join('')}
    </div>
    ${fandomLink(ep.episode_id)}`);
}

/* ==========================================================================
 * 起動
 * ======================================================================= */
async function loadAll() {
  const names = ['yokai', 'characters', 'episodes', 'segments', 'facets'];
  const results = await Promise.all(names.map((n) =>
    fetch(`data/${n}.json`).then((r) => {
      if (!r.ok) throw new Error(`${n}.json (${r.status})`);
      return r.json();
    })));
  names.forEach((n, i) => { DB[n] = results[i]; });

  DB.yokai.forEach((y) => INDEX.yokai.set(y.yokai_id, y));
  DB.characters.forEach((c) => INDEX.characters.set(c.character_id, c));
  DB.segments.forEach((s) => {
    if (!INDEX.segsByEp.has(s.episode_id)) INDEX.segsByEp.set(s.episode_id, []);
    INDEX.segsByEp.get(s.episode_id).push(s);
  });
  INDEX.segsByEp.forEach((list) => list.sort((a, b) => a.seq - b.seq));
}

function switchTab(name) {
  state.tab = name;
  document.querySelectorAll('[role="tab"]').forEach((b) => {
    b.setAttribute('aria-selected', String(b.dataset.tab === name));
  });
  ['yokai', 'anime', 'mine'].forEach((n) => { $(`panel-${n}`).hidden = n !== name; });
  if (name === 'mine') renderMine();
  window.scrollTo({ top: 0 });
}

function renderMine() {
  $('mine-summary').textContent =
    `見た回 ${store.watched.size} 件 ／ 持っているメダル ${store.owned.size} 件`;
}

function wire() {
  document.querySelectorAll('[role="tab"]').forEach((b) =>
    b.addEventListener('click', () => switchTab(b.dataset.tab)));

  const debounce = (fn) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), 150); }; };

  $('y-q').addEventListener('input', debounce((e) => {
    state.y.q = e.target.value; state.y.shown = PAGE; renderYokai();
  }));
  $('y-scope').addEventListener('change', (e) => { state.y.scope = e.target.value; renderYokai(); });
  $('y-sort').addEventListener('change', (e) => {
    state.y.sort = e.target.value; state.y.seed = Date.now() & 0x7fffffff; renderYokai();
  });
  $('y-owned-only').addEventListener('change', (e) => {
    state.y.ownedOnly = e.target.checked; state.y.shown = PAGE; renderYokai();
  });
  $('y-more').addEventListener('click', () => { state.y.shown += PAGE; renderYokai(); });
  $('y-clear').addEventListener('click', () => {
    state.y.facets = {};
    document.querySelectorAll('#y-facets input').forEach((i) => { i.checked = false; });
    state.y.shown = PAGE; renderYokai();
  });

  $('a-q').addEventListener('input', debounce((e) => {
    state.a.q = e.target.value; state.a.shown = PAGE; renderAnime();
  }));
  $('a-scope').addEventListener('change', (e) => { state.a.scope = e.target.value; renderAnime(); });
  $('a-sort').addEventListener('change', (e) => {
    state.a.sort = e.target.value; state.a.seed = Date.now() & 0x7fffffff; renderAnime();
  });
  $('a-unwatched-only').addEventListener('change', (e) => {
    state.a.unwatchedOnly = e.target.checked; state.a.shown = PAGE; renderAnime();
  });
  $('a-hide-movies').addEventListener('change', (e) => {
    state.a.hideMovies = e.target.checked; renderAnime();
  });
  $('a-more').addEventListener('click', () => { state.a.shown += PAGE; renderAnime(); });
  $('a-clear').addEventListener('click', () => {
    state.a.series.clear(); state.a.years.clear(); state.a.presence.clear();
    document.querySelectorAll('[data-a]').forEach((i) => { i.checked = false; });
    state.a.shown = PAGE; renderAnime();
  });

  // カード・タグのクリックはまとめて拾う
  document.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-yokai],[data-character],[data-episode],[data-own],[data-watch]');
    if (!el) return;
    if (el.dataset.own !== undefined) { store.toggle(store.owned, el.dataset.own); renderMine(); return; }
    if (el.dataset.watch !== undefined) { store.toggle(store.watched, el.dataset.watch); renderMine(); return; }
    if (el.dataset.yokai) showYokai(el.dataset.yokai);
    else if (el.dataset.character) showCharacter(el.dataset.character);
    else if (el.dataset.episode) showEpisode(el.dataset.episode);
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeDetail();
    if (ev.key === 'Enter' && ev.target.dataset?.yokai) showYokai(ev.target.dataset.yokai);
  });
  $('detail-close').addEventListener('click', closeDetail);
  $('detail').addEventListener('click', (ev) => { if (ev.target.id === 'detail') closeDetail(); });

  // 書き出し・読み込み（SPEC.md §10.6）
  $('io-export').addEventListener('click', () => {
    $('io-text').value = JSON.stringify(
      { watched: [...store.watched], owned: [...store.owned] }, null, 1);
    msg('書き出しました。この文字列を保存しておいてください。');
  });
  $('io-copy').addEventListener('click', async () => {
    if (!$('io-text').value) $('io-export').click();
    try { await navigator.clipboard.writeText($('io-text').value); msg('コピーしました。'); }
    catch (e) { $('io-text').select(); msg('コピーできませんでした。手動で選択してください。'); }
  });
  $('io-import').addEventListener('click', () => {
    try {
      const parsed = JSON.parse($('io-text').value);
      store.watched = new Set(parsed.watched || []);
      store.owned = new Set(parsed.owned || []);
      store.save();
      renderMine(); renderYokai(); renderAnime();
      msg('読み込みました。');
    } catch (e) { msg('読み込めませんでした。書き出した文字列をそのまま貼ってください。'); }
  });
  $('io-clear').addEventListener('click', () => {
    if (!confirm('記録をぜんぶ消します。よろしいですか？')) return;
    store.watched.clear(); store.owned.clear(); store.save();
    renderMine(); renderYokai(); renderAnime();
    msg('消しました。');
  });
}

(async function main() {
  store.load();
  wire();
  try {
    await loadAll();
  } catch (err) {
    $('y-count').textContent = 'データを読み込めませんでした: ' + err.message;
    $('a-count').textContent = '';
    return;
  }
  buildYokaiFacets();
  buildAnimeFacets();
  renderYokai();
  renderAnime();
  renderMine();
})();
