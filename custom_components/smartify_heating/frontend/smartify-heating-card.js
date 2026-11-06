/* smartify Heizung – Card + Editor
 * Raumregelung (Auto/Hand/Aus global und je Raum), Fensterabschaltung und
 * Fensterempfehlung. Logik läuft im Backend (custom_components/smartify_heating),
 * die Karte zeigt an und bedient.
 */
const SHC_VERSION = '0.1.0';

const SHC_MODES_GLOBAL = [['auto', 'Auto'], ['manual', 'Hand'], ['off', 'Aus']];
const SHC_MODES_ROOM = [['global', 'Global'], ['auto', 'Auto'], ['manual', 'Hand'], ['off', 'Aus']];
const SHC_REASONS = {
  zu_warm: 'Raum zu warm, außen kühler',
  im_soll: 'Im Sollbereich',
  aussen_zu_warm: 'Außen nicht kühl genug',
  soll_erreicht: 'Solltemperatur erreicht',
  lueftungsdauer: 'Maximale Lüftungsdauer erreicht',
  lueften_ok: 'Lüften noch sinnvoll',
  pause_nach_lueften: 'Pause nach dem Lüften',
  haltezeit: 'Haltezeit',
  sensorwert_fehlt: 'Sensorwert fehlt',
  start: '',
};
const SHC_ACTIONS = { heating: 'Heizbetrieb', idle: 'Leerlauf', off: 'Aus', cooling: 'Kühlbetrieb', fan: 'Lüften' };
const SHC_DEFAULTS = {
  title: 'Heizung',
  show_header: true,
  columns: 0,
  min_column_width: 220,
  collapsible: true,
  start_collapsed: false,
  show_graph: true,
  hours_to_show: 24,
  show_controls: true,
  show_mode: true,
  show_recommendation: true,
  hide_no_action: false,
  show_windows: true,
};

function shcEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function shcNum(v) {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : null;
}
function shcFmt(v, lang, digits = 1) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  return v.toLocaleString(lang || 'de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
/** Sparkline-Pfad aus [[t, v], …]; liefert {line, area} im viewBox 0..100 x 0..40. */
function shcSparkPath(points, start, end) {
  const pts = points.filter((p) => Number.isFinite(p[1]));
  if (pts.length < 2) return null;
  let min = Math.min(...pts.map((p) => p[1]));
  let max = Math.max(...pts.map((p) => p[1]));
  if (max - min < 0.5) { const mid = (max + min) / 2; min = mid - 0.25; max = mid + 0.25; }
  const span = Math.max(1, end - start);
  const x = (t) => Math.max(0, Math.min(100, ((t - start) / span) * 100));
  const y = (v) => 36 - ((v - min) / (max - min)) * 32;
  let line = '';
  pts.forEach((p, i) => {
    const px = x(p[0]).toFixed(2); const py = y(p[1]).toFixed(2);
    line += `${i === 0 ? 'M' : 'L'}${px},${py}`;
  });
  const area = `${line}L${x(pts.at(-1)[0]).toFixed(2)},40L${x(pts[0][0]).toFixed(2)},40Z`;
  return { line, area };
}

class SmartifyHeatingCard extends HTMLElement {
  static getConfigElement() { return document.createElement('smartify-heating-card-editor'); }
  static getStubConfig() { return { title: 'Heizung' }; }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._backend = null;
    this._backendError = '';
    this._collapsed = null;
    this._pending = {};
    this._timers = {};
    this._history = {};
    this._historyAt = 0;
    this._sig = '';
    this._onReload = () => { this._backend = null; this._loadBackend(); };
  }

  setConfig(config) {
    this._config = { ...SHC_DEFAULTS, ...(config || {}) };
    this._sig = '';
    this._collapsed = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._backend && !this._loading) this._loadBackend();
    this._maybeHistory();
    this._render();
  }

  connectedCallback() { window.addEventListener('smartify-heating-reload', this._onReload); }
  disconnectedCallback() { window.removeEventListener('smartify-heating-reload', this._onReload); }

  getCardSize() { return 6; }
  getGridOptions() { return { columns: 'full', rows: 'auto' }; }

  async _loadBackend() {
    if (!this._hass) return;
    this._loading = true;
    try {
      this._backend = await this._hass.callWS({ type: 'smartify_heating/config/get' });
      this._backendError = '';
      this._historyAt = 0;
      this._maybeHistory();
    } catch (err) {
      this._backendError = err?.message || 'Integration „smartify Heizung“ nicht geladen';
    } finally {
      this._loading = false;
      this._sig = '';
      this._render();
    }
  }

  _rooms() {
    const all = this._backend?.config?.rooms || [];
    const pick = Array.isArray(this._config.rooms) && this._config.rooms.length ? this._config.rooms : null;
    if (!pick) return all;
    return pick.map((id) => all.find((r) => r.id === id)).filter(Boolean);
  }

  _st(id) { return id ? this._hass?.states?.[id] : undefined; }

  _cooling() {
    const sw = this._backend?.config?.globals?.cooling_switch;
    return this._st(sw)?.state === 'on';
  }

  _climate(room) {
    return (this._cooling() && room.climate_cooling) ? room.climate_cooling : room.climate;
  }

  _insideEntity(room) { return room.temperature_sensor || null; }

  _inside(room) {
    const s = this._st(room.temperature_sensor);
    const v = s ? shcNum(s.state) : null;
    if (v !== null) return v;
    return shcNum(this._st(this._climate(room))?.attributes?.current_temperature);
  }

  _isCollapsed(id) {
    if (!this._config.collapsible) return false;
    if (!this._collapsed) {
      this._collapsed = {};
      try {
        const raw = localStorage.getItem('smartify-heating-collapsed');
        if (raw) this._collapsed = JSON.parse(raw) || {};
      } catch (_) { this._collapsed = {}; }
    }
    return id in this._collapsed ? this._collapsed[id] : !!this._config.start_collapsed;
  }

  _toggleRoom(id) {
    this._isCollapsed(id);
    this._collapsed[id] = !this._isCollapsed(id);
    try { localStorage.setItem('smartify-heating-collapsed', JSON.stringify(this._collapsed)); } catch (_) { /* privat */ }
    this._sig = '';
    this._render();
  }

  async _maybeHistory() {
    if (!this._hass || !this._backend || !this._config?.show_graph) return;
    const now = Date.now();
    if (now - this._historyAt < 10 * 60 * 1000 || this._historyLoading) return;
    // Verlauf aus dem Raumtemperatursensor (Thermostat-Attribute sind in minimal_response nicht enthalten)
    const ids = [...new Set(this._rooms().map((r) => r.temperature_sensor).filter(Boolean))];
    if (!ids.length) return;
    this._historyLoading = true;
    const hours = Math.max(1, Number(this._config.hours_to_show) || 24);
    const start = new Date(now - hours * 3600 * 1000);
    try {
      const res = await this._hass.callWS({
        type: 'history/history_during_period',
        start_time: start.toISOString(),
        end_time: new Date(now).toISOString(),
        entity_ids: ids,
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      const hist = {};
      for (const id of ids) {
        hist[id] = (res?.[id] || []).map((x) => {
          const v = shcNum(x.s);
          const t = ((x.lu ?? x.lc ?? 0) * 1000);
          return [t, v];
        }).filter((p) => p[1] !== null);
      }
      this._history = { start: start.getTime(), end: now, data: hist };
      this._historyAt = now;
    } catch (_) {
      this._historyAt = now; // nicht im Sekundentakt erneut versuchen
    } finally {
      this._historyLoading = false;
      this._sig = '';
      this._render();
    }
  }

  _signature() {
    const ids = new Set();
    const g = this._backend?.config?.globals || {};
    ids.add(g.outside_sensor); ids.add(g.cooling_switch);
    const ents = this._backend?.entities || {};
    ids.add(ents.global_mode); ids.add(ents.total);
    for (const r of this._rooms()) {
      [r.climate, r.climate_cooling, r.temperature_sensor, ...(r.windows || [])].forEach((x) => ids.add(x));
      const e = ents.rooms?.[r.id] || {};
      ids.add(e.mode); ids.add(e.recommendation); ids.add(e.window);
    }
    const parts = [];
    for (const id of ids) {
      if (!id) continue;
      const s = this._st(id);
      parts.push(id, s?.state, s?.attributes?.temperature, s?.attributes?.current_temperature,
        s?.attributes?.hvac_action, s?.attributes?.grund, s?.attributes?.wirksamer_modus, s?.attributes?.fensterabschaltung);
    }
    return JSON.stringify([parts, this._pending, this._collapsed, this._historyAt, this._backendError, !!this._backend]);
  }

  _render() {
    if (!this._config || !this._hass) return;
    const sig = this._signature();
    if (sig === this._sig) return;
    this._sig = sig;
    const lang = this._hass.locale?.language || this._hass.language || 'de';
    const c = this._config;

    let body;
    if (this._backendError) {
      body = `<div class="msg">${shcEsc(this._backendError)}<br><small>Integration installieren bzw. unter Einstellungen → Geräte &amp; Dienste hinzufügen.</small></div>`;
    } else if (!this._backend) {
      body = '<div class="msg">Lade …</div>';
    } else if (!this._rooms().length) {
      body = '<div class="msg">Noch keine Räume angelegt. Karte bearbeiten → Bereich „Räume“.</div>';
    } else {
      body = `<div class="grid">${this._rooms().map((r) => this._roomHtml(r, lang)).join('')}</div>`;
    }

    const cols = Number(c.columns) > 0 ? `repeat(${Number(c.columns)}, minmax(0, 1fr))`
      : `repeat(auto-fill, minmax(min(100%, ${Number(c.min_column_width) || 220}px), 1fr))`;

    this.shadowRoot.innerHTML = `<style>${SHC_STYLE}</style>
      <ha-card style="--shc-cols:${cols}">
        ${c.show_header ? this._headerHtml(lang) : ''}
        ${body}
      </ha-card>`;
    this.shadowRoot.querySelector('ha-card').addEventListener('click', (e) => this._onClick(e));
  }

  _headerHtml(lang) {
    const g = this._backend?.config?.globals || {};
    const ents = this._backend?.entities || {};
    const outside = shcNum(this._st(g.outside_sensor)?.state);
    const mode = this._st(ents.global_mode)?.state;
    const total = this._st(ents.total);
    const open = total?.attributes?.oeffnen || [];
    const close = total?.attributes?.schliessen || [];
    const summary = [
      close.length ? `<span class="pill close"><ha-icon icon="mdi:window-closed-variant"></ha-icon>${close.length}× schließen</span>` : '',
      open.length ? `<span class="pill open"><ha-icon icon="mdi:window-open-variant"></ha-icon>${open.length}× öffnen</span>` : '',
    ].join('');
    const seg = ents.global_mode ? `<div class="seg" role="group" aria-label="Modus gesamt">${SHC_MODES_GLOBAL.map(([k, l]) =>
      `<button class="${mode === k ? 'on' : ''} m-${k}" data-action="gmode" data-v="${k}">${l}</button>`).join('')}</div>` : '';
    return `<div class="head">
      <div class="ht">
        <span class="title">${shcEsc(this._config.title || '')}</span>
        <span class="meta">${g.outside_sensor ? `<ha-icon icon="mdi:home-thermometer-outline"></ha-icon>Außen ${shcFmt(outside, lang)} °C` : ''}
        ${this._cooling() ? '<span class="pill cool"><ha-icon icon="mdi:snowflake"></ha-icon>Kühlbetrieb</span>' : ''}${summary}</span>
      </div>
      ${seg}
    </div>`;
  }

  _roomHtml(room, lang) {
    const c = this._config;
    const ents = this._backend.entities?.rooms?.[room.id] || {};
    const climateId = this._climate(room);
    const cl = this._st(climateId);
    const inside = this._inside(room);
    const target = this._pending[climateId] ?? shcNum(cl?.attributes?.temperature) ?? room.target_temp;
    const action = cl?.attributes?.hvac_action || (cl?.state === 'off' ? 'off' : '');
    const modeSt = this._st(ents.mode);
    const mode = modeSt?.state;
    const eff = modeSt?.attributes?.wirksamer_modus;
    const paused = !!modeSt?.attributes?.fensterabschaltung;
    const recSt = this._st(ents.recommendation);
    const rec = recSt?.state;
    const winOpen = (room.windows || []).some((w) => ['on', 'open'].includes(this._st(w)?.state));
    const collapsed = this._isCollapsed(room.id);
    const heating = action === 'heating' || action === 'cooling';
    const statusText = cl ? (paused ? 'Fenster offen – aus' : (SHC_ACTIONS[action] || cl.state)) : '';
    const effLabel = (SHC_MODES_ROOM.find(([k]) => k === eff) || [])[1];

    const badges = [
      heating ? `<ha-icon class="b heat" icon="${action === 'cooling' ? 'mdi:snowflake' : 'mdi:fire'}" title="${statusText}"></ha-icon>` : '',
      eff && eff !== 'auto' ? `<span class="b tag m-${eff}">${effLabel}</span>` : '',
      winOpen ? '<ha-icon class="b win" icon="mdi:window-open-variant" title="Fenster offen"></ha-icon>' : '',
      rec === 'oeffnen' || rec === 'schliessen' ? `<span class="b dot ${rec}" title="Fenster ${rec === 'oeffnen' ? 'öffnen' : 'schließen'}"></span>` : '',
    ].join('');

    const sub = [
      `${shcFmt(inside, lang)} °C`,
      target !== null && target !== undefined ? `Soll ${shcFmt(target, lang)}` : '',
      collapsed ? statusText : '',
    ].filter(Boolean).join(' · ');

    let inner = '';
    if (!collapsed) {
      if (c.show_graph) inner += this._graphHtml(room);
      if (c.show_controls && cl) {
        inner += `<div class="ctl">
          <div class="status ${heating ? 'active' : ''}"><ha-icon icon="${paused ? 'mdi:window-open-variant' : heating ? 'mdi:fire' : 'mdi:thermostat'}"></ha-icon>${shcEsc(statusText)}</div>
          <div class="stepper ${cl.state === 'off' ? 'dim' : ''}">
            <button data-action="dec" data-room="${room.id}" aria-label="Soll senken">−</button>
            <span class="tv">${shcFmt(target, lang)}</span>
            <button data-action="inc" data-room="${room.id}" aria-label="Soll erhöhen">+</button>
          </div>
        </div>`;
      }
      if (c.show_mode && ents.mode) {
        inner += `<div class="seg small" role="group" aria-label="Modus ${shcEsc(room.name)}">${SHC_MODES_ROOM.map(([k, l]) =>
          `<button class="${mode === k ? 'on' : ''} m-${k}" data-action="rmode" data-room="${room.id}" data-v="${k}">${l}</button>`).join('')}</div>`;
      }
      if (c.show_recommendation && ents.recommendation && !(c.hide_no_action && rec === 'keine_aktion')) {
        const label = rec === 'oeffnen' ? 'Fenster öffnen' : rec === 'schliessen' ? 'Fenster schließen' : 'Keine Aktion';
        const icon = rec === 'oeffnen' ? 'mdi:window-open-variant' : rec === 'schliessen' ? 'mdi:window-closed-variant' : 'mdi:window-shutter-open';
        const reason = SHC_REASONS[recSt?.attributes?.grund] ?? recSt?.attributes?.grund ?? '';
        inner += `<div class="rec ${shcEsc(rec || '')}" data-action="more" data-entity="${ents.recommendation}">
          <ha-icon icon="${icon}"></ha-icon><div><b>${label}</b><small>${shcEsc(reason)}</small></div></div>`;
      }
      if (c.show_windows && room.windows?.length) {
        inner += `<div class="wins">${room.windows.map((w) => {
          const s = this._st(w);
          const open = ['on', 'open'].includes(s?.state);
          const name = s?.attributes?.friendly_name || w;
          const icon = s?.attributes?.device_class === 'door' ? (open ? 'mdi:door-open' : 'mdi:door-closed') : (open ? 'mdi:window-open-variant' : 'mdi:window-closed-variant');
          const txt = !s || s.state === 'unavailable' ? 'Nicht verfügbar' : open ? 'Offen' : 'Geschlossen';
          return `<div class="win ${open ? 'open' : ''}" data-action="more" data-entity="${w}"><ha-icon icon="${icon}"></ha-icon><span>${shcEsc(name)}</span><small>${txt}</small></div>`;
        }).join('')}</div>`;
      }
    }

    return `<div class="room ${collapsed ? 'collapsed' : ''}">
      <div class="rh" ${c.collapsible ? `data-action="toggle" data-room="${room.id}" role="button" tabindex="0" aria-expanded="${!collapsed}"` : ''}>
        <ha-icon class="ri" icon="${shcEsc(room.icon || 'mdi:thermometer')}"></ha-icon>
        <div class="rn"><span>${shcEsc(room.name)}</span><small>${sub}</small></div>
        <div class="badges">${badges}</div>
        ${c.collapsible ? '<ha-icon class="chev" icon="mdi:chevron-down"></ha-icon>' : ''}
      </div>
      ${collapsed ? '' : `<div class="rb">${inner}</div>`}
    </div>`;
  }

  _graphHtml(room) {
    const pts = (this._history?.data?.[room.temperature_sensor] || []).slice();
    const cur = this._inside(room);
    if (cur !== null) pts.push([Date.now(), cur]);
    const p = shcSparkPath(pts, this._history?.start || Date.now() - 86400000, Date.now());
    if (!p) return '<div class="graph empty"></div>';
    return `<svg class="graph" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
      <path class="area" d="${p.area}"></path><path class="line" d="${p.line}" vector-effect="non-scaling-stroke"></path></svg>`;
  }

  _onClick(e) {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const a = el.dataset.action;
    const room = this._rooms().find((r) => r.id === el.dataset.room);
    const ents = room ? this._backend.entities?.rooms?.[room.id] || {} : {};
    if (a === 'toggle') return this._toggleRoom(room.id);
    if (a === 'gmode') return this._select(this._backend.entities.global_mode, el.dataset.v);
    if (a === 'rmode') return this._select(ents.mode, el.dataset.v);
    if (a === 'inc' || a === 'dec') return this._step(room, a === 'inc' ? 1 : -1);
    if (a === 'more' && el.dataset.entity) {
      this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId: el.dataset.entity }, bubbles: true, composed: true }));
    }
  }

  _select(entity, option) {
    if (!entity) return;
    this._hass.callService('select', 'select_option', { entity_id: entity, option });
  }

  _step(room, dir) {
    const id = this._climate(room);
    const st = this._st(id);
    if (!st) return;
    const step = Number(st.attributes.target_temp_step) || 0.5;
    const cur = this._pending[id] ?? shcNum(st.attributes.temperature) ?? 20;
    const min = shcNum(st.attributes.min_temp) ?? 5;
    const max = shcNum(st.attributes.max_temp) ?? 30;
    const next = Math.min(max, Math.max(min, Math.round((cur + dir * step) / step) * step));
    this._pending[id] = next;
    this._sig = '';
    this._render();
    clearTimeout(this._timers[id]);
    this._timers[id] = setTimeout(async () => {
      try {
        await this._hass.callService('climate', 'set_temperature', { entity_id: id, temperature: next });
      } finally {
        delete this._pending[id];
        this._sig = '';
        this._render();
      }
    }, 800);
  }
}

