/* BragerOne dashboard card, shipped with the brager_one integration. */
const CARD_VERSION = "1.2.0";
const DOMAIN = "brager_one";

const TEXT = {
  en: {
    boiler: "Boiler",
    on: "On",
    off: "Off",
    confirm_on: "Tap again to start the boiler",
    confirm_off: "Tap again to stop the boiler",
    boiler_temperature: "Boiler temperature",
    setpoint: "Setpoint",
    hot_water_setpoint: "Hot water",
    return_temperature: "Return",
    feeder_temperature: "Feeder",
    flame_brightness: "Flame",
    blower_output: "Blower",
    burner_power: "Power",
    pumps: "Pumps",
    boiler_pump: "Boiler pump",
    return_pump: "Return pump",
    hot_water_pump: "Hot water pump",
    running: "running",
    stopped: "stopped",
    unknown: "unknown",
    state_standby: "Standby",
    state_work: "Work",
    state_code: "State code {code}",
    no_alarms: "No active alarms",
    active_alarm_one: "1 active alarm",
    active_alarm_many: "{n} active alarms",
    since: "since {time}",
    last_alarm: "Last alarm",
    ended: "ended {time}",
    still_open: "no end time",
    lower: "Lower {name}",
    raise: "Raise {name}",
    unavailable: "BragerOne is not reachable right now",
    no_device: "Choose a BragerOne device in the card settings.",
    device: "Device",
    name: "Name (optional)",
  },
  nl: {
    boiler: "Ketel",
    on: "Aan",
    off: "Uit",
    confirm_on: "Tik nogmaals om de ketel te starten",
    confirm_off: "Tik nogmaals om de ketel te stoppen",
    boiler_temperature: "Keteltemperatuur",
    setpoint: "Instelling",
    hot_water_setpoint: "Tapwater",
    return_temperature: "Retour",
    feeder_temperature: "Vijzel",
    flame_brightness: "Vlam",
    blower_output: "Ventilator",
    burner_power: "Vermogen",
    pumps: "Pompen",
    boiler_pump: "Ketelpomp",
    return_pump: "Retourpomp",
    hot_water_pump: "Tapwaterpomp",
    running: "draait",
    stopped: "uit",
    unknown: "onbekend",
    state_standby: "Stand-by",
    state_work: "In bedrijf",
    state_code: "Toestandscode {code}",
    no_alarms: "Geen actieve alarmen",
    active_alarm_one: "1 actief alarm",
    active_alarm_many: "{n} actieve alarmen",
    since: "sinds {time}",
    last_alarm: "Laatste alarm",
    ended: "beëindigd {time}",
    still_open: "geen eindtijd",
    lower: "{name} verlagen",
    raise: "{name} verhogen",
    unavailable: "BragerOne is nu niet bereikbaar",
    no_device: "Kies een BragerOne-apparaat in de kaartinstellingen.",
    device: "Apparaat",
    name: "Naam (optioneel)",
  },
};

// Alarm texts per language. English comes from the integration itself.
const ALARM_TEXT = {
  nl: {
    0: "Ketelsensor defect", 1: "Retoursensor defect", 2: "Tapwatersensor defect",
    3: "Vijzelsensor defect", 4: "Buitensensor defect", 5: "Mengklep 1 sensor defect",
    6: "Buffersensor (boven) defect", 7: "Rookgassensor defect", 8: "Brandstofniveausensor defect",
    13: "Vlamsensor defect", 15: "Ventilatortoerentalsensor defect", 18: "Buffersensor (onder) defect",
    23: "Ketel oververhit", 24: "Tapwater oververhit", 25: "Vijzel te heet (terugbrandgevaar)",
    26: "Veiligheidsthermostaat (STB) aangesproken", 28: "Vijzel geblokkeerd", 30: "Rookgas te heet",
    31: "Geen trek (schoorsteen of deur open)", 38: "Brandstof op", 39: "Bunkerdeksel open",
    44: "Ventilatorstoring", 54: "Ontsteken mislukt", 55: "Stroomonderbreking",
    56: "Opstartassistent vereist", 57: "Onderhoud of inspectie vereist", 170: "Storing asafvoer",
    500: "Ernstig alarm op afstand gereset door de gebruiker", 501: "Module niet verbonden",
  },
};

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

function bragerDevices(hass) {
  const ids = new Set();
  for (const entry of Object.values(hass?.entities || {})) {
    if (entry.platform === DOMAIN && entry.device_id) ids.add(entry.device_id);
  }
  return [...ids];
}

class BragerOneCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pendingSetpoints = {};
    this._timers = {};
    this._confirmUntil = 0;
    this._signature = "";
  }

  static getStubConfig(hass) {
    const device = bragerDevices(hass)[0];
    return device ? { device_id: device } : {};
  }

  static getConfigElement() {
    return document.createElement("brager-one-card-editor");
  }

  setConfig(config) {
    this._config = { ...config };
    this._signature = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _t(key, vars = {}) {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").split("-")[0];
    const table = TEXT[lang] || TEXT.en;
    let text = table[key] ?? TEXT.en[key] ?? key;
    for (const [name, value] of Object.entries(vars)) text = text.replace(`{${name}}`, value);
    return text;
  }

  _alarmText(alarm) {
    const lang = this._lang().split("-")[0];
    return ALARM_TEXT[lang]?.[alarm.code] || alarm.description || String(alarm.code ?? "");
  }

  _lang() {
    return this._hass?.locale?.language || this._hass?.language || "en";
  }

  _entities() {
    const deviceId = this._config?.device_id || bragerDevices(this._hass)[0];
    const map = {};
    if (!deviceId) return { deviceId, map };
    for (const entry of Object.values(this._hass.entities || {})) {
      if (entry.platform !== DOMAIN || entry.device_id !== deviceId) continue;
      const key = entry.translation_key || entry.entity_id.split(".")[1];
      map[key] = entry.entity_id;
    }
    return { deviceId, map };
  }

  _state(map, key) {
    const id = map[key];
    return id ? this._hass.states[id] : undefined;
  }

  _number(value, digits = 1, minDigits = 0) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "–";
    return n.toLocaleString(this._lang(), {
      minimumFractionDigits: minDigits,
      maximumFractionDigits: digits,
    });
  }

  _time(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(this._lang(), {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _render() {
    if (!this._hass || !this._config) return;
    const { deviceId, map } = this._entities();
    const watched = Object.values(map).map((id) => this._hass.states[id]);
    const signature = JSON.stringify([
      deviceId,
      this._config,
      this._lang(),
      this._pendingSetpoints,
      this._confirmUntil > Date.now(),
      watched.map((s) => (s ? [s.state, s.last_updated] : null)),
    ]);
    if (signature === this._signature) return;
    this._signature = signature;

    if (!deviceId || !Object.keys(map).length) {
      this.shadowRoot.innerHTML = `${this._styles()}<ha-card><div class="empty">${esc(this._t("no_device"))}</div></ha-card>`;
      return;
    }

    const device = this._hass.devices?.[deviceId];
    const title = this._config.name || device?.name_by_user || device?.name || "BragerOne";
    const boiler = this._state(map, "boiler");
    const temp = this._state(map, "boiler_temperature");
    const unavailable = !temp || temp.state === "unavailable";

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <ha-card>
        <div class="header">
          <ha-icon class="flame ${boiler?.state === "on" ? "lit" : ""}" icon="${boiler?.state === "on" ? "mdi:fire" : "mdi:fire-off"}"></ha-icon>
          <div class="title">
            <div class="name">${esc(title)}</div>
            ${this._stateLine(map)}
          </div>
          ${this._switch(boiler)}
        </div>
        ${unavailable ? `<div class="banner warn" role="status"><span class="mark">▲</span>${esc(this._t("unavailable"))}</div>` : ""}
        ${this._main(map)}
        ${this._tiles(map)}
        ${this._pumps(map)}
        ${this._alarms(map)}
      </ha-card>`;
    this._bind(map);
  }

  _stateLine(map) {
    const state = this._state(map, "operating_state");
    const code = this._state(map, "operating_state_code");
    let label;
    let icon = "mdi:help-circle-outline";
    if (state && ["standby", "work"].includes(state.state)) {
      label = this._t(`state_${state.state}`);
      icon = state.state === "work" ? "mdi:play-circle-outline" : "mdi:pause-circle-outline";
    } else if (code && !["unknown", "unavailable"].includes(code.state)) {
      label = this._t("state_code", { code: this._number(code.state, 0) });
    } else {
      label = this._t("unknown");
    }
    const id = state?.entity_id || code?.entity_id || "";
    return `<button class="state link" data-more="${esc(id)}"><ha-icon icon="${icon}"></ha-icon>${esc(label)}</button>`;
  }

  _switch(boiler) {
    if (!boiler) return "";
    const on = boiler.state === "on";
    const confirming = this._confirmUntil > Date.now();
    const disabled = boiler.state === "unavailable" ? "disabled" : "";
    const hint = confirming ? `<div class="hint">${esc(this._t(on ? "confirm_off" : "confirm_on"))}</div>` : "";
    return `
      <div class="power">
        <button class="power-btn ${on ? "on" : "off"} ${confirming ? "confirming" : ""}" data-action="toggle" ${disabled}
          aria-pressed="${on}" aria-label="${esc(this._t("boiler"))}: ${esc(this._t(on ? "on" : "off"))}">
          <ha-icon icon="mdi:power"></ha-icon><span>${esc(this._t(on ? "on" : "off"))}</span>
        </button>
        ${hint}
      </div>`;
  }

  _setpointControl(map, key, label) {
    const st = this._state(map, key);
    if (!st) return "";
    const pending = this._pendingSetpoints[key];
    const value = pending ?? Number(st.state);
    const min = Number(st.attributes.min);
    const max = Number(st.attributes.max);
    const disabled = st.state === "unavailable" ? "disabled" : "";
    return `
      <div class="setpoint" data-key="${key}">
        <div class="label">${esc(label)}</div>
        <div class="stepper">
          <button class="step" data-step="-1" data-key="${key}" ${disabled || value <= min ? "disabled" : ""}
            aria-label="${esc(this._t("lower", { name: label }))}"><ha-icon icon="mdi:minus"></ha-icon></button>
          <button class="value link ${pending !== undefined ? "pending" : ""}" data-more="${esc(st.entity_id)}">${esc(this._number(value, 0))} °C</button>
          <button class="step" data-step="1" data-key="${key}" ${disabled || value >= max ? "disabled" : ""}
            aria-label="${esc(this._t("raise", { name: label }))}"><ha-icon icon="mdi:plus"></ha-icon></button>
        </div>
      </div>`;
  }

  _main(map) {
    const temp = this._state(map, "boiler_temperature");
    const setpoint = this._state(map, "boiler_setpoint");
    const current = Number(temp?.state);
    const target = Number(this._pendingSetpoints.boiler_setpoint ?? setpoint?.state);
    let bar = "";
    if (setpoint && Number.isFinite(current)) {
      const lo = Math.min(20, current);
      const hi = Math.max(Number(setpoint.attributes.max) || 90, current);
      const pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
      bar = `
        <div class="bar" role="img" aria-label="${esc(this._number(current))} °C / ${esc(this._number(target, 0))} °C">
          <div class="fill" style="width:${pct(current)}%"></div>
          ${Number.isFinite(target) ? `<div class="target" style="left:${pct(target)}%"></div>` : ""}
        </div>`;
    }
    return `
      <div class="main">
        <button class="big link" data-more="${esc(temp?.entity_id || "")}">
          <div class="label">${esc(this._t("boiler_temperature"))}</div>
          <div class="reading">${esc(this._number(temp?.state))}<span class="unit"> °C</span></div>
        </button>
        <div class="controls">
          ${this._setpointControl(map, "boiler_setpoint", this._t("setpoint"))}
          ${this._setpointControl(map, "hot_water_setpoint", this._t("hot_water_setpoint"))}
        </div>
      </div>
      ${bar}`;
  }

  _tiles(map) {
    const tiles = [
      ["return_temperature", "mdi:thermometer-minus", "°C", 1],
      ["feeder_temperature", "mdi:screw-machine-flat-top", "°C", 1],
      ["flame_brightness", "mdi:fire", "%", 0],
      ["blower_output", "mdi:fan", "%", 0],
      ["burner_power", "mdi:fire-circle", "kW", 1, 1],
    ];
    const html = tiles
      .map(([key, icon, unit, digits, minDigits = 0]) => {
        const st = this._state(map, key);
        if (!st) return "";
        return `
          <button class="tile link" data-more="${esc(st.entity_id)}">
            <ha-icon icon="${icon}"></ha-icon>
            <span class="tile-label">${esc(this._t(key))}</span>
            <span class="tile-value">${esc(this._number(st.state, digits, minDigits))} ${unit}</span>
          </button>`;
      })
      .join("");
    return html ? `<div class="tiles">${html}</div>` : "";
  }

  _pumps(map) {
    const keys = ["boiler_pump", "return_pump", "hot_water_pump"];
    const chips = keys
      .map((key) => {
        const st = this._state(map, key);
        if (!st) return "";
        const on = st.state === "on";
        const known = ["on", "off"].includes(st.state);
        const word = known ? this._t(on ? "running" : "stopped") : this._t("unknown");
        const icon = on ? "mdi:pump" : "mdi:pump-off";
        return `
          <button class="chip link ${on ? "on" : ""}" data-more="${esc(st.entity_id)}">
            <ha-icon icon="${icon}"></ha-icon>${esc(this._t(key))}: <strong>${esc(word)}</strong>
          </button>`;
      })
      .join("");
    return chips ? `<div class="pumps" aria-label="${esc(this._t("pumps"))}">${chips}</div>` : "";
  }

  _alarms(map) {
    const active = this._state(map, "active_alarms");
    const last = this._state(map, "last_alarm");
    let html = "";
    if (active) {
      const list = active.attributes.alarms || [];
      if (list.length) {
        const items = list
          .map(
            (a) =>
              `<li><strong>${esc(this._alarmText(a))}</strong> (${esc(a.code)})${a.started ? ` · ${esc(this._t("since", { time: this._time(a.started) }))}` : ""}</li>`,
          )
          .join("");
        html += `
          <button class="banner alarm link" role="alert" data-more="${esc(active.entity_id)}">
            <span class="mark">▲</span>
            <div><strong>${esc(this._t(list.length === 1 ? "active_alarm_one" : "active_alarm_many", { n: list.length }))}</strong><ul>${items}</ul></div>
          </button>`;
      } else if (active.state !== "unavailable") {
        html += `
          <button class="banner ok link" data-more="${esc(active.entity_id)}">
            <span class="mark">✓</span>${esc(this._t("no_alarms"))}
          </button>`;
      }
    }
    if (last && last.state && !["unknown", "unavailable"].includes(last.state)) {
      const a = last.attributes;
      const end = a.ended ? this._t("ended", { time: this._time(a.ended) }) : this._t("still_open");
      html += `
        <button class="last link" data-more="${esc(last.entity_id)}">
          <ha-icon icon="mdi:history"></ha-icon>
          <span>${esc(this._t("last_alarm"))}: ${esc(this._time(last.state))} · ${esc(this._alarmText(a))} · ${esc(end)}</span>
        </button>`;
    }
    return html ? `<div class="alarms">${html}</div>` : "";
  }

  _bind(map) {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-more]").forEach((el) => {
      if (!el.dataset.more) return;
      el.addEventListener("click", () => this._moreInfo(el.dataset.more));
    });
    root.querySelectorAll("[data-step]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._step(map, el.dataset.key, Number(el.dataset.step));
      });
    });
    const toggle = root.querySelector('[data-action="toggle"]');
    if (toggle) toggle.addEventListener("click", () => this._toggle(map));
  }

  _moreInfo(entityId) {
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }),
    );
  }

  _step(map, key, delta) {
    const st = this._state(map, key);
    if (!st) return;
    const min = Number(st.attributes.min);
    const max = Number(st.attributes.max);
    const step = Number(st.attributes.step) || 1;
    const base = this._pendingSetpoints[key] ?? Number(st.state);
    if (!Number.isFinite(base)) return;
    const next = Math.max(min, Math.min(max, base + delta * step));
    this._pendingSetpoints = { ...this._pendingSetpoints, [key]: next };
    this._render();
    clearTimeout(this._timers[key]);
    // Collect several taps into one write to the stove.
    this._timers[key] = setTimeout(async () => {
      try {
        await this._hass.callService("number", "set_value", { entity_id: st.entity_id, value: next });
      } finally {
        const pending = { ...this._pendingSetpoints };
        delete pending[key];
        this._pendingSetpoints = pending;
        this._render();
      }
    }, 1200);
  }

  _toggle(map) {
    const boiler = this._state(map, "boiler");
    if (!boiler) return;
    const now = Date.now();
    // Starting or stopping a stove is not something to do by accident:
    // the first tap arms, the second tap within 4 seconds sends.
    if (this._confirmUntil < now) {
      this._confirmUntil = now + 4000;
      this._render();
      setTimeout(() => this._render(), 4100);
      return;
    }
    this._confirmUntil = 0;
    this._hass.callService("switch", boiler.state === "on" ? "turn_off" : "turn_on", {
      entity_id: boiler.entity_id,
    });
    this._render();
  }

  _styles() {
    return `<style>
      :host { display: block; }
      ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; line-height: 1.45; }
      button { font: inherit; color: inherit; background: none; border: 0; padding: 0; text-align: left; cursor: pointer; }
      button:disabled { cursor: default; opacity: 0.45; }
      button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; border-radius: 8px; }
      .empty { color: var(--secondary-text-color); }
      .header { display: flex; align-items: center; gap: 12px; }
      .flame { --mdc-icon-size: 32px; color: var(--secondary-text-color); }
      .flame.lit { color: var(--state-climate-heat-color, #e8702a); }
      .title { flex: 1; min-width: 0; }
      .name { font-size: 1.2em; font-weight: 600; }
      .state { display: inline-flex; align-items: center; gap: 4px; color: var(--secondary-text-color); }
      .state ha-icon { --mdc-icon-size: 18px; }
      .power { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
      .power-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 20px;
        border: 2px solid var(--divider-color); font-weight: 600; }
      .power-btn.on { border-color: var(--state-climate-heat-color, #e8702a); }
      .power-btn.confirming { background: var(--secondary-background-color); border-style: dashed; }
      .hint { font-size: 0.85em; color: var(--secondary-text-color); max-width: 180px; text-align: right; }
      .main { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
      .label { font-size: 0.9em; color: var(--secondary-text-color); }
      .reading { font-size: 2.6em; font-weight: 600; line-height: 1.1; }
      .unit { font-size: 0.45em; font-weight: 400; color: var(--secondary-text-color); }
      .controls { display: flex; gap: 16px; flex-wrap: wrap; }
      .stepper { display: flex; align-items: center; gap: 4px; }
      .step { width: 36px; height: 36px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
        background: var(--secondary-background-color); }
      .value { min-width: 64px; text-align: center; font-size: 1.15em; font-weight: 600; }
      .value.pending { text-decoration: none; border-bottom: 2px dashed var(--primary-color); }
      .bar { position: relative; margin: 2px 0 4px; height: 8px; border-radius: 4px; background: var(--secondary-background-color); }
      .fill { height: 100%; border-radius: 4px; background: var(--state-climate-heat-color, #e8702a); }
      .target { position: absolute; top: -4px; width: 3px; height: 16px; background: var(--primary-text-color); transform: translateX(-1px); }
      .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
      .tile { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto; column-gap: 8px; padding: 10px;
        border-radius: 12px; background: var(--secondary-background-color); }
      .tile ha-icon { grid-row: span 2; align-self: center; color: var(--secondary-text-color); }
      .tile-label { font-size: 0.85em; color: var(--secondary-text-color); overflow-wrap: anywhere; }
      .tile-value { font-weight: 600; }
      .pumps { display: flex; flex-wrap: wrap; gap: 8px; }
      .chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 16px;
        border: 1px solid var(--divider-color); }
      .chip ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
      .chip.on ha-icon { color: var(--state-active-color, var(--primary-color)); }
      .alarms { display: flex; flex-direction: column; gap: 8px; }
      .banner { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 12px; width: 100%; box-sizing: border-box; }
      .banner .mark { font-weight: 700; }
      .banner.ok { background: var(--secondary-background-color); }
      .banner.ok .mark { color: var(--success-color, #2e7d4f); }
      .banner.alarm, .banner.warn { border: 2px solid var(--error-color, #c2410c); }
      .banner.alarm .mark, .banner.warn .mark { color: var(--error-color, #c2410c); }
      .banner ul { margin: 4px 0 0; padding-left: 18px; }
      .last { display: flex; gap: 8px; align-items: center; color: var(--secondary-text-color); font-size: 0.9em; }
      .last ha-icon { --mdc-icon-size: 18px; }
    </style>`;
  }
}

class BragerOneCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const lang = (this._hass.locale?.language || "en").split("-")[0];
    const t = TEXT[lang] || TEXT.en;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) => t[schema.name === "device_id" ? "device" : "name"];
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...this._config, ...ev.detail.value };
        for (const key of Object.keys(config)) if (config[key] === "" || config[key] === undefined) delete config[key];
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "device_id", selector: { device: { integration: DOMAIN } } },
      { name: "name", selector: { text: {} } },
    ];
  }
}

if (!customElements.get("brager-one-card")) {
  customElements.define("brager-one-card", BragerOneCard);
  customElements.define("brager-one-card-editor", BragerOneCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "brager-one-card",
    name: "BragerOne",
    description: "Pellet stove or boiler on BragerOne: temperatures, setpoints, pumps and alarms.",
    preview: true,
    documentationURL: "https://github.com/Meppies/ha-brager-one",
  });
  console.info(`%c BRAGER-ONE-CARD %c ${CARD_VERSION} `, "background:#e8702a;color:#fff", "");
}
