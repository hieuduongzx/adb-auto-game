/* Hub layout contracts — the shelf, its cards, and the bar above them.
 *
 * What has to hold together, across files that cannot check each other:
 *   · hub.css reflows the shelf (`--cols` 5 → 4 → 3 → 2 → 1 on a narrow window)
 *   · hub.js navigates by the columns actually laid out, not by a constant
 *   · covers are sized from the shelf's width, so a short window scrolls rather
 *     than shrinking every card in it
 *   · the cover is the button that runs the game, and Run + the tools are on the
 *     card at rest — flat, never hover-gated, and never nested inside the cover
 * So this test reads both files, runs hub.js in a bare VM to exercise its
 * geometry helpers and render a card, and cross-checks the numbers the two
 * files share.
 *
 * Run: node tests/test_hub_grid.cjs   (or `pytest tests/test_hub_ui.py`)
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');

const HUB = path.join(__dirname, '../apps/web/hub');
const read = (rel) => fs.readFileSync(path.join(HUB, rel), 'utf8');
const JS = read('js/hub.js');
const CSS = read('css/hub.css');
const HTML = read('index.html');

/** hub.js as loaded by the page, in a VM whose DOM is only as real as it needs
 *  to be: `readyState: 'loading'` keeps init() from running, `tracks` is what
 *  getComputedStyle reports for #grid, and a null element is a grid that is not
 *  in the document at all. `uiIco` stands in for the shared icon set so the
 *  card markup can be rendered and read here. */
function loadHub({ tracks = null, hasGrid = true } = {}) {
  const grid = {};
  const ctx = vm.createContext({
    window: { addEventListener() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById: (id) => (hasGrid && id === 'grid' ? grid : null),
    },
    getComputedStyle: () => ({ gridTemplateColumns: tracks }),
    uiIco: (name, cls) => `<svg data-ico="${name}" class="${cls || ''}"></svg>`,
  });
  vm.runInContext(JS, ctx);
  return ctx;
}

/** The body of the first `selector { … }` rule in the stylesheet — everything
 *  between its own braces, whether it is written on one line or over ten. No
 *  rule in these files nests another block, so stopping at the first `}` is
 *  exact. */
function rule(css, selector) {
  const m = new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^{}]*)\\}').exec(css);
  assert.ok(m, `${selector} rule must exist`);
  return m[1];
}

// ── trackCount — reading a laid-out column count ──────────────────────────────

test('trackCount counts the used tracks Chromium reports', () => {
  const ctx = loadHub();
  assert.equal(ctx.trackCount('185.6px 185.6px 185.6px 185.6px 185.6px', 5), 5);
  assert.equal(ctx.trackCount('206px 206px 206px', 5), 3);
  assert.equal(ctx.trackCount('240px', 5), 1);
});

test('trackCount reads a repeat() form instead of counting one track', () => {
  const ctx = loadHub();
  assert.equal(ctx.trackCount('repeat(3, 206px)', 5), 3);
  assert.equal(ctx.trackCount('repeat(2, minmax(0, 1fr))', 5), 2);
});

test('trackCount falls back when there is no layout to read', () => {
  const ctx = loadHub();
  for (const bad of [null, undefined, '', '   ', 'none']) {
    assert.equal(ctx.trackCount(bad, 5), 5, `${String(bad)} should fall back`);
  }
  assert.equal(ctx.trackCount('', 3), 3, 'the fallback is the caller\'s');
});

// ── gridColumns — the real arrow-key step ────────────────────────────────────

test('gridColumns follows the grid it is looking at', () => {
  assert.equal(loadHub({ tracks: '185px 185px 185px 185px 185px' }).gridColumns(), 5);
  assert.equal(loadHub({ tracks: '206px 206px 206px' }).gridColumns(), 3, 'reflowed shelf');
  assert.equal(loadHub({ tracks: '190px' }).gridColumns(), 1);
});