const SHC_STYLE = `
:host{--shc-gap:10px;--shc-open:#3498db;--shc-close:#e74c3c;--shc-heat:#ef6c4a;--shc-radius:var(--ha-card-border-radius,12px)}
ha-card{padding:12px;box-sizing:border-box}
.head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin:0 2px 12px}
.ht{display:flex;flex-direction:column;gap:4px;min-width:0}
.title{font-size:1.15em;font-weight:700}
.meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px;color:var(--secondary-text-color);font-size:.9em}
.meta ha-icon,.pill ha-icon{--mdc-icon-size:16px}
.pill{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:999px;font-size:.85em;font-weight:600;color:#fff}
.pill.open{background:var(--shc-open)}.pill.close{background:var(--shc-close)}.pill.cool{background:#4fc3f7}
.seg{display:inline-flex;background:var(--secondary-background-color);border-radius:999px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--primary-text-color);font:inherit;font-weight:600;padding:6px 14px;border-radius:999px;cursor:pointer}
.seg button.on{background:var(--primary-color);color:var(--text-primary-color,#fff)}
.seg button.on.m-off{background:var(--disabled-text-color,#888)}
.seg button.on.m-manual{background:#f4a640;color:#fff}
.seg.small{display:flex;margin-top:8px}.seg.small button{flex:1;padding:5px 4px;font-size:.85em}
.grid{display:grid;grid-template-columns:var(--shc-cols);gap:var(--shc-gap);align-items:start}
.room{border:1px solid var(--divider-color);border-radius:var(--shc-radius);background:var(--card-background-color);overflow:hidden}
.rh{display:flex;align-items:center;gap:10px;padding:10px 12px;cursor:pointer;user-select:none}
.rh:focus-visible{outline:2px solid var(--primary-color);outline-offset:-2px}
.ri{--mdc-icon-size:24px;color:var(--primary-text-color)}
.rn{display:flex;flex-direction:column;min-width:0;flex:1}
.rn span{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rn small{color:var(--secondary-text-color);font-size:.88em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badges{display:flex;align-items:center;gap:4px}
.b{--mdc-icon-size:18px}.b.heat{color:var(--shc-heat)}.b.win{color:var(--shc-open)}
.b.tag{font-size:.72em;font-weight:700;padding:1px 6px;border-radius:6px;background:var(--secondary-background-color);text-transform:uppercase}
.b.tag.m-off{color:var(--disabled-text-color,#888)}.b.tag.m-manual{color:#f4a640}
.b.dot{width:10px;height:10px;border-radius:50%}.b.dot.oeffnen{background:var(--shc-open)}.b.dot.schliessen{background:var(--shc-close)}
.chev{--mdc-icon-size:20px;color:var(--secondary-text-color);transition:transform .2s}
.room:not(.collapsed) .chev{transform:rotate(180deg)}
.rb{padding:0 12px 12px}
.graph{display:block;width:100%;height:56px;margin-bottom:8px}
.graph.empty{height:8px}
.graph .area{fill:var(--secondary-background-color,#e8e8e8)}
.graph .line{fill:none;stroke:var(--primary-text-color);stroke-width:2;stroke-linejoin:round}
.ctl{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px}
.status{display:flex;align-items:center;gap:4px;min-width:0;font-size:.9em;color:var(--secondary-text-color)}
.status ha-icon{--mdc-icon-size:18px}.status.active{color:var(--shc-heat);font-weight:600}
.stepper{display:flex;align-items:center;background:var(--secondary-background-color);border-radius:12px}
.stepper.dim{opacity:.5}
.stepper button{width:38px;height:38px;border:0;background:transparent;font-size:1.4em;color:var(--primary-text-color);cursor:pointer;border-radius:12px}
.stepper .tv{min-width:46px;text-align:center;font-weight:700;font-size:1.1em}
.rec{display:flex;align-items:center;gap:10px;margin-top:8px;padding:8px 10px;border-radius:10px;cursor:pointer;background:var(--secondary-background-color)}
.rec ha-icon{--mdc-icon-size:22px}
.rec div{display:flex;flex-direction:column}.rec small{font-size:.8em;opacity:.85}
.rec.oeffnen{background:var(--shc-open);color:#fff}.rec.schliessen{background:var(--shc-close);color:#fff}
.rec.keine_aktion{color:var(--secondary-text-color)}
.wins{display:flex;flex-direction:column;gap:2px;margin-top:8px}
.win{display:grid;grid-template-columns:22px 1fr auto;align-items:center;gap:8px;padding:4px 2px;cursor:pointer;font-size:.92em}
.win ha-icon{--mdc-icon-size:20px;color:var(--secondary-text-color)}
.win small{color:var(--secondary-text-color)}
.win.open ha-icon,.win.open small{color:var(--shc-open);font-weight:600}
.msg{padding:16px;color:var(--secondary-text-color)}
`;

