/* Local emoji chooser. Names are search terms; no network or HTML injection. */
(() => {
  'use strict';
  const groups = {
    People: '😀 smile|😃 happy|😄 grin|😁 beam|😆 laugh|😅 sweat|😂 tears|🤣 rolling|😊 blush|🙂 slight|🙃 upside down|😉 wink|😍 love eyes|🥰 hearts|😘 kiss|😎 cool|🤓 nerd|🧐 curious|🤔 thinking|🤗 hug|🤩 star eyes|🥳 party|😴 sleep|🤯 mind blown|👋 wave|🙌 celebrate|👏 clap|👍 thumb up|👎 thumb down|💪 strong|🧠 brain|👩 woman|👨 man|🧑 person|👨‍👩‍👧‍👦 family|👩‍💻 coder|🧑‍🔬 scientist',
    Animals: '🐶 dog|🐱 cat|🐭 mouse|🐹 hamster|🐰 rabbit|🦊 fox|🐻 bear|🐼 panda|🐨 koala|🐯 tiger|🦁 lion|🐮 cow|🐷 pig|🐸 frog|🐵 monkey|🐔 chicken|🐧 penguin|🐦 bird|🦉 owl|🦅 eagle|🐺 wolf|🦄 unicorn|🐝 bee|🦋 butterfly|🐢 turtle|🐙 octopus',
    Objects: '💡 idea|🔍 search|🔎 find|🔧 wrench|🛠️ tools|⚙️ gear|🔑 key|📌 pin|📎 paperclip|✂️ scissors|📝 memo|📚 books|📖 book|💬 speech|🗂️ files|🗃️ archive|📦 package|🎨 art|🎬 movie|🎵 music|📷 camera|🎤 microphone|💻 laptop|📱 phone|⌚ watch|🚀 rocket',
    Work: '👩‍💼 manager|👨‍💼 professional|👩‍🏫 teacher|👨‍⚕️ doctor|🧑‍🍳 chef|🧑‍🎨 artist|🕵️ detective|👷 builder|📊 chart|📈 growth|📉 decline|🧮 calculator|🏢 office|🏗️ construction|🧪 test|🔬 microscope|🧭 compass|🗓️ calendar|⏰ clock|✅ done|📋 checklist|✉️ mail|☎️ call|💰 money|🌐 globe',
    Symbols: '✨ sparkle|⭐ star|🌟 glowing star|💫 dizzy|🔥 fire|❤️ heart|💙 blue heart|💚 green heart|💜 purple heart|🧡 orange heart|💛 yellow heart|⚡ lightning|☀️ sun|🌙 moon|☁️ cloud|🌈 rainbow|🌻 sunflower|🌿 herb|🍀 clover|🎯 target|🏆 trophy|💎 gem|♻️ recycle|🔔 bell|❓ question|❗ exclamation'
  };
  const items = Object.entries(groups).flatMap(([group, value]) => value.split('|').map((entry) => { const [emoji, ...words] = entry.split(' '); return { group, emoji, name: words.join(' ') }; }));
  let target = null, callback = null;
  const $ = (id) => document.getElementById(id);
  function clusters(value) {
    if (typeof Intl.Segmenter === 'function') return [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(value)].map((part) => part.segment);
    const result = [];
    for (const char of Array.from(value)) {
      const last = result.length - 1;
      if (last >= 0 && (/^[\u200d\ufe0e\ufe0f\u20e3]$/.test(char) || /\p{Emoji_Modifier}|\p{Mark}/u.test(char) || result[last].endsWith('\u200d') || (/\p{Regional_Indicator}/u.test(char) && /^\p{Regional_Indicator}$/u.test(result[last])))) result[last] += char;
      else result.push(char);
    }
    return result;
  }
  function valid(value) { const clean = value.trim(); return clusters(clean).length === 1 && new TextEncoder().encode(clean).length <= 64 && (/\p{Extended_Pictographic}|\p{Regional_Indicator}/u.test(clean) || /^[#*0-9]\ufe0f?\u20e3$/.test(clean)); }
  function recent() { try { const value = JSON.parse(localStorage.getItem('agent-hub-recent-emoji') || '[]'); return Array.isArray(value) ? value.slice(0, 12) : []; } catch { return []; } }
  function choose(emoji) {
    if (!valid(emoji)) { $('emojiCustom').setCustomValidity('Choose a single emoji.'); $('emojiCustom').reportValidity(); return; }
    if (target) { target.value = emoji; target.dispatchEvent(new Event('input', { bubbles: true })); }
    if (callback) callback(emoji);
    try { localStorage.setItem('agent-hub-recent-emoji', JSON.stringify([emoji, ...recent().filter((x) => x !== emoji)].slice(0, 12))); } catch { /* private mode */ }
    $('emojiDialog').close();
  }
  function draw() {
    const query = $('emojiSearch').value.toLowerCase().trim(); const grid = $('emojiGrid'); grid.replaceChildren();
    const sections = query ? { Results: items.filter((item) => `${item.name} ${item.group} ${item.emoji}`.toLowerCase().includes(query)) } : { Recent: recent().map((emoji) => ({ emoji, name: 'recent' })), ...Object.fromEntries(Object.keys(groups).map((group) => [group, items.filter((item) => item.group === group)])) };
    Object.entries(sections).forEach(([group, values]) => {
      if (!values.length) return; const heading = document.createElement('h3'); heading.textContent = group; grid.append(heading);
      const row = document.createElement('div'); row.className = 'emoji-row';
      values.forEach(({ emoji, name }) => { const button = document.createElement('button'); button.type = 'button'; button.textContent = emoji; button.title = name; button.setAttribute('aria-label', name); button.addEventListener('click', () => choose(emoji)); row.append(button); }); grid.append(row);
    });
  }
  function open(input, onChoose) { target = input; callback = onChoose || null; $('emojiSearch').value = ''; $('emojiCustom').value = ''; $('emojiCustom').setCustomValidity(''); draw(); $('emojiDialog').showModal(); $('emojiSearch').focus(); }
  window.HubEmoji = { open, valid, items, clusters };
  document.addEventListener('DOMContentLoaded', () => { $('emojiSearch').addEventListener('input', draw); $('emojiCustom').addEventListener('input', () => $('emojiCustom').setCustomValidity('')); $('emojiUseCustom').addEventListener('click', () => choose($('emojiCustom').value)); });
})();
