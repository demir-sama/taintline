const $ = (s, el = document) => el.querySelector(s);
const pct = (x, d = 0) => (x * 100).toFixed(d) + '%';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const [bench, ans, load] = await Promise.all([
  fetch('data/bench.json').then((r) => r.json()),
  fetch('data/answers.json').then((r) => r.json()),
  fetch('data/load.json').then((r) => (r.ok ? r.json() : null)).catch(() => null),
]);
const S = bench.strategies, V = bench.vector, D = bench.dataset;
const tl = S.taintline;
const last = (a) => a[a.length - 1];

// ---------- hero
$('#ds').textContent = `${D.questions} question papers, ${D.retracted} retracted works, ${D.works.toLocaleString()} works with reference lists`;
const stats = [
  [pct(last(tl.curve_mean)), 'accuracy in the final round, up from ' + pct(tl.curve_mean[0]) + ' in round 1', 'red'],
  [pct(V.top5.accuracy), 'vector store (top 5), flat by construction', ''],
  [tl.fetches_per_q.toFixed(1), `reference lists read per question, vs ${bench.exhaustive.fetches_per_q.toFixed(0)} for a full crawl`, ''],
  [Math.round(bench.taintline_tokens_mean) + '', `tokens of context per answer, vs ${Math.round(V.top5.tokens_mean).toLocaleString()} for vector top 5`, ''],
];
$('#stats').innerHTML = stats.map(([b, s, c]) => `<div class="stat ${c}"><b>${b}</b><span>${esc(s)}</span></div>`).join('');

// ---------- chart
function chart() {
  const svg = $('#chart');
  const W = 1000, H = 420, m = { l: 52, r: 170, t: 20, b: 40 };
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const n = tl.curve_mean.length;
  const x = (i) => m.l + (i / (n - 1)) * (W - m.l - m.r);
  const y = (v) => m.t + (1 - v) * (H - m.t - m.b);
  let g = '';
  for (let v = 0; v <= 1.0001; v += 0.2) g += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 10}" y="${y(v) + 4}" text-anchor="end">${Math.round(v * 100)}%</text>`;
  for (let i = 0; i < n; i++) g += `<text x="${x(i)}" y="${H - m.b + 22}" text-anchor="middle">R${i + 1}</text>`;
  const series = [
    { k: 'taintline', c: '#c2361c', w: 3.5, label: 'Taintline', short: 'Taintline' },
    { k: 'memory_random', c: '#857d70', w: 2, label: 'Graph memory, random reads', short: 'Random reads' },
    { k: 'cold', c: '#16130f', w: 2, label: 'No memory (reset per question)', short: 'No memory', dash: true },
  ];
  const vec = { c: '#3a5a8c', label: 'Vector store, top 5', v: V.top5.accuracy };
  const path = (arr) => arr.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join('');
  const labels = [];
  for (const s of series) {
    const st = S[s.k];
    const band = path(st.curve_max) + st.curve_min.slice().reverse().map((v, j) => `L${x(n - 1 - j)},${y(v)}`).join('') + 'Z';
    g += `<path d="${band}" fill="${s.c}" opacity=".10"/>`;
    g += `<path d="${path(st.curve_mean)}" fill="none" stroke="${s.c}" stroke-width="${s.w}" ${s.dash ? 'stroke-dasharray="6 5"' : ''} stroke-linejoin="round"/>`;
    st.curve_mean.forEach((v, i) => (g += `<circle cx="${x(i)}" cy="${y(v)}" r="${s.k === 'taintline' ? 4 : 2.5}" fill="${s.c}"/>`));
    labels.push({ y: y(last(st.curve_mean)), t: `${s.short} ${pct(last(st.curve_mean))}`, c: s.c });
  }
  g += `<line x1="${x(0)}" x2="${x(n - 1)}" y1="${y(vec.v)}" y2="${y(vec.v)}" stroke="${vec.c}" stroke-width="2" stroke-dasharray="2 4"/>`;
  labels.push({ y: y(vec.v), t: `Vector ${pct(vec.v)}`, c: vec.c });
  const at = bench.always_tainted.accuracy;
  g += `<line x1="${x(0)}" x2="${x(n - 1)}" y1="${y(at)}" y2="${y(at)}" stroke="#a49a88" stroke-width="1" stroke-dasharray="8 4 2 4"/>`;
  labels.push({ y: y(at), t: `Always "tainted" ${pct(at)}`, c: '#857d70' });
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 16) labels[i].y = labels[i - 1].y + 16;
  labels.forEach((l) => (g += `<text class="lbl" x="${W - m.r + 10}" y="${l.y + 4}" style="fill:${l.c}">${esc(l.t)}</text>`));
  svg.innerHTML = g;
  $('#legend').innerHTML = [...series, { ...vec, dash: true }, { c: '#a49a88', label: 'Always say "tainted" (no evidence)', dash: true }].map((s) => `<li style="color:${s.c}"><i class="${s.dash ? 'dash' : ''}" style="background:${s.c}"></i><span style="color:var(--ink2)">${esc(s.label)}</span></li>`).join('');
  const verd = S.taintline_verdict;
  $('#curve-note').innerHTML = `Same 3-read budget for every graph line. Taintline ranks unread references by how many papers it has already ingested cite them, so what it read for earlier questions decides what it reads next. Adding its own verdicts to that ranking (+3 per citer it judged tainted) scored ${pct(verd.accuracy_mean, 1)} overall vs ${pct(tl.accuracy_mean, 1)}: no gain, so it is off by default. Every "tainted" verdict is a real citation path: precision ${pct(tl.precision_min)} in every run.`;
}
chart();