if (!customElements.get('smartify-heating-card')) customElements.define('smartify-heating-card', SmartifyHeatingCard);
window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === 'smartify-heating-card')) {
  window.customCards.push({ type: 'smartify-heating-card', name: 'smartify Heizung', description: 'Raumregelung Auto/Hand/Aus mit Fensterempfehlung' });
}

/* ------------------------------------------------------------------ Editor */
class SmartifyHeatingCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._openSections = new Set();
    this._openRooms = new Set();
    this._selectors = [];
    this._draft = null;
    this._dirty = false;
    this._status = '';
  }

  setConfig(config) {
    const incoming = JSON.parse(JSON.stringify(config || {}));
    if (this._config && JSON.stringify(incoming) === JSON.stringify(this._config)) return;
    this._config = incoming;
    if (this._hass) this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    for (const s of this._selectors) s.hass = hass;
    if (first) { this._loadBackend(); this._render(); }
  }

  async _loadBackend() {
    try {
      const res = await this._hass.callWS({ type: 'smartify_heating/config/get' });
      this._draft = JSON.parse(JSON.stringify(res.config));
      this._canEdit = res.can_edit;
      this._dirty = false;
      this._status = '';
    } catch (err) {
      this._draft = null;
      this._status = err?.message || 'Integration nicht geladen';
    }
    this._render();
  }

  _emit() {
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: JSON.parse(JSON.stringify(this._config)) }, bubbles: true, composed: true }));
  }

  _put(key, val) {
    if (val === '' || val === null || val === undefined) delete this._config[key]; else this._config[key] = val;
    this._emit();
  }

  _markDirty() {
    this._dirty = true;
    this._status = 'Nicht gespeicherte Änderungen';
    const bar = this.shadowRoot.querySelector('.savebar');
    if (bar) this._fillSaveBar(bar);
  }

  async _save() {
    this._status = 'Speichere …';
    this._render();
    try {
      const res = await this._hass.callWS({ type: 'smartify_heating/config/save', config: this._draft });
      this._draft = JSON.parse(JSON.stringify(res.config));
      this._dirty = false;
      this._status = 'Gespeichert';
      window.dispatchEvent(new CustomEvent('smartify-heating-reload'));
    } catch (err) {
      this._status = `Fehler: ${err?.message || err}`;
    }
    this._render();
  }

  /* ---- Bausteine ---- */
  _section(name, icon) {
    const section = document.createElement('section');
    const open = this._openSections.has(name);
    section.classList.toggle('collapsed', !open);
    const h = document.createElement('h3');
    h.setAttribute('role', 'button'); h.tabIndex = 0; h.setAttribute('aria-expanded', String(open));
    h.innerHTML = `<ha-icon icon="${icon}"></ha-icon><span class="sec-title">${shcEsc(name)}</span><ha-icon class="sec-chevron" icon="mdi:chevron-down"></ha-icon>`;
    section.append(h);
    const toggle = () => {
      const nowOpen = section.classList.toggle('collapsed') === false;
      h.setAttribute('aria-expanded', String(nowOpen));
      if (nowOpen) this._openSections.add(name); else this._openSections.delete(name);
    };
    h.addEventListener('click', toggle);
    h.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    this._body.append(section);
    return section;
  }

  _field(parent, label, el, hint = '') {
    const wrap = document.createElement('div'); wrap.className = 'field';
    if (label) { const l = document.createElement('label'); l.textContent = label; wrap.append(l); }
    wrap.append(el);
    if (hint) { const s = document.createElement('small'); s.textContent = hint; wrap.append(s); }
    parent.append(wrap);
    return wrap;
  }

  _input(parent, label, value, onChange, type = 'text', hint = '') {
    const i = document.createElement('input'); i.type = type; i.value = value ?? '';
    if (type === 'number') i.step = 'any';
    i.addEventListener('change', () => onChange(type === 'number' ? (i.value === '' ? null : Number(i.value)) : i.value));
    this._field(parent, label, i, hint);
    return i;
  }

  _toggle(parent, label, value, onChange) {
    const wrap = document.createElement('label'); wrap.className = 'tgl';
    const i = document.createElement('input'); i.type = 'checkbox'; i.checked = !!value;
    i.addEventListener('change', () => onChange(i.checked));
    const t = document.createElement('span'); t.textContent = label;
    wrap.append(i, t); parent.append(wrap);
  }

  _entity(parent, label, value, filter, onChange, multiple = false, hint = '') {
    if (customElements.get('ha-selector')) {
      const sel = document.createElement('ha-selector');
      sel.hass = this._hass;
      sel.selector = { entity: { multiple, filter } };
      sel.value = multiple ? (value || []) : (value || '');
      sel.label = label;
      sel.addEventListener('value-changed', (e) => onChange(e.detail.value ?? (multiple ? [] : '')));
      this._selectors.push(sel);
      this._field(parent, '', sel, hint);
      return sel;
    }
    // Fallback ohne HA-Selector: Text, mehrere mit Komma
    return this._input(parent, label, multiple ? (value || []).join(', ') : value,
      (v) => onChange(multiple ? String(v).split(',').map((x) => x.trim()).filter(Boolean) : v), 'text',
      hint || (multiple ? 'Entity-IDs mit Komma trennen' : ''));
  }

  _fillSaveBar(bar) {
    bar.innerHTML = '';
    const s = document.createElement('span'); s.textContent = this._status || (this._dirty ? '' : 'Alles gespeichert');
    const b = document.createElement('button'); b.textContent = 'Speichern'; b.disabled = !this._dirty || !this._canEdit;
    b.addEventListener('click', () => this._save());
    bar.append(s, b);
    bar.classList.toggle('dirty', this._dirty);
  }

  /* ---- Render ---- */
  _render() {
    if (!this._hass || !this._config) return;
    this._selectors = [];
    const c = { ...SHC_DEFAULTS, ...this._config };
    this.shadowRoot.innerHTML = `<style>${SHC_EDITOR_STYLE}</style>
      <div class="intro"><b>smartify Heizung · Editor</b><small>„Darstellung“ gilt nur für diese Karte. Räume, Allgemein und Fensterlogik gelten für die ganze Installation und werden mit „Speichern“ übernommen.</small></div>
      <div id="body"></div><div class="ver">v${SHC_VERSION}</div>`;
    this._body = this.shadowRoot.getElementById('body');

    // Darstellung (Kartenkonfiguration)
    let sec = this._section('Darstellung', 'mdi:palette-outline');
    this._input(sec, 'Titel', c.title, (v) => this._put('title', v));
    this._toggle(sec, 'Kopfzeile mit Gesamtmodus anzeigen', c.show_header, (v) => this._put('show_header', v));
    this._input(sec, 'Spalten (0 = automatisch)', c.columns, (v) => this._put('columns', v), 'number');
    this._input(sec, 'Mindestbreite je Raum (px)', c.min_column_width, (v) => this._put('min_column_width', v), 'number', 'Nur bei automatischen Spalten.');
    this._toggle(sec, 'Räume ein-/ausklappbar', c.collapsible, (v) => this._put('collapsible', v));
    this._toggle(sec, 'Räume anfangs eingeklappt', c.start_collapsed, (v) => this._put('start_collapsed', v));
    this._toggle(sec, 'Temperaturverlauf', c.show_graph, (v) => this._put('show_graph', v));
    this._input(sec, 'Verlauf (Stunden)', c.hours_to_show, (v) => this._put('hours_to_show', v), 'number');
    this._toggle(sec, 'Sollwert-Bedienung', c.show_controls, (v) => this._put('show_controls', v));
    this._toggle(sec, 'Raummodus (Global/Auto/Hand/Aus)', c.show_mode, (v) => this._put('show_mode', v));
    this._toggle(sec, 'Fensterempfehlung', c.show_recommendation, (v) => this._put('show_recommendation', v));
    this._toggle(sec, '„Keine Aktion“ ausblenden', c.hide_no_action, (v) => this._put('hide_no_action', v));
    this._toggle(sec, 'Fensterkontakte', c.show_windows, (v) => this._put('show_windows', v));
    if (this._draft?.rooms?.length) {
      const box = document.createElement('div'); box.className = 'roompick';
      const lbl = document.createElement('label'); lbl.textContent = 'Angezeigte Räume (keine Auswahl = alle)'; box.append(lbl);
      const chosen = new Set(Array.isArray(c.rooms) ? c.rooms : []);
      for (const r of this._draft.rooms) {
        this._toggle(box, r.name, chosen.has(r.id), (on) => {
          const order = this._draft.rooms.map((x) => x.id);
          if (on) chosen.add(r.id); else chosen.delete(r.id);
          this._put('rooms', order.filter((id) => chosen.has(id)));
        });
      }
      sec.append(box);
    }

    if (!this._draft) {
      const msg = document.createElement('div'); msg.className = 'warn';
      msg.textContent = this._status || 'Lade Konfiguration …';
      this._body.append(msg);
      return;
    }
    if (!this._canEdit) {
      const msg = document.createElement('div'); msg.className = 'warn';
      msg.textContent = 'Nur Administratoren können Räume und Fensterlogik ändern.';
      this._body.append(msg);
    }

    const bar = document.createElement('div'); bar.className = 'savebar';
    this._fillSaveBar(bar);
    this._body.append(bar);

    // Räume
    sec = this._section('Räume', 'mdi:floor-plan');
    this._draft.rooms.forEach((room, idx) => this._roomEditor(sec, room, idx));
    const add = document.createElement('button'); add.className = 'add'; add.textContent = '+ Raum hinzufügen';
    add.addEventListener('click', () => {
      const id = Math.random().toString(16).slice(2, 10);
      this._draft.rooms.push({ id, name: `Raum ${this._draft.rooms.length + 1}`, windows: [] });
      this._openRooms.add(id);
      this._markDirty(); this._render();
    });
    sec.append(add);

    // Allgemein
    sec = this._section('Allgemein', 'mdi:cog-outline');
    const g = this._draft.globals;
    this._entity(sec, 'Außentemperatur', g.outside_sensor, [{ domain: 'sensor', device_class: 'temperature' }, { domain: 'sensor' }],
      (v) => { g.outside_sensor = v; this._markDirty(); });
    this._entity(sec, 'Kühlbetrieb-Schalter (optional)', g.cooling_switch, [{ domain: ['switch', 'input_boolean', 'binary_sensor'] }],
      (v) => { g.cooling_switch = v; this._markDirty(); }, false, 'Ein = Kühl-Thermostate verwenden, Lüftungsdauer-Limit aus.');

    // Fensterlogik
    sec = this._section('Fensterlogik', 'mdi:window-open-variant');
    const p = this._draft.params;
    const num = (label, key, hint) => this._input(sec, label, p[key], (v) => { p[key] = v; this._markDirty(); }, 'number', hint);
    num('Öffnen ab Soll + (K)', 'open_above', 'Standard 1,0. Öffnen-Empfehlung, wenn der Raum so viel über Soll liegt.');
    num('Außen mind. kälter als innen (K)', 'open_min_delta', 'Standard 2,0.');
    num('Hysterese (K)', 'hysteresis', 'Standard 0,3. Eine laufende Öffnen-Empfehlung endet erst bei Schwelle minus Hysterese.');
    num('Schließen bei Soll + (K)', 'close_margin', 'Standard 0,3. Gap zum Öffnen = Öffnen-Schwelle − dieser Wert.');
    num('Schließen, wenn außen weniger kälter als (K)', 'close_delta', 'Standard 1,0.');
    num('Max. Lüftungsdauer (min, 0 = aus)', 'max_vent_min', 'Standard 15. Gilt nur im Heizbetrieb.');
    num('Pause nach Lüften (min)', 'cooldown_min', 'Standard 30. Danach erst wieder Öffnen-Empfehlung.');
    num('Mindest-Haltezeit (min)', 'hold_min', 'Standard 5. Verhindert Flattern bei geschlossenem Fenster.');
    num('Fensterabschaltung nach (s)', 'shutdown_delay_s', 'Standard 60. Nur Modus Auto: Thermostat aus, solange ein Kontakt offen ist.');
    num('Wiedereinschalten nach (s)', 'restore_delay_s', 'Standard 30 nach dem Schließen aller Kontakte.');

    // Sicherung
    sec = this._section('Sicherung & Wiederherstellung', 'mdi:content-save-cog-outline');
    const ta = document.createElement('textarea'); ta.className = 'json';
    ta.value = JSON.stringify(this._draft, null, 2);
    this._field(sec, 'Konfiguration als JSON', ta, 'Exportieren: kopieren. Importieren: einfügen, „Übernehmen“ und danach „Speichern“.');
    const apply = document.createElement('button'); apply.className = 'add'; apply.textContent = 'JSON übernehmen';
    apply.addEventListener('click', () => {
      try {
        const parsed = JSON.parse(ta.value);
        this._draft = { globals: { ...this._draft.globals, ...(parsed.globals || {}) }, params: { ...this._draft.params, ...(parsed.params || {}) }, rooms: parsed.rooms || [] };
        this._markDirty(); this._render();
      } catch (err) { this._status = `JSON ungültig: ${err.message}`; this._render(); }
    });
    sec.append(apply);
  }

  _roomEditor(parent, room, idx) {
    const box = document.createElement('div'); box.className = 'room' + (this._openRooms.has(room.id) ? '' : ' collapsed');
    const head = document.createElement('div'); head.className = 'rhead';
    head.innerHTML = `<ha-icon icon="mdi:chevron-down" class="sec-chevron"></ha-icon><b>${shcEsc(room.name)}</b><small>${(room.windows || []).length} Kontakt(e)</small>`;
    const actions = document.createElement('span'); actions.className = 'ract';
    const btn = (icon, title, fn, disabled = false) => {
      const b = document.createElement('button'); b.title = title; b.disabled = disabled;
      b.innerHTML = `<ha-icon icon="${icon}"></ha-icon>`;
      b.addEventListener('click', (e) => { e.stopPropagation(); fn(); });
      actions.append(b);
    };
    const rooms = this._draft.rooms;
    btn('mdi:arrow-up', 'Nach oben', () => { [rooms[idx - 1], rooms[idx]] = [rooms[idx], rooms[idx - 1]]; this._markDirty(); this._render(); }, idx === 0);
    btn('mdi:arrow-down', 'Nach unten', () => { [rooms[idx + 1], rooms[idx]] = [rooms[idx], rooms[idx + 1]]; this._markDirty(); this._render(); }, idx === rooms.length - 1);
    btn('mdi:delete-outline', 'Raum entfernen', () => {
      if (!confirm(`Raum „${room.name}“ entfernen? Die zugehörigen Entitäten werden beim Speichern gelöscht.`)) return;
      rooms.splice(idx, 1); this._markDirty(); this._render();
    });
    head.append(actions);
    head.addEventListener('click', () => {
      const open = box.classList.toggle('collapsed') === false;
      if (open) this._openRooms.add(room.id); else this._openRooms.delete(room.id);
    });
    box.append(head);

    const body = document.createElement('div'); body.className = 'rbody';
    const set = (key) => (v) => { room[key] = v; this._markDirty(); };
    this._input(body, 'Name', room.name, (v) => { room.name = v; head.querySelector('b').textContent = v; this._markDirty(); });
    this._input(body, 'Kürzel für Entity-IDs', room.slug, set('slug'), 'text',
      'z. B. „buro“ → sensor.buro_fenster_empfehlung. Leer = aus dem Namen.');
    this._entity(body, 'Thermostat', room.climate, [{ domain: 'climate' }], set('climate'));
    this._entity(body, 'Kühl-Thermostat (optional)', room.climate_cooling, [{ domain: 'climate' }], set('climate_cooling'));
    this._entity(body, 'Raumtemperatur (optional)', room.temperature_sensor, [{ domain: 'sensor', device_class: 'temperature' }, { domain: 'sensor' }],
      set('temperature_sensor'), false, 'Leer = Ist-Temperatur des Thermostats.');
    this._entity(body, 'Fenster-/Türkontakte', room.windows, [{ domain: 'binary_sensor' }],
      (v) => { room.windows = v; head.querySelector('small').textContent = `${v.length} Kontakt(e)`; this._markDirty(); }, true,
      'Mehrere möglich. Offen, sobald ein Kontakt offen ist. Ohne Kontakt keine Fensterempfehlung.');
    this._input(body, 'Soll-Temperatur ohne Thermostat (°C)', room.target_temp, set('target_temp'), 'number',
      'Nur für Räume ohne Thermostat (z. B. Stiegenhaus) als Basis der Empfehlung.');
    this._input(body, 'Icon (optional)', room.icon, set('icon'), 'text', 'z. B. mdi:bed');
    box.append(body);
    parent.append(box);
  }
}

