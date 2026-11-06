// Card lädt ohne Browser (Stubs) und Hilfsfunktionen rechnen korrekt.
const assert = require('node:assert/strict');
const path = require('node:path');
global.HTMLElement = class {};
global.customElements = { _d: {}, get(n) { return this._d[n]; }, define(n, c) { this._d[n] = c; } };
global.window = { customCards: [] };
const m = require(path.join(__dirname, '..', 'custom_components', 'smartify_heating', 'frontend', 'smartify-heating-card.js'));
assert.ok(customElements.get('smartify-heating-card'));
assert.ok(customElements.get('smartify-heating-card-editor'));
assert.equal(window.customCards[0].type, 'smartify-heating-card');
assert.equal(m.shcFmt(22.5, 'de-DE'), '22,5');
assert.equal(m.shcFmt(null), '–');
assert.equal(m.shcNum('unavailable'), null);
assert.equal(m.shcSparkPath([[0, 20]], 0, 10), null);
const p = m.shcSparkPath([[0, 20], [5, 21], [10, 22]], 0, 10);
assert.equal(p.line, 'M0.00,36.00L50.00,20.00L100.00,4.00');
assert.ok(p.area.endsWith('Z'));
console.log('Card tests passed');