// ---------- explorer
const rows = ans.answers;
const T = ans.titles;
let filter = 'all', sel = null;
const tl_tok = (r) => r.ctx_tokens ?? Math.round(r.context.length / 3.6);
function list() {
  const q = $('#q').value.trim().toLowerCase();
  const out = rows.filter((r) => {
    if (filter === 'tainted' && !r.tainted) return false;
    if (filter === 'clean' && r.tainted) return false;
    if (filter === 'miss' && r.tainted === r.truth) return false;
    return !q || (r.title || '').toLowerCase().includes(q);
  }).slice(0, 120);
  $('#results').innerHTML = out.map((r) => `<li data-q="${r.q}" class="${sel === r.q ? 'sel' : ''}"><span class="dot ${r.tainted ? 't' : ''}"></span><span>${esc(r.title || 'W' + r.q)}</span><span class="yr">${r.year ?? ''} · R${r.round}</span></li>`).join('') || '<li><span></span><span>No matches</span></li>';
}
function show(qid) {
  const r = rows.find((x) => x.q === qid); if (!r) return;
  sel = qid; list();
  $('#compare').hidden = false;
  $('#p-title').textContent = r.title || 'W' + r.q;
  $('#p-meta').textContent = `W${r.q} · ${r.year ?? ''} ${r.venue ? '· ' + r.venue : ''} · answered in round ${r.round} · ${r.fetches} reference list${r.fetches === 1 ? '' : 's'} read`;
  const v = $('#verdict');
  const miss = r.tainted !== r.truth;
  v.className = 'verdict ' + (r.tainted ? 't' : 'c');
  v.textContent = r.tainted ? 'Tainted: evidence chain reaches a retraction' : (miss ? 'No path found within budget (a miss: the snapshot has one)' : 'No retracted ancestor within two citations');
  const p = r.path[0] || [];
  $('#path').innerHTML = p.map((id, i) => {
    const isR = i === p.length - 1 && p.length > 1;
    const lab = i === 0 ? 'This paper' : isR ? 'Retracted' : 'Cites';
    return (i ? `<div class="edge">CITES</div>` : '') + `<div class="node ${isR ? 'r' : ''}"><small>${lab} · W${id}</small>${esc(T[id] || (i === 0 ? r.title : 'W' + id))}</div>`;
  }).join('');
  $('#ctx').textContent = r.context;
  $('#tl-tok').textContent = `${r.ctx_tokens} tokens`;
  $('#v-tok').textContent = `${r.vec_tokens.toLocaleString()} tokens`;
  const chain = new Set(r.chain || []);
  $('#vhits').innerHTML = r.vector_top5.map((h) => `<li><span class="s">${h.s.toFixed(2)}</span><span>${h.retracted ? `<span class="rt ${chain.has(h.id) ? 'in' : ''}">${chain.has(h.id) ? 'RETRACTED · in this paper\'s chain' : 'RETRACTED · not cited by this paper\'s chain'}</span>` : ''}${esc(h.title || 'W' + h.id)}</span></li>`).join('');
  const anyR = r.vector_top5.some((h) => h.retracted);
  $('#vnote').textContent = anyR
    ? (r.vector_top5.some((h) => h.retracted && chain.has(h.id)) ? 'The vector store surfaced a retracted paper that really is in the chain, plus the text of four others.' : 'The vector store surfaced retracted work that sounds similar but is not in this paper\'s citations. An agent would raise a false alarm or cite the wrong reason.')
    : (r.truth ? 'No retracted paper in the top 5: the vector store misses this contamination.' : 'No retracted paper in the top 5, which is right here, but it cannot show why.');
}
$('#q').addEventListener('input', list);
$('#results').addEventListener('click', (e) => { const li = e.target.closest('li[data-q]'); if (li) show(+li.dataset.q); });
document.querySelectorAll('.chips button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.chips button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on'); filter = b.dataset.f; list();
}));
list();
const isFalseAlarmDemo = (r) => r.tainted && r.path[0]?.length === 3 && /covid|sars-cov|pandemic/i.test(r.title || '') && r.vector_top5.some((h) => h.retracted && !(r.chain || []).includes(h.id));
const firstTwoHop = rows.find(isFalseAlarmDemo) || rows.find((r) => r.tainted && r.path[0]?.length === 3);
if (firstTwoHop) show(firstTwoHop.q);

