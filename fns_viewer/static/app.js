/* Налоговые ставки и льготы — client.
   Two routes, both in the address bar: `#/` is a search (filters, sort and page
   included) and `#/doc/<id>` is one document. That makes the back button work,
   makes a query bookmarkable, and gives the wide benefit table the full width
   it never had inside a modal. */

const PAGE_SIZE = 50;
const PAYERS = [['', 'Все категории'], ['fl', 'Физические лица'],
                ['ul', 'Юридические лица'], ['ip', 'Индивидуальные предприниматели']];
const PAYER_SHORT = { fl: 'ФЛ', ul: 'ЮЛ', ip: 'ИП' };
const RATE_SORTS = [['object', 'по объекту налогообложения'],
                    ['rate', 'по ставке, по возрастанию'],
                    ['rate-desc', 'по ставке, по убыванию']];
const BENEFIT_SORTS = [['category', 'по категории налогоплательщика'],
                       ['amount', 'по размеру льготы'],
                       ['article', 'по статье документа']];

const el = id => document.getElementById(id);
const form = el('filters');
const viewSearch = el('view-search');
const viewDoc = el('view-doc');

let meta = { labels: {}, payerFields: {}, codeFields: [] };
let optionNames = { regions: new Map(), taxes: new Map() };
let searchHash = '#/';
let searchScroll = 0;
let lastSearch = 0;
let doc = null;
let payer = '';
let rateSort = 'object';
let benefitSort = 'category';

/* ---------- helpers ---------- */

const esc = x => String(x ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const tidy = x => String(x ?? '').replace(/\s+/g, ' ').trim();
const num = x => { const v = parseFloat(String(x ?? '').replace(',', '.')); return isNaN(v) ? null : v; };
const fmt = v => v === null ? '—' : v.toLocaleString('ru-RU', { maximumFractionDigits: 4 });
const count = n => n.toLocaleString('ru-RU');
// The export stores dates as "2007-07-04T00:00:00"; nobody reads a tax law that way.
const date = value => {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(tidy(value));
  return match ? `${match[3]}.${match[2]}.${match[1]}` : tidy(value);
};

// Russian needs three forms: 1 ставка, 2 ставки, 5 ставок.
const plural = (n, forms) => {
  const rest = Math.abs(n) % 100, ones = rest % 10;
  const form = rest > 10 && rest < 20 ? forms[2] : ones === 1 ? forms[0] : ones > 1 && ones < 5 ? forms[1] : forms[2];
  return `${count(n)} ${form}`;
};
const RATES_WORD = ['ставка', 'ставки', 'ставок'];
const BENEFITS_WORD = ['льгота', 'льготы', 'льгот'];
const RECORDS_WORD = ['запись', 'записи', 'записей'];

async function api(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}

const label = key => meta.labels[key] || key;
const forPayer = (items, value) => items.filter(x => !value || x[meta.payerFields[value]] === '1');
const splitObject = text => {
  const s = tidy(text), i = s.indexOf(':');
  return i > 0 ? [s.slice(0, i).trim(), s.slice(i + 1).trim()] : [s, ''];
};
const payerTags = item => {
  const tags = Object.entries(meta.payerFields)
    .filter(([key, field]) => item[field] === '1')
    .map(([key]) => `<span class="tag" title="${esc(PAYERS.find(p => p[0] === key)[1])}">${PAYER_SHORT[key]}</span>`);
  return tags.length ? `<div class="tags">${tags.join('')}</div>` : '<span class="muted">—</span>';
};
// "87 - Чукотский автономный округ" — the code is real data, so set it as one.
const regionCell = name => {
  const match = /^(\d{2,3})\s*-\s*(.+)$/.exec(tidy(name));
  return match ? `<span class="rcode">${match[1]}</span>${esc(match[2])}` : esc(name) || '—';
};
const optionTags = (list, active) => list
  .map(([value, name]) => `<option value="${esc(value)}"${value === active ? ' selected' : ''}>${esc(name)}</option>`)
  .join('');

/* ---------- routing ---------- */

function state() {
  const params = new URLSearchParams((location.hash.split('?')[1]) || '');
  return {
    q: params.get('q') || '',
    region: params.get('region') || '',
    tax: params.get('tax') || '',
    period: params.get('period') || '',
    page: Math.max(0, parseInt(params.get('page') || '0', 10) || 0),
    sort: params.get('sort') || 'period',
    dir: params.get('dir') === 'asc' ? 'asc' : 'desc',
  };
}

function toHash(next, { replace = false } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(next)) {
    const isDefault = (key === 'page' && !value) || (key === 'sort' && value === 'period')
      || (key === 'dir' && value === 'desc');
    if (value && !isDefault) params.set(key, value);
  }
  const hash = '#/' + (params.toString() ? '?' + params : '');
  if (replace) history.replaceState(null, '', hash);
  else if (hash !== location.hash) { location.hash = hash; return; }
  if (replace) router();
}

