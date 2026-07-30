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
  const viewStats = el('view-stats');
  const show = which => {
    viewSearch.hidden = which !== 'search';
    viewDoc.hidden = which !== 'doc';
    viewStats.hidden = which !== 'stats';
    for (const tab of document.querySelectorAll('[data-tab]')) {
      tab.setAttribute('aria-current', String(tab.dataset.tab === (which === 'doc' ? 'search' : which)));
    }
  };
  if (match) {
    show('doc');
    openDoc(decodeURIComponent(match[1]));
  } else if (path === '#/stats') {
    show('stats');
    openStats();
  } else {
    if (viewDoc.hidden === false) viewDoc.innerHTML = '';
    show('search');
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

const shownOf = (shown, total) => shown === total ? count(total) : `${count(shown)} из ${count(total)}`;

function sectionHead(title, suffix, control, id) {
  // The heading is the toggle; the ranking select sits outside it so choosing
  // an order does not also fold the section away.
  return `<div class="section-head">
    <button type="button" class="section-toggle" data-toggle="${esc(id)}"
            aria-expanded="${!collapsed.has(id)}">
      <span class="chev" aria-hidden="true"></span>
      <h2>${esc(title)} <span class="count">${suffix}</span></h2>
    </button>${control}</div>`;
}

// Which sections the reader has folded away, kept across re-renders.
const collapsed = new Set();

function docSection(id, title, suffix, control, body) {
  return `<section class="doc-section${collapsed.has(id) ? ' collapsed' : ''}" id="${esc(id)}">
    ${sectionHead(title, suffix, control, id)}<div class="section-body">${body}</div></section>`;
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
  const suffix = shownOf(items.length, doc.rates.length);
  if (!items.length) {
    return docSection('sec-rates', 'Налоговые ставки', suffix, control,
      doc.rates.length ? emptyNote() : '<p class="note">В документе нет ставок.</p>');
  }

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

  return docSection('sec-rates', 'Налоговые ставки', suffix, control,
    `<div class="table-scroll"><table class="data">
      <colgroup>${columns.map(c => c[0]).join('')}</colgroup>
      <thead><tr>${columns.map(c => c[1]).join('')}</tr></thead>
      <tbody>${body}</tbody></table></div>`);
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
  const suffix = shownOf(items.length, doc.benefits.length);
  if (!items.length) {
    return docSection('sec-benefits', 'Льготы', suffix, control,
      doc.benefits.length ? emptyNote() : '<p class="note">В документе нет льгот.</p>');
  }

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

  return docSection('sec-benefits', 'Льготы', suffix, control,
    `<div class="table-scroll"><table class="data">
    <colgroup><col style="width:24%"><col style="width:130px"><col style="width:110px">
      <col style="width:16%"><col><col style="width:120px"><col style="width:110px"></colgroup>
    <thead><tr><th>Категория налогоплательщика</th><th class="num">Размер</th>
      <th>Плательщики</th><th>Основание</th><th>Условия предоставления</th>
      <th>Статья</th><th>Идентификатор</th></tr></thead>
    <tbody>${body}</tbody></table></div>`);
}

/* ---------- statistics ---------- */

// The form is published per subject of the Federation, never per municipality,
// so a municipal document is shown its region's totals and told as much.
let stats = null;
let statsAll = false;

function statsSection() {
  if (!stats || !stats.available) return '';
  const municipal = tidy(doc.attributes.MunObraz);
  const asked = tidy(doc.attributes.TaxPeriod);
  const shown = String(stats.year ?? asked);
  // Built before the empty case on purpose: a year with nothing in it is still
  // a year to move off, so the picker has to stay put rather than vanish.
  const picker = stats.years.length
    ? `<label>Год <select data-stat-year>${optionTags(
        stats.years.slice().reverse().map(y => [String(y), String(y)]), shown)}</select></label>`
    : '';
  if (!stats.forms || !stats.forms.length) {
    return docSection('sec-stats', 'Начисления по данным ФНС', esc(shown), picker,
      `<p class="note">За ${esc(shown)} год по этому налогу данных нет.
       ${stats.years.length ? 'Выберите другой год выше.' : ''}</p>`);
  }

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
    return docSection(`sec-${form.form}`, `${form.form} — ${form.name}`, esc(shown), picker,
      (caveats.length ? `<p class="note">Показаны ${caveats.join('; ')}.</p>` : '') + tables);
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
// A contents link must not reach the hash router: "#sec-5-ТН" is not a route,
// so letting the browser set it sent the reader back to the search screen.
viewDoc.addEventListener('click', event => {
  const jump = event.target.closest('[data-toc]');
  if (jump) {
    event.preventDefault();
    const id = jump.dataset.toc;
    collapsed.delete(id);            // jumping to a folded section opens it
    const section = document.getElementById(id);
    if (section) {
      section.classList.remove('collapsed');
      section.querySelector('.section-toggle')?.setAttribute('aria-expanded', 'true');
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    return;
  }
  const toggle = event.target.closest('.section-toggle');
  if (toggle) {
    const id = toggle.dataset.toggle;
    const open = collapsed.has(id);
    if (open) collapsed.delete(id); else collapsed.add(id);
    const section = document.getElementById(id);
    section?.classList.toggle('collapsed', !open);
    toggle.setAttribute('aria-expanded', String(open));
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
    el('corpus').innerHTML = esc(plural(options.total, RECORDS_WORD))
      + (options.revision ? ` · версия <code>${esc(options.revision)}</code>` : '');
  } catch (error) {
    el('summary').textContent = 'Не удалось загрузить справочники: ' + error.message;
  }
  router();
})();

/* ---------- analysis screen ---------- */

/* Colours come from the data-viz reference palette, validated against both
   surfaces: light passes every gate with a contrast WARN, which is why the
   legend always carries text labels and a table view is one click away. */
const SERIES_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100',
                      '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
const SERIES_DARK = ['#3987e5', '#d95926', '#199e70', '#c98500',
                     '#d55181', '#008300', '#9085e9', '#e66767'];
const CHART_TYPES = [['line', 'Линия'], ['bar', 'Столбцы'], ['dot', 'Точки']];
const X_AXES = [['year', 'Год'], ['region', 'Регион']];

let cat = null;                       // the indicator catalogue
let picks = [];                       // chosen indicator slots
let statsState = { regions: ['43'], mode: 'one', type: 'line', xAxis: 'year',
                   year: null, expr: '', table: false, zoom: null };
let seriesData = null;

const seriesColour = i => (matchMedia('(prefers-color-scheme: dark)').matches
  ? SERIES_DARK : SERIES_LIGHT)[i % 8];

const slotName = i => String.fromCharCode(65 + i);

function sectionsOf(form) {
  return (cat.forms.find(f => f.form === form) || { sections: [] }).sections;
}

function pickRow(pick, index) {
  const forms = cat.forms.map(f => [f.form, `${f.form} — ${f.name}`]);
  const sections = sectionsOf(pick.form).map(s => [String(s.section), s.title]);
  const chosen = sectionsOf(pick.form).find(s => String(s.section) === String(pick.section));
  const indicators = (chosen ? chosen.indicators : [])
    .map(i => [i.code, `${i.code} · ${i.label}`]);
  return `<div class="pick" data-index="${index}">
    <span class="slot">${slotName(index)}</span>
    <select data-pick="form">${optionTags(forms, pick.form)}</select>
    <select data-pick="section">${optionTags(sections, String(pick.section))}</select>
    <select data-pick="code" class="pick-indicator">${optionTags(indicators, pick.code)}</select>
    <button type="button" class="button button-quiet" data-drop="${index}"
            aria-label="Убрать показатель ${slotName(index)}"${picks.length < 2 ? ' disabled' : ''}>×</button>
  </div>`;
}

function statsControls() {
  const regionOptions = cat.regions.map(([code, name]) => [code, name]);
  const chosen = new Set(statsState.regions);
  return `<div class="panel">
    <div class="panel-head"><b>Показатели</b>
      <button type="button" class="more" data-add-pick>Добавить показатель</button></div>
    ${picks.map(pickRow).join('')}
    <label class="field-inline">Формула
      <input type="text" data-expr value="${esc(statsState.expr)}"
             placeholder="например B / A — оставьте пустым, чтобы взять A как есть">
      <small>Латинские буквы — обозначения выше, знаки + − * / и скобки</small>
    </label>
  </div>

  <div class="panel">
    <div class="panel-head"><b>Регионы</b></div>
    <div class="chips">
      ${[['one', 'Один регион'], ['some', 'Несколько'], ['all', `Все ${cat.regions.length}`]]
        .map(([value, label]) => `<button type="button" class="segment" data-mode="${value}"
          aria-pressed="${statsState.mode === value}">${label}</button>`).join('')}
    </div>
    ${statsState.mode === 'all' ? '' : `<select data-regions ${statsState.mode === 'some' ? 'multiple size="8"' : ''}>
      ${regionOptions.map(([v, n]) =>
        `<option value="${esc(v)}"${chosen.has(v) ? ' selected' : ''}>${esc(n)}</option>`).join('')}
    </select>`}
  </div>

  <div class="panel">
    <div class="panel-head"><b>График</b></div>
    <div class="control-row">
      <label class="field-inline">Тип
        <select data-type>${optionTags(CHART_TYPES, statsState.type)}</select></label>
      <label class="field-inline">Ось X
        <select data-xaxis>${optionTags(X_AXES, statsState.xAxis)}</select></label>
      ${statsState.xAxis === 'region' ? `<label class="field-inline">Год
        <select data-year>${optionTags(cat.years.map(y => [String(y), String(y)]),
          String(statsState.year ?? cat.years[cat.years.length - 1]))}</select></label>` : ''}
      <button type="button" class="button" data-table aria-pressed="${statsState.table}">Таблицей</button>
      <button type="button" class="button button-primary" data-export-series>Скачать Excel</button>
    </div>
  </div>`;
}

/* --- the chart itself: plain SVG, because nothing may be fetched from a CDN --- */

const PLOT = { w: 1000, h: 420, l: 84, r: 20, t: 18, b: 58 };

function niceTicks(min, max, count = 5) {
  if (!isFinite(min) || !isFinite(max)) return [0, 1];
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const rough = span / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= rough) || magnitude * 10;
  const first = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = first; v <= max + step * 0.001; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

const shortNumber = v => {
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млрд';
  if (abs >= 1e6) return (v / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн';
  if (abs >= 1e3) return (v / 1e3).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' тыс.';
  return v.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
};

function chartModel() {
  // Two orientations of the same matrix: years across the bottom with one
  // series per region, or regions across the bottom for a single year.
  if (statsState.xAxis === 'year') {
    return zoomed({
      labels: seriesData.years.map(String),
      series: seriesData.rows.map(row => ({ name: row.name, values: row.values })),
    });
  }
  const year = statsState.year ?? seriesData.years[seriesData.years.length - 1];
  const at = seriesData.years.indexOf(Number(year));
  return zoomed({
    labels: seriesData.rows.map(row => row.name.replace(/^\d\d\s*-\s*/, '')),
    series: [{ name: `${year} год`, values: seriesData.rows.map(row => row.values[at] ?? null) }],
  });
}

// Zooming is a slice of the x axis, so it belongs to the model, not the render.
function zoomed(model) {
  const range = statsState.zoom;
  if (!range) return model;
  const [from, to] = range;
  return {
    labels: model.labels.slice(from, to + 1),
    series: model.series.map(s => ({ ...s, values: s.values.slice(from, to + 1) })),
  };
}

// Eight is where a categorical palette stops working, and cycling it just
// produces eleven regions sharing a blue. Past that the largest eight keep
// their colour and a name; the rest stay in as recessive context so "все
// регионы" still means all of them.
const NAMED = 8;

function rankSeries(series) {
  const last = s => {
    for (let i = s.values.length - 1; i >= 0; i--) {
      if (s.values[i] !== null && isFinite(s.values[i])) return s.values[i];
    }
    return -Infinity;
  };
  const order = series.map((s, i) => ({ s, i, key: last(s) }))
    .sort((a, b) => b.key - a.key);
  const named = new Set(order.slice(0, NAMED).map(x => x.i));
  return series.map((s, i) => ({ ...s, named: named.has(i),
                                 colour: named.has(i)
                                   ? seriesColour(order.findIndex(x => x.i === i)) : null }));
}

function drawChart() {
  const model = chartModel();
  model.series = rankSeries(model.series);
  const flat = model.series.flatMap(s => s.values).filter(v => v !== null && isFinite(v));
  if (!flat.length) {
    return `<div class="state"><h3>Нет данных</h3>
      <p>Для выбранного показателя и регионов значений не нашлось.</p></div>`;
  }
  // Bars encode magnitude by length, so they must start at zero; a line encodes
  // change, and forcing zero there just flattens the shape being read.
  const floor = statsState.type === 'bar' ? Math.min(0, ...flat) : Math.min(...flat);
  const ticks = niceTicks(floor, Math.max(...flat));
  const low = ticks[0], high = ticks[ticks.length - 1];
  const innerW = PLOT.w - PLOT.l - PLOT.r;
  const innerH = PLOT.h - PLOT.t - PLOT.b;
  const y = v => PLOT.t + innerH - ((v - low) / (high - low)) * innerH;
  const step = innerW / Math.max(1, model.labels.length - (statsState.type === 'bar' ? 0 : 1));
  const x = i => statsState.type === 'bar'
    ? PLOT.l + step * (i + 0.5)
    : PLOT.l + step * i;

  const grid = ticks.map(t => `<line class="grid" x1="${PLOT.l}" x2="${PLOT.w - PLOT.r}"
      y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/>
    <text class="tick" x="${PLOT.l - 10}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${esc(shortNumber(t))}</text>`).join('');

  // Thin out x labels so they never collide.
  const everyNth = Math.ceil(model.labels.length / 14);
  const xLabels = model.labels.map((label, i) => (i % everyNth) ? '' :
    `<text class="tick" x="${x(i).toFixed(1)}" y="${PLOT.h - PLOT.b + 22}"
       text-anchor="${statsState.xAxis === 'region' ? 'end' : 'middle'}"
       ${statsState.xAxis === 'region' ? `transform="rotate(-35 ${x(i).toFixed(1)} ${PLOT.h - PLOT.b + 22})"` : ''}
     >${esc(label.length > 22 ? label.slice(0, 21) + '…' : label)}</text>`).join('');

  const marks = model.series.map((s, si) => {
    const colour = s.colour || 'var(--ink-3)';
    const context = !s.named;
    if (statsState.type === 'bar') {
      const width = Math.max(2, (step / model.series.length) * 0.7);
      return s.values.map((v, i) => v === null || !isFinite(v) ? '' : `<rect
        x="${(x(i) - (width * model.series.length) / 2 + si * width).toFixed(1)}"
        y="${Math.min(y(v), y(Math.max(low, 0))).toFixed(1)}" width="${width.toFixed(1)}"
        height="${Math.max(1, Math.abs(y(v) - y(Math.max(low, 0)))).toFixed(1)}"
        rx="3" fill="${colour}"><title>${esc(s.name)} · ${esc(model.labels[i])}: ${esc(fmt(v))}</title></rect>`).join('');
    }
    const points = s.values.map((v, i) => (v === null || !isFinite(v)) ? null : [x(i), y(v)]);
    const path = points.reduce((acc, p, i) => {
      if (!p) return acc;
      const prev = i > 0 && points[i - 1];
      return acc + (prev ? ` L${p[0].toFixed(1)} ${p[1].toFixed(1)}`
                         : ` M${p[0].toFixed(1)} ${p[1].toFixed(1)}`);
    }, '');
    const dots = context ? '' : points.map((p, i) => !p ? '' :
      `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${statsState.type === 'dot' ? 5 : 4}"
        fill="${colour}" stroke="var(--surface)" stroke-width="2"><title>${esc(s.name)} · ${esc(model.labels[i])}: ${esc(fmt(s.values[i]))}</title></circle>`).join('');
    return (statsState.type === 'line' || context
      ? `<path d="${path}" fill="none" stroke="${colour}" stroke-width="${context ? 1 : 2}"
           ${context ? 'opacity=".35"' : ''}
           stroke-linejoin="round" stroke-linecap="round"><title>${esc(s.name)}</title></path>` : '') + dots;
  }).join('');

  // The legend mirrors the mark it stands for: a stroke for lines, a block for bars.
  const key = statsState.type === 'bar' ? 'swatch' : 'swatch swatch-line';
  const rest = model.series.length - model.series.filter(s => s.named).length;
  const legend = model.series.length > 1 ? `<ul class="legend">${
    model.series.filter(s => s.named)
      .map(s => `<li><span class="${key}" style="background:${s.colour}"></span>${esc(s.name)}</li>`).join('')
    }${rest ? `<li><span class="${key} swatch-rest"></span>Остальные ${count(rest)} — серым</li>` : ''}</ul>` : '';

  const caption = statsState.expr
    ? `Формула ${esc(statsState.expr)}`
    : esc(picks.length ? (seriesData.picks[0] || {}).label || '' : '');

  // Geometry the interaction layer needs; recomputing it there would be a
  // second source of truth for where a point sits.
  chartGeometry = { x, y, model, step, low, high };

  return `<figure class="chart">
    <div class="chart-head">
      <figcaption>${caption}</figcaption>
      <button type="button" class="more" data-zoom-reset${statsState.zoom ? '' : ' hidden'}>Весь период</button>
    </div>
    <div class="plot">
      <svg viewBox="0 0 ${PLOT.w} ${PLOT.h}" tabindex="0"
           role="img" aria-label="График: ${esc(caption)}. Значения доступны кнопкой «Таблицей»."
           preserveAspectRatio="none">
        ${grid}
        <line class="axis" x1="${PLOT.l}" x2="${PLOT.w - PLOT.r}" y1="${y(low).toFixed(1)}" y2="${y(low).toFixed(1)}"/>
        ${xLabels}${marks}
        <g class="crosshair" hidden>
          <line y1="${PLOT.t}" y2="${PLOT.h - PLOT.b}"/>
          <g class="crosshair-dots"></g>
        </g>
        <rect class="brush" hidden y="${PLOT.t}" height="${PLOT.h - PLOT.t - PLOT.b}"/>
        <rect class="surface" x="${PLOT.l}" y="${PLOT.t}"
              width="${PLOT.w - PLOT.l - PLOT.r}" height="${PLOT.h - PLOT.t - PLOT.b}"/>
      </svg>
      <div class="tip" hidden></div>
    </div>
    ${legend}
    <p class="chart-hint">Наведите курсор — значения по всем рядам. Протяните мышью по графику, чтобы приблизить период; стрелки ← → двигают курсор.</p>
  </figure>`;
}

let chartGeometry = null;

function seriesTable() {
  const model = chartModel();
  return `<div class="table-scroll"><table class="data">
    <thead><tr><th>Ряд</th>${model.labels.map(l => `<th class="num">${esc(l)}</th>`).join('')}</tr></thead>
    <tbody>${model.series.map(s => `<tr><td>${esc(s.name)}</td>${
      s.values.map(v => `<td class="amount">${v === null ? '<span class="muted">—</span>' : esc(fmt(v))}</td>`).join('')
    }</tr>`).join('')}</tbody></table></div>`;
}

function statsParams() {
  const params = new URLSearchParams();
  for (const [index, pick] of picks.entries()) {
    params.append('pick', `${slotName(index)}:${pick.form}:${pick.section}:${pick.code}`);
  }
  params.set('regions', statsState.mode === 'all' ? 'all' : statsState.regions.join(','));
  if (statsState.expr.trim()) params.set('expr', statsState.expr.trim());
  return params;
}

async function loadSeries() {
  const box = el('view-stats').querySelector('#chart-area');
  if (box) box.innerHTML = '<div class="state"><h3>Считаем…</h3></div>';
  try {
      statsState.zoom = null;   // a new series has a different x axis
    seriesData = await api('/api/statistics/series?' + statsParams());
  } catch (error) {
    seriesData = null;
    if (box) box.innerHTML = `<div class="error">${esc(error.message)}</div>`;
    return;
  }
  renderChartArea();
}

function renderChartArea() {
  const box = el('view-stats').querySelector('#chart-area');
  if (!box || !seriesData) return;
  box.innerHTML = drawChart() + (statsState.table ? seriesTable() : '');
  attachChartInteraction();
}

function renderStats() {
  if (!cat) return;
  el('view-stats').innerHTML = `
    <h1 class="screen-title">Аналитика по данным ФНС</h1>
    <p class="screen-note">Выберите показатель, регионы и вид графика. Формула считает
      по каждому региону и году отдельно, результат попадает и в график, и в выгрузку.</p>
    <div class="panels">${statsControls()}</div>
    <div id="chart-area"></div>`;
  loadSeries();
}

async function openStats() {
  if (!cat) {
    try {
      cat = await api('/api/statistics/catalog');
    } catch (error) {
      el('view-stats').innerHTML = `<div class="error">${esc(error.message)}</div>`;
      return;
    }
    if (!cat.available) {
      el('view-stats').innerHTML = '<div class="state"><h3>Статистики нет</h3><p>Файлы с данными ФНС не найдены.</p></div>';
      return;
    }
    // Open on a total rather than whatever code sorts first: the form numbers
    // its own headline rows, and those are what anyone wants to see first.
    const first = cat.forms[0];
    const section = first.sections[0];
    const headline = section.indicators.find(i => /^\s*\d+\s*[.)]/.test(i.label))
      || section.indicators[0];
    picks = [{ form: first.form, section: section.section, code: headline.code }];
    statsState.year = cat.years[cat.years.length - 1];
  }
  renderStats();
}

el('view-stats').addEventListener('change', event => {
  const target = event.target;
  const row = target.closest('.pick');
  if (row) {
    const index = Number(row.dataset.index);
    const which = target.dataset.pick;
    if (which === 'form') {
      const sections = sectionsOf(target.value);
      picks[index] = { form: target.value, section: sections[0].section,
                       code: sections[0].indicators[0].code };
    } else if (which === 'section') {
      const section = sectionsOf(picks[index].form)
        .find(s => String(s.section) === target.value);
      picks[index] = { ...picks[index], section: section.section,
                       code: section.indicators[0].code };
    } else {
      picks[index] = { ...picks[index], code: target.value };
    }
    return renderStats();
  }
  if (target.matches('[data-regions]')) {
    statsState.regions = [...target.selectedOptions].map(o => o.value);
    return loadSeries();
  }
  if (target.matches('[data-type]')) { statsState.type = target.value; return renderChartArea(); }
  if (target.matches('[data-xaxis]')) {
    statsState.xAxis = target.value; statsState.zoom = null; return renderStats();
  }
  if (target.matches('[data-year]')) { statsState.year = Number(target.value); return renderChartArea(); }
});

el('view-stats').addEventListener('click', event => {
  const target = event.target;
  if (target.closest('[data-add-pick]')) {
    if (picks.length >= 6) return;
    picks.push({ ...picks[picks.length - 1] });
    return renderStats();
  }
  const drop = target.closest('[data-drop]');
  if (drop) { picks.splice(Number(drop.dataset.drop), 1); return renderStats(); }
  const mode = target.closest('[data-mode]');
  if (mode) {
    statsState.mode = mode.dataset.mode;
    if (statsState.mode === 'one') statsState.regions = statsState.regions.slice(0, 1);
    return renderStats();
  }
  if (target.closest('[data-zoom-reset]')) {
    statsState.zoom = null;
    return renderChartArea();
  }
  if (target.closest('[data-table]')) {
    statsState.table = !statsState.table;
    return renderStats();
  }
  if (target.closest('[data-export-series]')) {
    location.href = '/api/statistics/series.xlsx?' + statsParams();
  }
});

// The formula is re-evaluated on the server, so wait for a pause in typing.
let formulaTimer;
el('view-stats').addEventListener('input', event => {
  if (!event.target.matches('[data-expr]')) return;
  statsState.expr = event.target.value;
  clearTimeout(formulaTimer);
  formulaTimer = setTimeout(loadSeries, 400);
});

/* --- interaction: crosshair, readout, drag-to-zoom --- */

function attachChartInteraction() {
  const box = el('view-stats').querySelector('.plot');
  if (!box || !chartGeometry) return;
  const svg = box.querySelector('svg');
  const tip = box.querySelector('.tip');
  const cross = svg.querySelector('.crosshair');
  const crossLine = cross.querySelector('line');
  const crossDots = cross.querySelector('.crosshair-dots');
  const brush = svg.querySelector('.brush');
  const { x, y, model, step } = chartGeometry;
  const bars = statsState.type === 'bar';
  let current = -1;
  let dragFrom = null;

  const toPlotX = event => {
    const rect = svg.getBoundingClientRect();
    return ((event.clientX - rect.left) / rect.width) * PLOT.w;
  };
  const indexAt = plotX => {
    if (!model.labels.length) return -1;
    const raw = bars ? (plotX - PLOT.l) / step - 0.5 : (plotX - PLOT.l) / step;
    return Math.max(0, Math.min(model.labels.length - 1, Math.round(raw)));
  };

  function show(index) {
    if (index < 0 || index === current) return;
    current = index;
    const at = x(index);
    crossLine.setAttribute('x1', at.toFixed(1));
    crossLine.setAttribute('x2', at.toFixed(1));
    crossDots.replaceChildren();
    const present = [];
    for (const s of model.series) {
      const value = s.values[index];
      if (value === null || !isFinite(value)) continue;
      present.push(s);
      if (!s.named) continue;
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', at.toFixed(1));
      dot.setAttribute('cy', y(value).toFixed(1));
      dot.setAttribute('r', '6');
      dot.setAttribute('fill', s.colour);
      crossDots.appendChild(dot);
    }
    cross.hidden = false;

    // Labels come from the data, so they are inserted as text, never as markup.
    tip.replaceChildren();
    const head = document.createElement('b');
    head.textContent = model.labels[index];
    tip.appendChild(head);
    const named = present.filter(s => s.named);
    const listed = (named.length ? named : present).slice(0, 10);
    for (const s of listed) {
      const row = document.createElement('div');
      row.className = 'tip-row';
      const key = document.createElement('i');
      key.style.background = s.colour || 'var(--ink-3)';
      const value = document.createElement('b');
      value.textContent = fmt(s.values[index]);
      const name = document.createElement('span');
      name.textContent = s.name;
      row.append(key, value, name);
      tip.appendChild(row);
    }
    if (present.length > listed.length) {
      const more = document.createElement('div');
      more.className = 'tip-more';
      more.textContent = `и ещё ${count(present.length - listed.length)}`;
      tip.appendChild(more);
    }
    tip.hidden = false;
    const left = (at / PLOT.w) * box.clientWidth;
    tip.style.left = `${Math.min(box.clientWidth - tip.offsetWidth - 8, Math.max(8, left + 14))}px`;
  }

  function hide() {
    current = -1;
    cross.hidden = true;
    tip.hidden = true;
  }

  svg.addEventListener('pointermove', event => {
    const plotX = toPlotX(event);
    if (dragFrom !== null) {
      const from = Math.min(dragFrom, plotX), to = Math.max(dragFrom, plotX);
      brush.setAttribute('x', from.toFixed(1));
      brush.setAttribute('width', Math.max(0, to - from).toFixed(1));
      brush.hidden = false;
    }
    show(indexAt(plotX));
  });
  svg.addEventListener('pointerleave', () => { if (dragFrom === null) hide(); });

  svg.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    dragFrom = toPlotX(event);
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointerup', event => {
    if (dragFrom === null) return;
    const to = toPlotX(event);
    const wide = Math.abs(to - dragFrom) > 18;   // a click is not a zoom
    const [a, b] = [indexAt(Math.min(dragFrom, to)), indexAt(Math.max(dragFrom, to))];
    dragFrom = null;
    brush.hidden = true;
    if (wide && b > a) {
      const base = statsState.zoom ? statsState.zoom[0] : 0;
      statsState.zoom = [base + a, base + b];
      renderChartArea();
    }
  });
  svg.addEventListener('dblclick', () => {
    if (!statsState.zoom) return;
    statsState.zoom = null;
    renderChartArea();
  });

  // Keyboard parity: the same readout without a pointer.
  svg.addEventListener('keydown', event => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const next = current < 0 ? 0 : current + (event.key === 'ArrowRight' ? 1 : -1);
    show(Math.max(0, Math.min(model.labels.length - 1, next)));
  });
  svg.addEventListener('blur', hide);
}
