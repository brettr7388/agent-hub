/* Agent Hub Pips. SVG fragments below use only fixed, local geometry. */
(function (root) {
  'use strict';
  const palettes = Object.freeze({
    blue: ['#5BB0FF', '#2F7BFF'], violet: ['#B794FF', '#7C4DFF'], teal: ['#5EE0C1', '#14A88A'],
    charcoal: ['#4A5568', '#1A202C'], coral: ['#FF8FA3', '#F0456A'], orange: ['#FFB86B', '#F07A1A'],
    yellow: ['#FFE686', '#EDAA23'], lime: ['#B9E978', '#66AD34'], mint: ['#89E7C8', '#31B997'],
    sky: ['#91DBF3', '#35A5D7'], indigo: ['#8F9CFF', '#4B5CD5'], magenta: ['#ED9BE8', '#BD4AAD'],
    red: ['#F69489', '#D95755'], brown: ['#CDAA86', '#97663D']
  });
  const colors = Object.keys(palettes);
  const eyes = Object.freeze(['dots', 'happy', 'wide', 'sleepy', 'sparkle']);
  const antennaTips = Object.freeze(['dot', 'star', 'bolt', 'heart']);
  const visors = Object.freeze(['round', 'squircle']);
  const accessories = Object.freeze(['none', 'scarf', 'bow', 'glasses', 'cap', 'compass', 'pencil', 'magnifier', 'code', 'hard_hat', 'envelope', 'calendar', 'chart', 'paintbrush', 'headphones', 'chef_hat', 'graduation_cap', 'wrench', 'shield', 'globe', 'camera', 'music_note', 'dollar_coin', 'heart', 'book', 'lightbulb', 'rocket', 'leaf', 'gamepad', 'megaphone']);
  const defaults = Object.freeze({ palette: 'blue', accessory: 'none', eyes: 'dots', antenna: 'dot', visor: 'round' });
  const cache = new Map();
  const dark = '#0D1B2E';
  function pick(value, options, fallback) { return typeof value === 'string' && options.includes(value) ? value : fallback; }
  function normalizeSpec(input) {
    const s = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
    return {
      palette: pick(s.palette || s.color, colors, defaults.palette),
      accessory: pick(s.accessory, accessories, defaults.accessory),
      eyes: pick(s.eyes, eyes, defaults.eyes),
      antenna: pick(s.antenna || s.antenna_tip, antennaTips, defaults.antenna),
      visor: pick(s.visor, visors, defaults.visor)
    };
  }
  function hash(value) { let h = 2166136261; for (const c of String(value || '')) { h ^= c.codePointAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  function roleAccessory(agent) {
    const text = [agent?.name, agent?.title, agent?.role, agent?.instructions].filter(v => typeof v === 'string').join(' ').toLowerCase();
    if (agent?.guide || agent?.is_guide || String(agent?.name || '').toLowerCase() === 'guide') return 'compass';
    const rules = [
      [/cod(e|er|ing)|develop|program|software|engineer|javascript|python/, 'code'],
      [/research|search|investigat|analys|detect|find/, 'magnifier'],
      [/audio|podcast|listen|sound|transcrib/, 'headphones'],
      [/writ|edit|author|copy|content|script/, 'pencil'],
      [/ops|operat|build|deploy|infrastructure|construct/, 'hard_hat'],
      [/inbox|email|mail|reply|messag/, 'envelope'],
      [/schedul|calendar|plan|appointment/, 'calendar'],
      [/chart|metric|data|statistic|report|analytics/, 'chart'],
      [/design|paint|illustrat|\bart\b|creative/, 'paintbrush'],
      [/chef|cook|recipe|food|kitchen/, 'chef_hat'],
      [/teach|learn|tutor|school|educat/, 'graduation_cap'],
      [/repair|fix|maintain|mechanic|tool/, 'wrench'],
      [/secur|guard|protect|audit|privacy/, 'shield'],
      [/travel|world|global|language|translat/, 'globe'],
      [/photo|camera|video|film|clip/, 'camera'],
      [/music|song|melody|compos/, 'music_note'],
      [/financ|money|budget|account|sales|revenue/, 'dollar_coin'],
      [/health|care|wellness|therapy|medic/, 'heart'],
      [/book|read|document|librar/, 'book'],
      [/idea|brainstorm|invent|strateg/, 'lightbulb'],
      [/launch|startup|rocket|growth/, 'rocket'],
      [/garden|plant|nature|environment|sustainab/, 'leaf'],
      [/game|play|gaming/, 'gamepad'],
      [/market|promot|advertis|announce|outreach/, 'megaphone']
    ];
    return (rules.find(([rx]) => rx.test(text)) || [null, ['none', 'scarf', 'bow', 'glasses', 'cap'][hash(agent?.id) % 5]])[1];
  }
  function baseSpec(agent) {
    const h = hash(agent?.id);
    if (agent?.guide || agent?.is_guide || String(agent?.name || '').toLowerCase() === 'guide') return { ...defaults, accessory: 'compass' };
    return { palette: colors[h % colors.length], accessory: roleAccessory(agent), eyes: eyes[(h >>> 4) % eyes.length], antenna: antennaTips[(h >>> 8) % antennaTips.length], visor: visors[(h >>> 12) % visors.length] };
  }
  function signature(s) { return [s.palette, s.accessory, s.eyes, s.antenna, s.visor].join('|'); }
  function candidate(base, seed, n) {
    if (!n) return base;
    const k = (seed % 560 + n * 13) % 560;
    return { ...base, palette: colors[k % 14], eyes: eyes[Math.floor(k / 14) % 5], antenna: antennaTips[Math.floor(k / 70) % 4], visor: visors[Math.floor(k / 280) % 2] };
  }
  function assignPips(agents) {
    if (!Array.isArray(agents)) return [];
    const sorted = agents.filter(a => a && a.id != null && a.avatar_style !== 'emoji').slice().sort((a, b) => String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0);
    const used = new Map();
    for (const a of sorted) if (a.pip_style) { const key = signature(normalizeSpec(a.pip_style)); used.set(key, (used.get(key) || 0) + 1); }
    const assigned = [];
    for (const a of sorted) {
      if (a.pip_style) continue;
      const base = baseSpec(a), seed = hash(a.id), first = signature(base);
      let best = base, least = used.get(first) || 0;
      if (least) {
        // Preserve the role accessory; vary the remaining 560 combinations.
        for (let n = 1; n < 560; n++) {
          const next = candidate(base, seed, n), count = used.get(signature(next)) || 0;
          if (count < least) { best = next; least = count; if (!count) break; }
        }
      }
      used.set(signature(best), (used.get(signature(best)) || 0) + 1);
      assigned.push({ id: a.id, pip_style: best });
    }
    return assigned;
  }
  function pipFor(agent, workspaceAgents) {
    if (agent?.pip_style) return normalizeSpec(agent.pip_style);
    if (Array.isArray(workspaceAgents)) {
      const found = assignPips(workspaceAgents).find(x => String(x.id) === String(agent?.id));
      if (found) return found.pip_style;
    }
    return baseSpec(agent || {});
  }
  const eyeArt = {
    dots: '<circle cx="25" cy="34" r="4" fill="#fff"/><circle cx="39" cy="34" r="4" fill="#fff"/><circle cx="26.2" cy="32.8" r="1.3" fill="#0D1B2E"/><circle cx="40.2" cy="32.8" r="1.3" fill="#0D1B2E"/>',
    happy: '<path d="M21 35q4-5 8 0M35 35q4-5 8 0" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>',
    wide: '<circle cx="25" cy="34" r="5" fill="#fff"/><circle cx="39" cy="34" r="5" fill="#fff"/><circle cx="26" cy="33" r="1.6" fill="#0D1B2E"/><circle cx="40" cy="33" r="1.6" fill="#0D1B2E"/>',
    sleepy: '<path d="M21 35q4 3 8 0M35 35q4 3 8 0" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>',
    sparkle: '<path d="M25 29l1.5 4.5L31 35l-4.5 1.5L25 41l-1.5-4.5L19 35l4.5-1.5zM39 29l1.5 4.5L45 35l-4.5 1.5L39 41l-1.5-4.5L33 35l4.5-1.5z" fill="#fff"/>'
  };
  const tipArt = {
    dot: '<circle cx="32" cy="7" r="3.6" fill="#FFB547"/>',
    star: '<path d="M32 2l1.5 3.3 3.5.5-2.6 2.5.6 3.5-3-1.7-3 1.7.6-3.5L27 5.8l3.5-.5z" fill="#FFB547"/>',
    bolt: '<path d="M33 1l-5 7h3l-1 5 6-8h-3z" fill="#FFB547"/>',
    heart: '<path d="M32 11l-4.4-4.1c-3.5-3.4 1-7.1 4.4-3.2 3.4-3.9 7.9.8 4.4 3.2z" fill="#FFB547"/>'
  };
  const accessoryArt = {
    none: '',
    scarf: '<path d="M13 47q19 9 38 0v5q-18 10-38 0z" fill="#FFD166" stroke="#0D1B2E" stroke-width="1.5"/>',
    bow: '<path d="M32 49l-10-4v9l10-4 10 4v-9z" fill="#FFD166" stroke="#0D1B2E" stroke-width="2"/><circle cx="32" cy="49" r="3" fill="#0D1B2E"/>',
    glasses: '<circle cx="25" cy="34" r="7" fill="none" stroke="#FFD166" stroke-width="2"/><circle cx="39" cy="34" r="7" fill="none" stroke="#FFD166" stroke-width="2"/><path d="M32 34h0" stroke="#FFD166" stroke-width="3"/>',
    cap: '<path d="M17 20q15-12 30 0v3H17z" fill="#FFD84D" stroke="#0D1B2E" stroke-width="2"/><path d="M44 22h10" stroke="#0D1B2E" stroke-width="2"/>',
    compass: '<circle cx="49" cy="48" r="8" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M52 44l-5 2-2 6 5-2z" fill="#2F7BFF" stroke="#0D1B2E" stroke-width="1"/>',
    pencil: '<g transform="rotate(35 50 46)"><rect x="47" y="34" width="6" height="20" rx="1.5" fill="#FFD166"/><path d="M47 54l3 6 3-6z" fill="#0D1B2E"/></g>',
    magnifier: '<circle cx="49" cy="47" r="7" fill="none" stroke="#0D1B2E" stroke-width="3"/><path d="M54 52l5 5" stroke="#0D1B2E" stroke-width="3.5" stroke-linecap="round"/>',
    code: '<path d="M24 29l-5 5 5 5M40 29l5 5-5 5M34 28l-4 12" stroke="#7CFFB2" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    hard_hat: '<path d="M14 18q18-14 36 0v3H14z" fill="#FFD84D" stroke="#0D1B2E" stroke-width="2"/>',
    envelope: '<rect x="42" y="40" width="17" height="12" rx="2" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M42.5 41l8 6 8-6" stroke="#0D1B2E" stroke-width="2" fill="none"/>',
    calendar: '<rect x="43" y="40" width="15" height="15" rx="2" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M43 45h15M47 38v5M54 38v5" stroke="#0D1B2E" stroke-width="2"/><circle cx="49" cy="50" r="1.5" fill="#F0456A"/>',
    chart: '<path d="M43 54V42M48 54V47M53 54V38M58 54V44" stroke="#0D1B2E" stroke-width="3" stroke-linecap="round"/>',
    paintbrush: '<path d="M47 55l10-16" stroke="#0D1B2E" stroke-width="3"/><path d="M56 38q5-1 3 5l-5 2-2-5z" fill="#FFD166"/><path d="M46 54q-2 6-6 5 2-5 6-5" fill="#F0456A"/>',
    headphones: '<path d="M16 34v-5a16 16 0 0 1 32 0v5" fill="none" stroke="#FFD166" stroke-width="3"/><rect x="12" y="31" width="7" height="12" rx="3" fill="#FFD166"/><rect x="45" y="31" width="7" height="12" rx="3" fill="#FFD166"/>',
    chef_hat: '<path d="M19 21q-4-7 3-9 3-6 10-3 7-3 10 3 7 2 3 9v5H19z" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M20 23h24" stroke="#0D1B2E" stroke-width="2"/>',
    graduation_cap: '<path d="M15 18l17-8 17 8-17 8z" fill="#FFD166" stroke="#0D1B2E" stroke-width="2"/><path d="M22 24v5q10 7 20 0v-5M49 19v12" stroke="#0D1B2E" stroke-width="2" fill="none"/>',
    wrench: '<path d="M54 39a7 7 0 0 0-8 9l-8 8 4 4 8-8a7 7 0 0 0 9-8l-4 4-4-4z" fill="#FFD166" stroke="#0D1B2E" stroke-width="2"/>',
    shield: '<path d="M50 38l9 3v7q-1 7-9 11-8-4-9-11v-7z" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M46 48l3 3 5-6" stroke="#14A88A" stroke-width="2" fill="none"/>',
    globe: '<circle cx="50" cy="48" r="9" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M41 48h18M50 39q-9 9 0 18M50 39q9 9 0 18" stroke="#2F7BFF" stroke-width="1.5" fill="none"/>',
    camera: '<rect x="40" y="43" width="19" height="13" rx="2" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><circle cx="50" cy="49" r="4" fill="#5BB0FF" stroke="#0D1B2E" stroke-width="1.5"/><path d="M44 43l2-3h7l2 3" fill="#fff" stroke="#0D1B2E" stroke-width="2"/>',
    music_note: '<path d="M48 43v12a3 3 0 1 1-2-3V41l11-3v13a3 3 0 1 1-2-3V40z" fill="#FFD166" stroke="#0D1B2E" stroke-width="1.5"/>',
    dollar_coin: '<circle cx="50" cy="49" r="9" fill="#FFD166" stroke="#0D1B2E" stroke-width="2"/><path d="M53 45q-6-3-7 1-1 3 4 3 6 1 3 5-3 3-7 0M50 42v14" stroke="#0D1B2E" stroke-width="1.5" fill="none"/>',
    heart: '<path d="M50 56l-8-8q-4-6 2-8 4-1 6 3 2-4 6-3 6 2 2 8z" fill="#F0456A" stroke="#0D1B2E" stroke-width="2"/>',
    book: '<path d="M40 42q5-3 10 1 5-4 10-1v14q-5-3-10 1-5-4-10-1z" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M50 43v14" stroke="#0D1B2E" stroke-width="1.5"/>',
    lightbulb: '<path d="M50 39a7 7 0 0 0-5 12l2 3h6l2-3a7 7 0 0 0-5-12z" fill="#FFE686" stroke="#0D1B2E" stroke-width="2"/><path d="M47 56h6M48 59h4" stroke="#0D1B2E" stroke-width="2"/>',
    rocket: '<path d="M47 53q-2-11 9-16 4 11-6 18z" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><circle cx="53" cy="44" r="2" fill="#2F7BFF"/><path d="M47 53l-4 5 7-3M46 50l-5-1 4-4" fill="#F0456A" stroke="#0D1B2E" stroke-width="1.5"/>',
    leaf: '<path d="M42 55q-1-14 17-16 1 16-17 16z" fill="#B9E978" stroke="#0D1B2E" stroke-width="2"/><path d="M42 55l13-11" stroke="#0D1B2E" stroke-width="1.5"/>',
    gamepad: '<path d="M43 44h14l4 8q1 6-5 4l-4-3h-4l-4 3q-6 2-5-4z" fill="#fff" stroke="#0D1B2E" stroke-width="2"/><path d="M44 49h7M47.5 46v6" stroke="#0D1B2E" stroke-width="1.5"/><circle cx="55" cy="48" r="1" fill="#F0456A"/>',
    megaphone: '<path d="M41 44h6l11-5v15l-11-5h-6z" fill="#FFD166" stroke="#0D1B2E" stroke-width="2"/><path d="M44 49l2 8h4l-2-8M60 43l3-2M60 50l3 2" stroke="#0D1B2E" stroke-width="2" fill="none"/>'
  };
  function pipSVG(spec) {
    const s = normalizeSpec(spec), key = signature(s);
    if (cache.has(key)) return cache.get(key);
    const [light, deep] = palettes[s.palette], gid = 'pip-' + s.palette;
    const visor = s.visor === 'round' ? '<rect x="15" y="23" width="34" height="22" rx="11" fill="#0D1B2E"/>' : '<rect x="15" y="23" width="34" height="22" rx="7" fill="#0D1B2E"/>';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Pip avatar"><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${deep}"/></linearGradient></defs><line x1="32" y1="15" x2="32" y2="8" stroke="${deep}" stroke-width="3" stroke-linecap="round"/>${tipArt[s.antenna]}<rect x="9" y="15" width="46" height="40" rx="17" fill="url(#${gid})"/>${visor}${s.accessory === 'code' ? '' : eyeArt[s.eyes]}${accessoryArt[s.accessory]}</svg>`;
    if (cache.size > 4096) cache.clear();
    cache.set(key, svg); return svg;
  }
  function escapeHTML(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]); }
  function avatarHTML(agent) {
    if (agent?.avatar_style === 'emoji') return `<span class="pip-emoji" aria-hidden="true">${escapeHTML(agent.emoji || '🤖')}</span>`;
    return pipSVG(pipFor(agent)).replace('<svg ', '<svg class="pip-avatar" ');
  }
  const api = Object.freeze({ pipSVG, pipFor, assignPips, avatarHTML, normalizeSpec, palettes, accessories, eyes, antennaTips, visors });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.Pips = api;
})(typeof window !== 'undefined' ? window : null);