function router() {
  const path = location.hash.split('?')[0];
  const match = path.match(/^#\/doc\/(.+)$/);
  if (match) {
    viewSearch.hidden = true;
    viewDoc.hidden = false;
    openDoc(decodeURIComponent(match[1]));
  } else {
    if (viewDoc.hidden === false) viewDoc.innerHTML = '';
    viewDoc.hidden = true;
    viewSearch.hidden = false;
    searchHash = location.hash || '#/';
    runSearch();
  }
}

/* ---------- search view ---------- */

function applyState(current) {
  form.q.value = current.q;
  form.region.value = current.region;
  form.tax.value = current.tax;
  form.period.value = current.period;
  for (const button of form.parentElement.querySelectorAll('.sort')) {
    const active = button.dataset.sort === current.sort;
    button.dataset.dir = active ? current.dir : '';
    button.closest('th').setAttribute('aria-sort',
      active ? (current.dir === 'asc' ? 'ascending' : 'descending') : 'none');
  }
}

function activeFilters(current) {
  const box = el('active');
  const chips = [];
  if (current.q) chips.push(['q', `Поиск: ${current.q}`]);
  if (current.region) chips.push(['region', optionNames.regions.get(current.region) || current.region]);
  if (current.tax) chips.push(['tax', optionNames.taxes.get(current.tax) || current.tax]);
  if (current.period) chips.push(['period', `Период: ${current.period}`]);
  box.hidden = !chips.length;
  box.innerHTML = chips.map(([key, text]) =>
    `<button type="button" class="pill" data-clear="${key}" aria-label="Убрать фильтр: ${esc(text)}">` +
    `<span>${esc(text)}</span><i aria-hidden="true">×</i></button>`).join('');
}

function skeleton() {
  el('rows').innerHTML = Array.from({ length: 8 }, () =>
    '<tr class="skeleton">' + '<td><i></i></td>'.repeat(5) + '</tr>').join('');
}

function emptyRow(title, body) {
  return `<tr><td colspan="5"><div class="state"><h3>${esc(title)}</h3><p>${esc(body)}</p></div></td></tr>`;
}

async function runSearch() {
  const current = state();
  applyState(current);
  activeFilters(current);
  skeleton();
  el('summary').textContent = 'Идёт поиск…';

  const params = new URLSearchParams({
    q: current.q, region: current.region, tax: current.tax, period: current.period,
    page: current.page, sort: current.sort, dir: current.dir,
  });
  const token = ++lastSearch;
  let data;
  try {
    data = await api('/api/search?' + params);
  } catch (error) {
    if (token !== lastSearch) return;
    el('rows').innerHTML = emptyRow('Не удалось выполнить поиск', error.message);
    el('summary').textContent = '';
    return;
  }
  if (token !== lastSearch) return;  // a later keystroke already won

  const from = data.count ? current.page * PAGE_SIZE + 1 : 0;
  const to = Math.min((current.page + 1) * PAGE_SIZE, data.count);
  const pages = Math.max(1, Math.ceil(data.count / PAGE_SIZE));
  const summary = data.count
    ? `Найдено <b>${plural(data.count, RECORDS_WORD)}</b> · показаны ${count(from)}–${count(to)}`
    : 'Ничего не найдено';
  el('summary').innerHTML = summary;
  el('summary-foot').innerHTML = summary;
  el('export').disabled = !data.count;
  el('footbar').hidden = pages < 2;
  for (const suffix of ['', '-foot']) {
    el('pageinfo' + suffix).textContent = `${current.page + 1} / ${count(pages)}`;
    el('prev' + suffix).disabled = current.page === 0;
    el('next' + suffix).disabled = current.page + 1 >= pages;
  }

  el('rows').innerHTML = data.rows.map(row => `
    <tr tabindex="-1" data-id="${esc(row.id)}">
      <td class="cell-period">${esc(row.period) || '—'}</td>
      <td>${regionCell(row.region)}</td>
      <td class="cell-tax">${esc(row.tax) || '—'}</td>
      <td class="cell-name"><a href="#/doc/${encodeURIComponent(row.id)}">${esc(row.municipality) || '<i class="muted">без муниципального образования</i>'}</a></td>
      <td class="cell-law"><div class="clip">${esc(row.law) || '—'}</div></td>
    </tr>`).join('')
    || emptyRow('Ничего не найдено',
      'Проверьте написание или снимите часть фильтров — поиск ищет по началу слова в названии муниципального образования, документа и коде ИФНС.');

  if (searchScroll) { window.scrollTo(0, searchScroll); searchScroll = 0; }
}

/* ---------- document view ---------- */

async function openDoc(id) {
  viewDoc.innerHTML = '<div class="state"><h3>Загрузка документа…</h3></div>';
  try {
    doc = await api('/api/record/' + encodeURIComponent(id));
  } catch (error) {
    viewDoc.innerHTML = `<button type="button" class="back" data-back>← К результатам</button>
      <div class="error">${esc(error.message)}</div>`;
    return;
  }
  payer = '';
  rateSort = 'object';
  benefitSort = 'category';
  stats = null;
  statsAll = false;
  renderDoc();
  window.scrollTo(0, 0);
  await loadStats();      // the document renders first; figures fill in after
  if (doc && doc.id === id) renderDoc();
}

function citation() {
  const a = doc.attributes;
  const place = [doc.region, a.MunObraz].filter(Boolean).map(tidy).join(' · ');
  const meta = [
    a.LawNum && ['Номер документа', a.LawNum],
    a.LawDate && ['Дата', date(a.LawDate)],
    a.TaxPeriod && ['Налоговый период', a.TaxPeriod],
    doc.tax && ['Налог', doc.tax],
    a.PayAll && ['Срок уплаты', a.PayAll],
    a.PayFiz && ['Срок уплаты, ФЛ', a.PayFiz],
    a.PayYur && ['Срок уплаты, ЮЛ', a.PayYur],
  ].filter(Boolean);
  const codes = meta_codes(a);
  return `<article class="citation">
    ${place ? `<p class="place">${esc(place)}</p>` : ''}
    <h1>${esc(tidy(a.LawDoc)) || 'Документ без названия'}</h1>
    ${meta.length ? `<div class="meta">${meta.map(([k, v]) =>
      `<span>${esc(k)}: <b>${esc(tidy(v))}</b></span>`).join('')}</div>` : ''}
    ${codes.length ? `<div class="codes">${codes.map(([k, v]) =>
      `<span class="code"><i>${esc(k)}</i>${esc(v)}</span>`).join('')}</div>` : ''}
  </article>`;
}

function meta_codes(attributes) {
  const short = { Oktmo_ID: 'ОКТМО', Oktmo: 'ОКТМО', Okato_ID: 'ОКАТО',
                  TaxOrganCode: 'ИФНС', TaxPlace_ID: 'Документ' };
  const seen = new Set();
  return meta.codeFields
    .filter(key => attributes[key] && !seen.has(short[key]) && seen.add(short[key]))
    .map(key => [short[key] || label(key), tidy(attributes[key])]);
}

function payerBar() {
  return `<div class="payers">
    <b>Категория плательщика</b>
    <div class="segments" role="group" aria-label="Категория плательщика">
      ${PAYERS.map(([value, name]) => `
        <button type="button" class="segment" data-payer="${value}" aria-pressed="${value === payer}">
          ${esc(name)}
          <small>${plural(forPayer(doc.rates, value).length, RATES_WORD)} · ${plural(forPayer(doc.benefits, value).length, BENEFITS_WORD)}</small>
        </button>`).join('')}
    </div>
  </div>`;
}

function sectionHead(title, shown, total, control, id) {
  const suffix = shown === total ? count(total) : `${count(shown)} из ${count(total)}`;
  return `<div class="section-head"${id ? ` id="${id}"` : ''}>
    <h2>${esc(title)} <span class="count">${suffix}</span></h2>${control}</div>`;
}

const emptyNote = () => `<p class="note">Для выбранной категории плательщиков записей нет.
  В части документов признаки ФЛ/ЮЛ/ИП не заполнены — тогда выберите «Все категории».</p>`;

function rateGroups(items) {
  const groups = new Map();
  for (const item of items) {
    const [name, detail] = splitObject(item.TaxObject);
    const key = name.toLocaleLowerCase('ru');
    if (!groups.has(key)) groups.set(key, { name, items: [] });
    groups.get(key).items.push({ ...item, detail, rate: num(item.TaxRates) });
  }
  const list = [...groups.values()];
  const down = rateSort === 'rate-desc';
  const sign = down ? -1 : 1;
  for (const group of list) {
    const values = group.items.map(x => x.rate).filter(x => x !== null);
    group.min = values.length ? Math.min(...values) : null;
    group.max = values.length ? Math.max(...values) : null;
    group.items.sort((a, b) => sign * ((a.rate ?? 0) - (b.rate ?? 0)) || a.detail.localeCompare(b.detail, 'ru'));
  }
  if (rateSort === 'object') list.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  else list.sort((a, b) => sign * ((down ? a.max : a.min) ?? 0) - sign * ((down ? b.max : b.min) ?? 0)
    || a.name.localeCompare(b.name, 'ru'));
  return list;
}

function ratesSection() {
  const items = forPayer(doc.rates, payer);
  const control = `<label>Ранжировать
    <select data-rate-sort>${optionTags(RATE_SORTS, rateSort)}</select></label>`;
  const head = sectionHead('Налоговые ставки', items.length, doc.rates.length, control, 'sec-rates');
  if (!items.length) return head + (doc.rates.length ? emptyNote() : '<p class="note">В документе нет ставок.</p>');

  const groups = rateGroups(items);
  // Only regions that spell out limits after a colon fill the detail column,
  // but it is always present: it is the one flexible column, and without it the
  // three fixed ones stretch across the whole table.
  const detailed = groups.some(group => group.items.some(x => x.detail));
  const columns = [
    ['<col style="width:120px">', '<th class="num">Ставка</th>'],
    ['<col>', detailed ? '<th>Уточнение объекта</th>' : '<th></th>'],
    ['<col style="width:130px">', '<th>Плательщики</th>'],
    ['<col style="width:130px">', '<th>Идентификатор</th>'],
  ];

  const body = groups.map(group => {
    const range = group.min === null ? ''
      : ` · ${group.min === group.max ? fmt(group.min) : `${fmt(group.min)} – ${fmt(group.max)}`}`;
    const header = `<tr class="group"><td colspan="${columns.length}"><div class="group-row">
      <b>${esc(group.name) || 'Без объекта налогообложения'}</b>
      <small>${plural(group.items.length, RATES_WORD)}${esc(range)}</small></div></td></tr>`;
    return header + group.items.map(x => `<tr>
      <td class="rate">${esc(fmt(x.rate))}</td>
      <td>${esc(x.detail) || (detailed ? '<span class="muted">—</span>' : '')}</td>
      <td>${payerTags(x)}</td>
      <td class="ident">${esc(x.ID || '')}</td></tr>`).join('');
  }).join('');

  return head + `<div class="table-scroll"><table class="data">
    <colgroup>${columns.map(c => c[0]).join('')}</colgroup>
    <thead><tr>${columns.map(c => c[1]).join('')}</tr></thead>
    <tbody>${body}</tbody></table></div>`;
}

// Roughly four lines in this column; below that a toggle is just noise.
const CLAMP_AT = 220;

function expandable(value) {
  const text = tidy(value);
  if (!text) return '<span class="muted">—</span>';
  if (text.length <= CLAMP_AT) return esc(text);
  return `<div class="clamp"><div class="text">${esc(text)}</div>
    <button type="button" class="more">Показать полностью</button></div>`;
}

function benefitsSection() {
  const items = forPayer(doc.benefits, payer).map(x => ({ ...x, amount: num(x.Amount) }));
  const control = `<label>Ранжировать
    <select data-benefit-sort>${optionTags(BENEFIT_SORTS, benefitSort)}</select></label>`;
  const head = sectionHead('Льготы', items.length, doc.benefits.length, control, 'sec-benefits');
  if (!items.length) return head + (doc.benefits.length ? emptyNote() : '<p class="note">В документе нет льгот.</p>');

  if (benefitSort === 'amount') items.sort((a, b) => (b.amount ?? -1) - (a.amount ?? -1)
    || tidy(a.Category).localeCompare(tidy(b.Category), 'ru'));
  else if (benefitSort === 'article') items.sort((a, b) =>
    tidy(a.LawArticle).localeCompare(tidy(b.LawArticle), 'ru', { numeric: true }));
  else items.sort((a, b) => tidy(a.Category).localeCompare(tidy(b.Category), 'ru'));

  const body = items.map(x => `<tr>
    <td>${esc(tidy(x.Category)) || '<span class="muted">—</span>'}</td>
    <td class="amount">${esc(fmt(x.amount))} <i>${esc(tidy(x.Unit))}</i></td>
    <td>${payerTags(x)}</td>
    <td>${esc(tidy(x.Base)) || '<span class="muted">—</span>'}</td>
    <td>${expandable(x.Condition)}</td>
    <td>${esc(tidy(x.LawArticle)) || '<span class="muted">—</span>'}</td>
    <td class="ident">${esc(x.ID || '')}</td></tr>`).join('');

  return head + `<div class="table-scroll"><table class="data">
    <colgroup><col style="width:24%"><col style="width:130px"><col style="width:110px">
      <col style="width:16%"><col><col style="width:120px"><col style="width:110px"></colgroup>
    <thead><tr><th>Категория налогоплательщика</th><th class="num">Размер</th>
      <th>Плательщики</th><th>Основание</th><th>Условия предоставления</th>
      <th>Статья</th><th>Идентификатор</th></tr></thead>
    <tbody>${body}</tbody></table></div>`;
}

/* ---------- statistics (form 5-МН) ---------- */

// The form is published per subject of the Federation, never per municipality,
// so a municipal document is shown its region's totals and told as much.
let stats = null;
let statsAll = false;

function statsSection() {
  if (!stats || !stats.available) return '';
  if (!stats.forms || !stats.forms.length) {
    return `<section id="sec-stats"><div class="section-head"><h2>Начисления по данным ФНС</h2></div>
      <p class="note">Для этого региона статистики нет.</p></section>`;
  }
  const municipal = tidy(doc.attributes.MunObraz);
  const asked = tidy(doc.attributes.TaxPeriod);
  const shown = String(stats.year);
  const picker = stats.years.length > 1
    ? `<label>Год <select data-stat-year>${optionTags(
        stats.years.slice().reverse().map(y => [String(y), String(y)]), shown)}</select></label>`
    : '';

  const caveats = [];
  if (municipal) caveats.push(`данные по региону <b>${esc(doc.region)}</b> целиком, а не по «${esc(municipal)}»`);
  if (asked && asked !== shown) caveats.push(`ближайший доступный год — <b>${esc(shown)}</b>, документ за ${esc(asked)}`);

  const blocks = stats.forms.map(form => {
    const tables = form.sections.map(section => {
      // The form's own numbered rows are its totals; the rest breaks them down
      // into dozens of exemption codes that nobody reads at a glance.
      // 5-ТН writes every row as a branch of a numbered parent, so almost
      // nothing reads as a top-level total; showing the lot beats showing three.
      const headline = section.items.filter(i => i.headline);
      const rows = (statsAll || headline.length < 4 ? section.items : headline)
        .map(item => `<tr${item.headline ? ' class="headline"' : ''}>
          <td>${esc(item.label)}</td>
          <td class="amount">${item.amount === null ? '<span class="muted">—</span>' : esc(fmt(item.amount))}</td>
          <td class="ident">${esc(item.code)}</td></tr>`).join('');
      return `<h3 class="stat-title">${esc(section.title)}</h3>
        <div class="table-scroll"><table class="data">
          <colgroup><col><col style="width:170px"><col style="width:80px"></colgroup>
          <thead><tr><th>Показатель</th><th class="num">Значение, тыс. руб. / единиц</th><th>Код</th></tr></thead>
          <tbody>${rows}</tbody></table></div>`;
    }).join('');
    return `<section id="sec-${esc(form.form)}">
      <div class="section-head"><h2>${esc(form.form)} — ${esc(form.name)}
        <span class="count">${esc(shown)}</span></h2>${picker}</div>
      ${caveats.length ? `<p class="note">Показаны ${caveats.join('; ')}.</p>` : ''}
      ${tables}</section>`;
  }).join('');

  const total = stats.forms.reduce((n, f) =>
    n + f.sections.reduce((m, s) => m + s.items.length, 0), 0);
  return blocks + `<button type="button" class="more" data-stat-all>${
    statsAll ? 'Показать только итоговые строки'
             : `Показать все показатели (${count(total)})`}</button>`;
}

// One line of jump links: a document runs to several screens once the rates,
// the exemptions and three statistical forms are all on it.
function tableOfContents() {
  const entries = [['sec-rates', 'Ставки', forPayer(doc.rates, payer).length],
                   ['sec-benefits', 'Льготы', forPayer(doc.benefits, payer).length]];
  for (const form of (stats && stats.forms) || []) entries.push([`sec-${form.form}`, form.form, null]);
  if (entries.length < 2) return '';
  return `<nav class="toc" aria-label="Разделы документа"><span class="toc-label">Разделы</span>${
    entries.map(([id, name, n]) =>
      `<a href="#${id}" data-toc="${id}">${esc(name)}${n === null ? '' : ` <b>${count(n)}</b>`}</a>`)
      .join('')}</nav>`;
}

// Highlight whichever section is currently on screen.
let tocWatcher = null;
function watchToc() {
  if (tocWatcher) tocWatcher.disconnect();
  const links = [...viewDoc.querySelectorAll('[data-toc]')];
  if (!links.length) return;
  tocWatcher = new IntersectionObserver(seen => {
    for (const entry of seen) {
      if (!entry.isIntersecting) continue;
      for (const link of links) {
        link.setAttribute('aria-current', String(link.dataset.toc === entry.target.id));
      }
    }
  }, { rootMargin: '-60px 0px -70% 0px' });
  for (const link of links) {
    const target = document.getElementById(link.dataset.toc);
    if (target) tocWatcher.observe(target);
  }
}

async function loadStats() {
  const code = /^(\d\d)\s*-/.exec(tidy(doc.region));
  if (!code) { stats = null; return; }
  try {
    stats = await api('/api/statistics?' + new URLSearchParams(
      { region: code[1], period: tidy(doc.attributes.TaxPeriod),
        tax: tidy(doc.attributes.Nalog_ID) }));
  } catch {
    stats = null;  // statistics are optional; the document still stands on its own
  }
}

function renderDoc() {
  viewDoc.innerHTML = `<button type="button" class="back" data-back>← К результатам</button>`
    + citation() + payerBar() + tableOfContents() + ratesSection() + benefitsSection() + statsSection()
    + `<div class="doc-actions">
        <button type="button" class="button button-primary" data-export-doc>Скачать документ в Excel</button>
        <button type="button" class="button" data-print>Распечатать</button>
      </div>`;
  watchToc();
}

/* ---------- events ---------- */

let typing;
form.addEventListener('input', event => {
  const immediate = event.target.tagName === 'SELECT';
  clearTimeout(typing);
  const commit = () => toHash({ ...state(), ...readForm(), page: 0 }, { replace: true });
  if (immediate) commit();
  else typing = setTimeout(commit, 250);
});
form.addEventListener('submit', event => {
  event.preventDefault();
  clearTimeout(typing);
  toHash({ ...state(), ...readForm(), page: 0 }, { replace: true });
});

const readForm = () => ({ q: form.q.value.trim(), region: form.region.value,
                          tax: form.tax.value, period: form.period.value });

el('active').addEventListener('click', event => {
  const pill = event.target.closest('[data-clear]');
  if (pill) toHash({ ...state(), [pill.dataset.clear]: '', page: 0 }, { replace: true });
});

viewSearch.addEventListener('click', event => {
  const sort = event.target.closest('.sort');
  if (sort) {
    const current = state();
    const next = sort.dataset.sort;
    toHash({ ...current, sort: next, page: 0,
             dir: current.sort === next && current.dir === 'asc' ? 'desc' : 'asc' }, { replace: true });
    return;
  }
  const row = event.target.closest('tbody tr[data-id]');
  if (row && !event.target.closest('a') && !getSelection().toString()) {
    searchScroll = window.scrollY;
    location.hash = '#/doc/' + encodeURIComponent(row.dataset.id);
  }
});
viewSearch.addEventListener('mousedown', event => {
  if (event.target.closest('tbody tr[data-id] a')) searchScroll = window.scrollY;
});

const step = delta => {
  toHash({ ...state(), page: Math.max(0, state().page + delta) });
  window.scrollTo(0, 0);
};
el('prev').onclick = el('prev-foot').onclick = () => step(-1);
el('next').onclick = el('next-foot').onclick = () => step(1);
el('export').onclick = () => {
  const current = state();
  location.href = '/api/export.xlsx?' + new URLSearchParams({
    q: current.q, region: current.region, tax: current.tax, period: current.period,
    sort: current.sort, dir: current.dir,
  });
};

viewDoc.addEventListener('click', event => {
  const target = event.target;
  if (target.closest('[data-back]')) {
    if (history.length > 1) history.back();
    else location.hash = searchHash;
  } else if (target.closest('[data-print]')) {
    window.print();
  } else if (target.closest('[data-export-doc]')) {
    location.href = '/api/export.xlsx?' + new URLSearchParams({ id: doc.id, payer });
  } else if (target.closest('.segment')) {
    payer = target.closest('.segment').dataset.payer;
    renderDoc();
  } else if (target.closest('[data-stat-all]')) {
    statsAll = !statsAll;
    renderDoc();
  } else if (target.closest('.more')) {
    const box = target.closest('.clamp');
    const open = box.classList.toggle('open');
    target.closest('.more').textContent = open ? 'Свернуть' : 'Показать полностью';
  }
});
viewDoc.addEventListener('change', async event => {
  if (event.target.matches('[data-rate-sort]')) { rateSort = event.target.value; renderDoc(); }
  if (event.target.matches('[data-benefit-sort]')) { benefitSort = event.target.value; renderDoc(); }
  if (event.target.matches('[data-stat-year]')) {
    const code = /^(\d\d)\s*-/.exec(tidy(doc.region));
    stats = await api('/api/statistics?' + new URLSearchParams(
      { region: code[1], period: event.target.value,
        tax: tidy(doc.attributes.Nalog_ID) }));
    renderDoc();
  }
});

document.addEventListener('keydown', event => {
  if (event.key === '/' && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) {
    event.preventDefault();
    form.q.focus();
    form.q.select();
  }
  if (event.key === 'Escape' && document.activeElement === form.q && form.q.value) {
    form.q.value = '';
    toHash({ ...state(), q: '', page: 0 }, { replace: true });
  }
});

window.addEventListener('hashchange', router);

/* ---------- boot ---------- */

(async function start() {
  // The hash router restores scroll itself; the browser's own guess fights it.
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  try {
    const [metaData, options] = await Promise.all([api('/api/meta'), api('/api/options')]);
    meta = metaData;
    for (const [id, name] of options.regions) {
      optionNames.regions.set(id, name);
      form.region.add(new Option(name, id));
    }
    for (const [id, name] of options.taxes) {
      optionNames.taxes.set(id, name);
      form.tax.add(new Option(name, id));
    }
    for (const period of options.periods) form.period.add(new Option(period, period));
    el('corpus').innerHTML = `${esc(plural(options.total, RECORDS_WORD))} · только чтение`
      + (options.revision ? ` · версия <code>${esc(options.revision)}</code>` : '');
  } catch (error) {
    el('summary').textContent = 'Не удалось загрузить справочники: ' + error.message;
  }
  router();
})();