test('gridColumns never returns 0 or NaN for an unlaid-out grid', () => {
  assert.equal(loadHub({ tracks: 'none' }).gridColumns(), 5);
  assert.equal(loadHub({ hasGrid: false }).gridColumns(), 5);
  assert.equal(loadHub({ tracks: '' }).gridColumns(), 5);
});

// ── hub.js ↔ hub.css: one number, two files ──────────────────────────────────

test('navigation uses the laid-out columns, never a constant', () => {
  assert.doesNotMatch(JS, /\bCOLS\b/, 'a bare COLS constant must not steer the arrows');
  assert.match(JS, /ArrowUp:\s*-cols/, 'ArrowUp must step by the measured column count');
  assert.match(JS, /index < cols\)\s*\{\s*\$\("search"\)\.focus\(\)/, 'first row + Up leaves for search');
  assert.match(JS, /gridColumns\(\)\s*\*\s*2/, 'the skeleton fills two measured rows');
});

test('hub.css lays the shelf out from --cols, 5 by default', () => {
  const grid = rule(CSS, '.game-grid');
  assert.match(grid, /--cols:\s*5;/, 'the default shelf is five covers wide');
  assert.match(grid, /grid-template-columns:\s*repeat\(var\(--cols\),\s*var\(--card-w\)\)/);
  assert.doesNotMatch(grid, /repeat\(5,/, 'a hard-coded 5 would ignore the reflow');

  const fallback = /const GRID_COLS = (\d+)/.exec(JS);
  assert.ok(fallback, 'hub.js needs a GRID_COLS fallback');
  assert.equal(Number(fallback[1]), Number(/--cols:\s*(\d+)/.exec(grid)[1]),
    'the JS fallback and the CSS default must agree');
});

test('a cover is sized from the shelf width, never squeezed to fit the height', () => {
  const grid = rule(CSS, '.game-grid');
  const cardW = /--card-w:([\s\S]*?);/.exec(grid);
  assert.ok(cardW, '.game-grid must size its cards from --card-w');
  assert.match(cardW[1], /100cqw/, 'the columns fit across the shelf');
  assert.match(cardW[1], /var\(--cols\)/, 'and reflow with it');
  assert.doesNotMatch(cardW[1], /cqh/,
    'a height term would shrink covers to thumbnails on a short window — the shelf scrolls instead');
  assert.match(grid, /--card-max:\s*\d+px/, 'a cover stops growing at some sane width');

  // The shelf is only queried for width, and its rows are content-sized, so a
  // row that does not fit scrolls rather than resizing every card in it.
  assert.match(rule(CSS, '.lib-main'), /container-type:\s*inline-size/);
  assert.match(grid, /overflow-y:\s*auto/);
  assert.doesNotMatch(grid, /grid-auto-rows:\s*calc\(var\(--card-w\)/);
});

test('the library bar is a 64px title row, and controls match the search field', () => {
  assert.match(CSS, /:root\s*\{\s*--hdr-h:\s*64px;\s*\}/, 'the bar declares its own chrome height');
  assert.match(rule(CSS, '.lib-bar'), /height:\s*var\(--hdr-h\)/);
  assert.match(rule(CSS, '#search'), /height:\s*36px/);
  assert.match(CSS, /\.lib-actions \.btn\s*\{[^}]*height:\s*34px/,
    'bar buttons sit one step above the shared 30px .btn');
});

test('the reflow steps descend in width and in columns, down to one', () => {
  const steps = [...CSS.matchAll(/@media \(max-width:\s*(\d+)px\)\s*\{\s*\.game-grid\s*\{\s*--cols:\s*(\d+)/g)]
    .map(([, w, c]) => [Number(w), Number(c)]);
  assert.ok(steps.length >= 2, `expected reflow steps, found ${steps.length}`);
  for (let i = 1; i < steps.length; i++) {
    assert.ok(steps[i][0] < steps[i - 1][0], 'breakpoints must descend in width');
    assert.ok(steps[i][1] < steps[i - 1][1], 'columns must descend with them');
  }
  assert.equal(steps[0][1], 4, 'the first step reflows off five columns');
  assert.equal(steps[steps.length - 1][1], 1, 'the narrowest shelf is a single column');
});

// ── The rest of the narrow-window contract ───────────────────────────────────

test('the empty-state buttons can actually be hidden', () => {
  // Anchored at the start of a line: the app-wide rule, not the one scoped to
  // .lib-empty, has to be the thing that beats `.btn { display: inline-flex }`.
  assert.match(CSS, /^\[hidden\]\s*\{\s*display:\s*none\s*!important/m,
    'a toggled .btn needs to beat .btn { display: inline-flex }');
});

test('the wrapped header keeps the fixed offsets in step', () => {
  const bar = /@media \(max-width: 720px\) \{([\s\S]*?)\n\}/.exec(CSS);
  assert.ok(bar, 'the two-row bar rule must exist');
  const wrapped = /--hdr-h:\s*(\d+)px/.exec(bar[1]);
  assert.ok(wrapped, 'toasts and the build panel key off --hdr-h');
  assert.ok(Number(wrapped[1]) > 64, 'the two-row bar is taller than the one-row bar');
  assert.match(bar[1], /\.lib-bar\s*\{[\s\S]*?flex-wrap:\s*wrap/);
  assert.match(bar[1], /\.search-wrap\s*\{[^}]*order:\s*3/, 'the search takes its own row');
  assert.match(bar[1], /\.build-panel\s*\{[^}]*width:\s*auto/, 'the panel fits the window');
  assert.match(bar[1], /body\.bp-open #ui-toasts/, 'toasts stay on screen beside a full-width panel');
});

// ── The card — flat, and readable at rest ────────────────────────────────────

test('a card is a flat tile: hairline border, no shadow, no hover lift', () => {
  const card = rule(CSS, '.game');
  assert.match(card, /background:\s*var\(--panel\)/);
  assert.match(card, /border:\s*1px solid var\(--line\)/);
  assert.match(card, /border-radius:\s*var\(--r-md\)/);
  assert.doesNotMatch(card, /box-shadow/, 'a flat tile carries no elevation');

  const cover = rule(CSS, '.game-cover');
  assert.doesNotMatch(cover, /box-shadow/, 'the cover carries none either');
  assert.doesNotMatch(cover, /transform/, 'and does not lift');
  assert.doesNotMatch(CSS, /\.game:hover\s+\.game-cover/, 'no hover-lift rule may come back');
  assert.doesNotMatch(CSS, /\.game:hover\s+\.game-cover::after/, 'nor a hover scrim over the art');
});

test('Run and the card tools are on the card at rest, not hover-gated', () => {
  const tools = rule(CSS, '.game-tools');
  assert.doesNotMatch(tools, /opacity:\s*0/, 'the tools are always visible');
  assert.doesNotMatch(tools, /position:\s*absolute/, 'they belong to the card, not an overlay');
  const run = rule(CSS, '.game-run');
  assert.doesNotMatch(run, /opacity:\s*0/, 'so is Run');
  assert.doesNotMatch(CSS, /\.game:hover\s+\.game-run/, 'nothing may summon Run on hover');
  assert.doesNotMatch(CSS, /\.game:hover\s+\.game-tools/, 'nor the tools');

  // Both live in the footer row under the cover, which is markup (below), and
  // the footer is where the card's own tools sit — not over the artwork.
  const foot = rule(CSS, '.game-foot');
  assert.match(foot, /display:\s*flex/);
});

test('a card uses assets/icon as its icon, then the cover, then initials', () => {
  const ctx = loadHub();
  const withIcon = ctx.cardHtml(
    { name: 'BrownDust2', path: 'p', folder: 'BrownDust2', icon: 'file:///icon.png', cover: 'file:///cover.png', controller: 'win32', activityCount: 1 }, 0);
  assert.match(withIcon, /<img class="game-icon"[^>]*src="file:\/\/\/icon\.png"/);
  const withCover = ctx.cardHtml(
    { name: 'BrownDust2', path: 'p', folder: 'BrownDust2', cover: 'file:///cover.png', controller: 'win32', activityCount: 1 }, 0);
  assert.match(withCover, /<img class="game-icon"[^>]*src="file:\/\/\/cover\.png"/);
  const bare = ctx.cardHtml(
    { name: 'BrownDust2', path: 'p', folder: 'BrownDust2', controller: 'win32', activityCount: 1 }, 0);
  assert.match(bare, /class="game-icon icon-mono"[^>]*>BD</);
  const info = rule(CSS, '.game-info');
  assert.match(info, /grid-template-columns:\s*28px minmax\(0,\s*1fr\)/);
  const icon = rule(CSS, '.game-icon');
  assert.match(icon, /width:\s*28px/);
  assert.match(icon, /height:\s*28px/);
});

test('a card keeps the cover as its run button and repeats Run in the footer', () => {
  const ctx = loadHub();
  const html = ctx.cardHtml(
    { name: 'Nikke', path: 'workflows/Nikke', folder: 'Nikke', controller: 'adb', activityCount: 3 }, 0);
  const cover = /<button class="game-cover"[^>]*data-act="run"[^>]*>([\s\S]*?)<\/button>/.exec(html);
  assert.ok(cover, 'the cover is still the button that runs the game');
  assert.doesNotMatch(cover[1], /<button/, 'no button may be nested inside the cover button');

  const footAt = html.indexOf('<div class="game-foot">');
  assert.ok(footAt > cover.index, 'the footer sits under the cover');
  const foot = html.slice(footAt);
  assert.match(foot, /class="game-run"[^>]*data-act="run"/, 'Run is a button in the footer');
  assert.match(foot, /data-act="run"[^>]*>[\s\S]*?Run</, 'and it reads "Run"');
  for (const act of ['edit', 'build', 'delete']) {
    assert.match(foot, new RegExp(`data-act="${act}"`), `the ${act} tool belongs to the footer`);
  }
  assert.doesNotMatch(foot, /class="game-building"/, 'the build chip stays on the cover');
});

test('the skeleton stands in for the whole card, footer included', () => {
  assert.match(JS, /class="game-foot"[\s\S]*?sk-dots/, 'the loading card has a footer too');
  assert.match(rule(CSS, '.sk-line.run'), /height:\s*34px/, '…with the footer Run boxed');
  assert.match(rule(CSS, '.sk-dot'), /background:\s*var\(--alt\)/, 'and a box per tool');
});

test('a touch screen only enlarges what is already on the card', () => {
  const touch = /@media \(hover: none\) \{([\s\S]*?)\n\}/.exec(CSS);
  assert.ok(touch, 'a hover:none block must exist');
  assert.match(touch[1], /\.game-run\s*\{[^}]*height:\s*38px/);
  assert.match(touch[1], /\.game-tool\s*\{[^}]*width:\s*34px/);
});

// ── Markup ↔ script: every id hub.js reaches for exists ──────────────────────

test('every element hub.js looks up is in index.html', () => {
  // Built by script rather than markup, so they are not in index.html.
  const dynamic = new Set(['ui-toasts', 'update-overlay', 'upd-fill', 'upd-pct', 'upd-sub']);
  const used = [...new Set([...JS.matchAll(/\$\("([^"]+)"\)/g)].map(([, id]) => id))];
  assert.ok(used.includes('btn-empty-clear'), 'the no-match state needs a way out of the search');
  for (const id of used) {
    if (dynamic.has(id)) continue;
    assert.match(HTML, new RegExp(`id="${id}"`), `#${id} is missing from index.html`);
  }
});