// ---------- tables
const tr = (cells, cls = '') => `<tr class="${cls}">${cells.map((c, i) => `<td class="${i ? 'n' : ''}">${c}</td>`).join('')}</tr>`;
$('#tbl').innerHTML = `<tr><th>Approach</th><th class="n">Accuracy</th><th class="n">Final round</th><th class="n">Recall (tainted)</th><th class="n">Precision</th><th class="n">Lists read / q</th><th class="n">Context tokens</th></tr>` +
  tr(['Taintline (HydraDB)', pct(tl.accuracy_mean, 1), pct(last(tl.curve_mean), 1), pct(tl.recall_mean, 1), pct(tl.precision_min), tl.fetches_per_q.toFixed(2), Math.round(bench.taintline_tokens_mean)], 'hl') +
  tr(['Graph memory, random reads', pct(S.memory_random.accuracy_mean, 1), pct(last(S.memory_random.curve_mean), 1), pct(S.memory_random.recall_mean, 1), pct(S.memory_random.precision_min), S.memory_random.fetches_per_q.toFixed(2), '≈ same']) +
  tr(['No memory (reset per question)', pct(S.cold.accuracy_mean, 1), pct(last(S.cold.curve_mean), 1), pct(S.cold.recall_mean, 1), pct(S.cold.precision_min), S.cold.fetches_per_q.toFixed(2), '≈ same']) +
  tr(['Vector store, top 5', pct(V.top5.accuracy, 1), '—', pct(V.top5.recall, 1), pct(V.top5.precision, 1), '0', Math.round(V.top5.tokens_mean).toLocaleString()]) +
  tr(['Vector store, top 10', pct(V.top10.accuracy, 1), '—', pct(V.top10.recall, 1), pct(V.top10.precision, 1), '0', Math.round(V.top10.tokens_mean).toLocaleString()]) +
  tr(['Always say "tainted"', pct(bench.always_tainted.accuracy, 1), '—', '100%', pct(bench.always_tainted.precision, 1), '0', 'no evidence']) +
  tr(['Full crawl, no budget', '100%', '100%', '100%', '100%', bench.exhaustive.fetches_per_q.toFixed(1), '—']);
$('#sweep').innerHTML = `<tr><th>Budget</th><th class="n">Accuracy</th><th class="n">Final round</th><th class="n">Lists / q</th></tr>` +
  bench.budget_sweep.map((b) => tr([b.budget, pct(b.accuracy, 1), pct(b.last_round, 1), b.fetches_per_q.toFixed(2)], b.budget === bench.budget ? 'hl' : '')).join('');
if (load) {
  $('#load').innerHTML = `<div class="load">
    <div><b>${load.qps.toFixed(0)}</b><span>queries / second</span></div>
    <div><b>${load.p50_ms.toFixed(1)} ms</b><span>p50 latency</span></div>
    <div><b>${load.p95_ms.toFixed(1)} ms</b><span>p95 latency</span></div>
    <div><b>${load.errors}</b><span>errors in ${load.queries.toLocaleString()} queries</span></div></div>
    <p class="note">${esc(load.note)}</p>`;
} else $('#load').innerHTML = '<p class="note">Load test pending.</p>';

$('#honest').innerHTML = [
  `The "world" is a frozen OpenAlex snapshot (${D.works.toLocaleString()} works with reference lists). Ground truth is a retraction within two citations <em>inside that snapshot</em>; papers outside it are treated as having no references.`,
  `Questions were sampled as citers of papers that cite retracted COVID-19 work, plus ${D.clean_questions} same-topic papers with no such path, so the set is ${pct(D.tainted_questions / D.questions)} tainted on purpose. Saying "tainted" every time would score ${pct(bench.always_tainted.accuracy)} with no evidence; Taintline passes that from round 2 and every flag comes with its path.`,
  `Most of the gain comes from the graph remembering what it read. Ranking by its own verdicts added nothing measurable here, and we say so.`,
  `A full crawl is always right; Taintline's case is cost: about ${tl.fetches_per_q.toFixed(1)} reference-list reads per question instead of ${bench.exhaustive.fetches_per_q.toFixed(0)}.`,
  `The public page is a precomputed replay of a real HydraDB run (parity with the in-memory reference: ${bench.hydra_run ? bench.hydra_run.parity_mismatches_vs_memory + ' mismatches' : 'n/a'}). Running HydraDB needs a self-hosted node; setup is in the README.`,
].map((s) => `<li>${s}</li>`).join('');