const SHC_EDITOR_STYLE = `
:host{display:block}
.intro{display:flex;flex-direction:column;gap:4px;margin-bottom:12px}.intro small{color:var(--secondary-text-color)}
section{border:1px solid var(--divider-color);border-radius:10px;margin-bottom:10px;overflow:hidden}
section>h3{display:flex;align-items:center;gap:10px;margin:0;padding:12px;font-size:15px;cursor:pointer;user-select:none}
section>h3 .sec-title{flex:1}
.sec-chevron{transition:transform .2s}
section:not(.collapsed)>h3 .sec-chevron,.room:not(.collapsed)>.rhead .sec-chevron{transform:rotate(180deg)}
section.collapsed>:not(h3){display:none!important}
section>:not(h3){margin-left:12px;margin-right:12px}
section>:last-child{margin-bottom:12px}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:12px}
.field label{font-size:13px;font-weight:600}
.field small{color:var(--secondary-text-color);font-size:12px}
input[type=text],input[type=number],textarea{box-sizing:border-box;width:100%;padding:9px 10px;border:1px solid var(--divider-color);border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit}
.tgl{display:flex;align-items:center;gap:8px;margin-bottom:10px;cursor:pointer}
.roompick{border-top:1px solid var(--divider-color);padding-top:10px}
.roompick>label{display:block;font-size:13px;font-weight:600;margin-bottom:8px}
.room{border:1px solid var(--divider-color);border-radius:8px;margin-bottom:8px}
.rhead{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer}
.rhead b{flex:0 1 auto}.rhead small{flex:1;color:var(--secondary-text-color)}
.ract{display:flex;gap:2px}
.ract button{border:0;background:transparent;color:var(--primary-text-color);width:34px;height:34px;border-radius:8px;cursor:pointer}
.ract button:disabled{opacity:.3;cursor:default}
.room.collapsed .rbody{display:none}
.rbody{padding:4px 10px 4px}
.add{box-sizing:border-box;width:calc(100% - 24px);min-height:40px;border:0;border-radius:8px;background:var(--primary-color);color:var(--text-primary-color,#fff);cursor:pointer;font:inherit}
.savebar{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 12px;margin-bottom:10px;border-radius:10px;background:var(--secondary-background-color)}
.savebar.dirty{outline:2px solid var(--warning-color,#f4a640)}
.savebar span{font-size:13px;color:var(--secondary-text-color)}
.savebar button{border:0;border-radius:8px;padding:8px 16px;background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;cursor:pointer}
.savebar button:disabled{opacity:.4;cursor:default}
.warn{padding:10px 12px;border-radius:8px;background:var(--secondary-background-color);margin-bottom:10px}
.json{min-height:160px;font:12px monospace}
.ver{text-align:right;font-size:11px;color:var(--secondary-text-color)}
`;

if (!customElements.get('smartify-heating-card-editor')) customElements.define('smartify-heating-card-editor', SmartifyHeatingCardEditor);

if (typeof module !== 'undefined') module.exports = { shcSparkPath, shcFmt, shcNum, SHC_VERSION };
