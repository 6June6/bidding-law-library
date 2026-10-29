/**
 * 检索回归测试：把 index.html 里的脚本抽出来在 Node 里跑（用最小 DOM mock），
 * 校验召回、排序、同义扩展、条号直达，并测量耗时。
 *
 *   node tools/test_search.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.dirname(__dirname);
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

function grab(id) {
  const re = new RegExp('<script id="' + id + '"[^>]*>([\\s\\S]*?)</script>');
  const m = html.match(re);
  if (!m) throw new Error('script#' + id + ' 未找到');
  return m[1];
}
const IDX_RAW = grab('idx').replace(/\u0000SCRIPT\u0000/g, '<\/script');
const BLOB = grab('blob').split('\u0000SCRIPT\u0000').join('<\/script');
const IDX = JSON.parse(IDX_RAW);

// 取最后一个 <script>（无 id 的那个，即主逻辑）
const scripts = [...html.matchAll(/<script(?![^>]*\bid=)[^>]*>([\s\S]*?)<\/script>/g)];
const MAIN = scripts[scripts.length - 1][1];

// ---------------- 最小 DOM mock ----------------
function mkEl() {
  const el = {
    _html: '', textContent: '', value: '', dataset: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){return false} },
    style: {}, offsetTop: 0, scrollTop: 0, clientHeight: 800, scrollHeight: 2000,
    get innerHTML() { return this._html },
    set innerHTML(v) { this._html = v },
    querySelectorAll(){ return [] }, querySelector(){ return null },
    appendChild(){}, addEventListener(){}, scrollIntoView(){}, focus(){},
    setSelectionRange(){}, getBoundingClientRect(){ return {top:0,left:0,width:800,height:600} },
    closest(){ return null },
  };
  return el;
}
const els = {};
const document = {
  getElementById(id) {
    if (id === 'idx') return { textContent: IDX_RAW };
    if (id === 'blob') return { textContent: BLOB };
    if (!els[id]) els[id] = mkEl();
    return els[id];
  },
  addEventListener(){}, querySelector(){ return mkEl() },
  querySelectorAll(){ return [] }, createElement(){ return mkEl() },
  body: { classList: { add(){}, remove(){}, toggle(){}, contains(){return false} } },
};
const window = { innerWidth: 1400 };
const location = { hash: '' };
const sandbox = {
  document, window, location, console,
  setTimeout: (f, t) => 0, clearTimeout(){}, requestAnimationFrame(){},
  encodeURI, Math, JSON, Map, Set, Array, Object, String, Number, Date, RegExp, Error,
};
sandbox.globalThis = sandbox;
// 脚本里是 const/let，不会挂到 sandbox 上，追加一段导出桥接
const BRIDGE = `
;globalThis.__api = {
  get RESULT(){return RESULT}, set RESULT(v){RESULT=v},
  get kw(){return kw}, set kw(v){kw=v},
  get scope(){return scope}, set scope(v){scope=v},
  get sortBy(){return sortBy}, set sortBy(v){sortBy=v},
  get SHOWN(){return SHOWN}, set SHOWN(v){SHOWN=v},
  F, cache, doSearch, snippets, unitText, parseQuery, expand, docAt,
  DOCS, BLOB, UNITS, ARTS, N
};`;
vm.createContext(sandbox);
vm.runInContext(MAIN + BRIDGE, sandbox);

const api = sandbox.__api;
const { DOCS, N } = api;

// ---------------- 断言 ----------------
let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '  → ' + extra : '')); }
}
function q(str, opts = {}) {
  api.kw = str;
  api.scope = opts.scope || 'all';
  api.sortBy = opts.sort || 'rel';
  Object.assign(api.F, { level: '全部', region: '全部', tag: '全部', issuer: '全部' }, opts.F || {});
  api.cache.clear();
  const t0 = process.hrtime.bigint();
  api.doSearch();
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  return { r: api.RESULT, ms };
}
function top(res, n = 5) {
  return res.slice(0, n).map(x => DOCS[x.i].t);
}

console.log('\n=== 1. 找法：按名称检索 ===');
let r = q('招标投标法');
check('首位是《中华人民共和国招标投标法》', top(r.r, 1)[0] === '中华人民共和国招标投标法', top(r.r, 1)[0]);
check('命中数 > 20', r.r.length > 20, r.r.length);
console.log('    前5：' + top(r.r, 5).join(' / '));

r = q('政府采购法');
check('首位是政府采购法', top(r.r, 1)[0] === '中华人民共和国政府采购法', top(r.r, 1)[0]);

r = q('招标投标法实施条例');
check('首位是实施条例', top(r.r, 1)[0] === '中华人民共和国招标投标法实施条例', top(r.r, 1)[0]);

console.log('\n=== 2. 正文检索与条文定位 ===');
r = q('投标保证金');
check('投标保证金召回 > 40 件', r.r.length > 40, r.r.length);
const sn = api.snippets(r.r[0], 3);
check('首条能给出条文级定位', sn.length > 0 && /第.+条|^[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）/.test(sn[0].label), JSON.stringify(sn[0] && sn[0].label));
console.log('    首条：' + DOCS[r.r[0].i].t + ' → ' + sn.map(s => s.label).join(' , '));

r = q('评标委员会');
check('评标委员会召回 > 60', r.r.length > 60, r.r.length);

console.log('\n=== 3. 同义扩展（法律术语） ===');
r = q('串标');
const hasSyn = r.r.some(x => DOCS[x.i].t.includes('招标投标') || true);
check('"串标"能召回讲"串通投标"的文件', r.r.length > 10, r.r.length);
const synCheck = r.r.some(x => {
  const d = DOCS[x.i];
  return api.BLOB.slice(d.s, d.e).includes('串通投标');
});
check('确有命中来自"串通投标"而非"串标"字面', synCheck);

r = q('围标');
check('"围标"亦有召回', r.r.length > 5, r.r.length);

console.log('\n=== 4. 条号直达（汉字↔数字归一） ===');
r = q('招标投标法 第36条');
const first36 = r.r[0];
check('带条号查询首位仍是招标投标法', DOCS[first36.i].t === '中华人民共和国招标投标法', DOCS[first36.i].t);
check('定位到具体单元', first36.art >= 0, first36.art);
if (first36.art >= 0) {
  const lbl = api.UNITS[first36.art][2];
  check('目标单元是第36条', /三十六|36/.test(lbl), lbl);
  console.log('    定位：' + lbl + ' → ' + api.unitText(first36.art).slice(0, 50).replace(/\s+/g, ' '));
}
r = q('招标投标法 第三十六条');
check('汉字条号同样可定位', r.r[0].art >= 0 && /三十六|36/.test(api.UNITS[r.r[0].art][2]),
  r.r.length ? api.UNITS[r.r[0].art][2] : '无结果');

console.log('\n=== 5. 排除与精确短语 ===');
const a = q('保证金');
const b = q('保证金 -政府采购');
check('排除词生效（结果变少）', b.r.length < a.r.length, a.r.length + ' → ' + b.r.length);
const c = q('"串通投标"');
check('引号短语有召回', c.r.length > 0, c.r.length);

console.log('\n=== 6. 地区维度（属地管辖） ===');
r = q('建设工程勘察设计管理条例', { F: { region: '浙江' } });
const regs = r.r.map(x => DOCS[x.i].rg);
check('选浙江时结果只含浙江 + 全国', regs.every(x => x === '浙江' || x === '全国'), [...new Set(regs)].join(','));
check('浙江省条例排在前面', r.r[0] && DOCS[r.r[0].i].rg === '浙江', r.r[0] && DOCS[r.r[0].i].t);
console.log('    前3：' + top(r.r, 3).join(' / '));

r = q('勘察设计管理条例', { F: { region: '山西' } });
check('山西同理', r.r[0] && DOCS[r.r[0].i].rg === '山西', r.r[0] && DOCS[r.r[0].i].t);

console.log('\n=== 7. 层级 / 标签筛选 ===');
r = q('招标', { F: { level: '法律' } });
check('层级筛选只出法律', r.r.every(x => DOCS[x.i].lv === '法律'));
r = q('', { F: { tag: '政府采购' } });
check('主题标签筛选生效', r.r.length > 10 && r.r.every(x => DOCS[x.i].tg.includes('政府采购')), r.r.length);
r = q('', { F: { issuer: '住房和城乡建设部' } });
check('机关筛选生效（归一后 156 件）', r.r.length > 100, r.r.length);

console.log('\n=== 8. 排序 ===');
r = q('保证金', { sort: 'date' });
const dates = r.r.slice(0, 20).map(x => DOCS[x.i].pb).filter(Boolean);
check('按日期倒序', dates.every((d, i) => i === 0 || dates[i - 1] >= d), dates.slice(0, 3).join(','));
r = q('保证金', { sort: 'level' });
check('按层级排序，法律在前', DOCS[r.r[0].i].lv === '法律', DOCS[r.r[0].i].lv);

console.log('\n=== 9. 性能（全文 223 万字） ===');
const qs = ['投标保证金', '评标委员会', '招标', '串通投标', '建设工程质量', '必须招标 项目 范围'];
let tot = 0;
for (const s of qs) {
  api.cache.clear();
  const t0 = process.hrtime.bigint();
  api.kw = s; api.scope = 'all'; api.sortBy = 'rel';
  Object.assign(api.F, { level: '全部', region: '全部', tag: '全部', issuer: '全部' });
  api.doSearch();
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  tot += ms;
  console.log('    "' + s + '"  ' + ms.toFixed(1) + ' ms  （命中 ' + api.RESULT.length + ' 件）');
}
console.log('    平均 ' + (tot / qs.length).toFixed(1) + ' ms / 次');
check('单次检索 < 120ms', tot / qs.length < 120, (tot / qs.length).toFixed(1) + 'ms');

console.log('\n=== 结果 ===');
console.log(pass + ' 通过, ' + fail + ' 失败');
process.exit(fail ? 1 : 0);
