/* Run with: node tests/ui_smoke.js */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node {
  constructor(tag = 'div') { this.tagName = tag; this.className = ''; this.classList = { add: (name) => { this.className = [...new Set([...this.className.split(' ').filter(Boolean), name])].join(' '); }, remove: (name) => { this.className = this.className.split(' ').filter((part) => part !== name).join(' '); }, contains: (name) => this.className.split(' ').includes(name), toggle: (name, force) => { const on = force === undefined ? !this.classList.contains(name) : force; this.classList[on ? 'add' : 'remove'](name); return on; } }; this.children = []; this.dataset = {}; this.events = {}; this._text = ''; this.hidden = false; this.open = false; this.disabled = false; this.isConnected = true; this.style = { setProperty(name, value) { this[name] = value; }, removeProperty(name) { delete this[name]; } }; this.rect = { left: 20, top: 20, right: 120, bottom: 64, width: 100, height: 44 }; this.offsetHeight = 180; }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(value) { if (this.tagName !== 'template' || !/^<svg class="pip-avatar" [\s\S]*<\/svg>$/.test(value)) throw new Error('Unexpected HTML'); this.content = { firstElementChild: new Node('svg') }; this.content.firstElementChild.className = 'pip-avatar'; this.content.firstElementChild.source = value; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  append(...children) { children.forEach((child) => { if (child?.tagName === '#fragment') this.append(...child.children); else { if (child && typeof child === 'object') child.parent = this; this.children.push(child); } }); }
  insertBefore(child, anchor) { if (child.parent) child.parent.children = child.parent.children.filter((item) => item !== child); const index = anchor ? this.children.indexOf(anchor) : this.children.length; if (index < 0) throw new Error('Anchor is not a child'); child.parent = this; this.children.splice(index, 0, child); }
  prepend(...children) { children.forEach((child) => { child.parent = this; this.children.unshift(child); }); }
  get childNodes() { return this.children; }
  get options() { return this.children.filter((child) => child.tagName === 'option'); }
  getBoundingClientRect() { return this.rect; }
  replaceWith(other) { if (this.parent) { const index = this.parent.children.indexOf(this); this.parent.children[index] = other; other.parent = this.parent; } }
  after(other) { if (this.parent) { const index = this.parent.children.indexOf(this); this.parent.children.splice(index + 1, 0, other); other.parent = this.parent; } }
  remove() { this.isConnected = false; if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this); }
  replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
  addEventListener(name, callback) { this.events[name] = callback; }
  focus() { this.focused = true; }
  dispatchEvent(event) { return this.events[event.type]?.(event); }
  click() { return this.events.click?.({target:this}); }
  setSelectionRange(start, end) { this.selection = [start, end]; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  scrollIntoView(options) { this.scrolledWith = options; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  querySelectorAll(selector) { return this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)]).filter((child) => selector.split(',').some((part) => part.startsWith('.') ? child.className?.split(' ').includes(part.slice(1)) : part === '[data-settings-tab]' ? !!child.dataset.settingsTab : part === '[data-settings-panel]' ? !!child.dataset.settingsPanel : part.startsWith('[name=') ? child.name === part.slice(6, -1) : child.tagName === part)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  findText(text) { return this.textContent.includes(text); }
}
const elements = new Map();
const indexHTML = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const root = new Node('document'), stack = [root], voidTags = new Set(['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']);
for (const token of indexHTML.match(/<!--[^]*?-->|<![^>]*>|<\/?[a-z][^>]*>/gi) || []) {
  if (token.startsWith('<!')) continue;
  if (token.startsWith('</')) { stack.pop(); continue; }
  const match = /^<([a-z][\w-]*)\b/i.exec(token); if (!match) continue;
  const tag = match[1].toLowerCase(), item = new Node(tag);
  const id = /\bid="([^"]+)"/.exec(token)?.[1], classes = /\bclass="([^"]+)"/.exec(token)?.[1];
  if (id) { item.id = id; elements.set(id, item); }
  if (classes) item.className = classes;
  for (const [, name, value] of token.matchAll(/data-settings-(tab|panel)="([^"]+)"/g)) item.dataset[name === 'tab' ? 'settingsTab' : 'settingsPanel'] = value;
  item.hidden = /\shidden(?:\s|>|=)/.test(token);
  stack.at(-1).append(item);
  if (!voidTags.has(tag) && !token.endsWith('/>')) stack.push(item);
}
const body = root.querySelector('body');
assert.ok(body && elements.get('messageList')?.parent?.id === 'messageViewport', 'test DOM comes from the actual index.html message structure');
const document = { body, events: {}, addEventListener(name, callback) { this.events[name] = callback; }, getElementById(id) { if (!elements.has(id)) elements.set(id, new Node()); return elements.get(id); }, createElement: (tag) => new Node(tag), createDocumentFragment: () => new Node('#fragment'), querySelectorAll: (selector) => root.querySelectorAll(selector), querySelector: (selector) => root.querySelector(selector), documentElement: root.querySelector('html') };
const timers = [];
const setTimeoutFake = (callback, ms) => { const timer = { callback, ms, cancelled: false }; timers.push(timer); return timer; };
const clearTimeoutFake = (timer) => { if (timer) timer.cancelled = true; };
let source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
source = source.replace(/  setup\(\);[\s\S]*\}\)\(\);\s*$/, '  window.HubApp = { api, post, refreshState, openChat, showToast, prepareTeam }; globalThis.__test = { openMessageMenu, closeMessagePopover, resizeComposer, data, seconds, chatTime, quotedText, approvalsDrafts, hasUnread, modelSelect, engineLabel, api, messageNode, renderSwarmResults, renderApprovals, submitApprovalsReview, checkApprovalsDecision, showSwarmError, clearSwarmError, renderWorkers, openApprovals, onPaletteKeydown, paletteEntries, sendMessage, askEveryone, connectEvents, renderDeltas, closeDelta, reconcileMessages, openChat, refreshState, loadSetup, showCoach, positionCoach, closeCoach, addReply, renderReply, selectSettingsTab, react, openTeam, renderSwarmWorkers, setWorkerAgent, renderEmpty, renderHeader, renderSend, renderRoutines, agentSettings, plainInline, confirmationText, teamResultCard, updateCard, navButton, renderNav, setSidebarCollapsed, toggleMenu, closeMenus, pipPicker, readPipPicker, proposalCard, guideStarters, editProposal, proposalDecision, windowedRows, navSections, renderDirectory, archiveDirectory, pipRole, quotePreview, withoutSpeakerPrefix, friendlyFolder, shouldWelcome, dismissWelcome, idleCheck, startSession, exportFile, visibleHandoffText, openGettingStartedGuide, settingsTabKeydown, openSettings };\n})();');
source = source.replace('globalThis.__test = {', 'globalThis.__test = { setupComposerInteractions, stopResponse, positionToast, setupSidebarSearch, showLogin, sendFeel, inlineAction, appActionDialog, showCreatedToast, mergeSentMessages, retrySentMessage, markAgentSeen, ');
let eventSource;
class FakeEventSource { constructor() { this.listeners = {}; eventSource = this; } addEventListener(name, callback) { this.listeners[name] = callback; } close() {} }
FakeEventSource.CLOSED = 2;
let nextRequestId = 0;
const context = { document, location: { origin: 'http://localhost' }, localStorage: {}, history: {}, navigator: { onLine: true }, window: { innerWidth: 1440, innerHeight: 900 }, matchMedia: () => ({ matches: false }), requestAnimationFrame: (callback) => callback(), Event, Intl, Date, Number, String, URL, Headers, console, crypto: { randomUUID: () => `request-${++nextRequestId}` }, EventSource: FakeEventSource, setTimeout: setTimeoutFake, clearTimeout: clearTimeoutFake };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'markdown.js'), 'utf8'), context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'pips.js'), 'utf8'), context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'access.js'), 'utf8'), context);
vm.runInNewContext(source, context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'onboarding.js'), 'utf8'), context);
const { data, chatTime, quotedText, approvalsDrafts, hasUnread, modelSelect, renderApprovals, submitApprovalsReview } = context.__test;
const walk = (root) => [root, ...(root.children || []).flatMap(walk)];
const md = context.window.HubMarkdown.render('1. **"status"**: `ready`\n- next\n\n```js\nconst x = 1;\n```\n[good](https://example.com) [bad](javascript:alert(1)) <img onerror=alert(1)>');
assert.ok(walk(md).some((n) => n.tagName === 'strong' && n.textContent === '"status"'), 'markdown bold inside numbered list');
assert.ok(walk(md).some((n) => n.tagName === 'code' && n.textContent === 'ready'), 'inline code');
assert.ok(walk(md).some((n) => n.tagName === 'pre' && n.textContent.includes('const x')), 'fenced code');
assert.ok(walk(md).some((n) => n.tagName === 'button' && n.textContent === 'Copy'), 'code copy button');
assert.ok(walk(md).some((n) => n.tagName === 'a' && n.href === 'https://example.com/' && n.rel === 'noopener noreferrer'), 'safe link opens separately');
assert.equal(walk(md).filter((n) => n.tagName === 'a').length, 1, 'unsafe scheme stays plain text');
assert.ok(md.textContent.includes('<img onerror=alert(1)>'), 'HTML is literal text');
assert.ok(context.window.HubMarkdown.render('Thinking **bold').textContent.includes('**bold'), 'final literal unclosed marker stays readable');
assert.equal(context.window.HubMarkdown.render('Thinking **bold', { streaming: true }).textContent, 'Thinking bold', 'streaming hides unclosed bold marker');
assert.equal(context.window.HubMarkdown.render('Thinking *ital', { streaming: true }).textContent, 'Thinking ital', 'streaming hides unclosed italic marker');
assert.equal(context.window.HubMarkdown.render('Thinking `code', { streaming: true }).textContent, 'Thinking code', 'streaming hides unclosed code marker');
assert.ok(context.window.HubMarkdown.render('`nested `` backticks`').textContent.includes('nested'), 'nested backticks remain safe text');
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'emoji.js'), 'utf8'), { ...context, document: { ...document, addEventListener() {} }, TextEncoder, Event });
assert.ok(context.window.HubEmoji.items.length >= 120, 'emoji picker has curated range');
assert.ok(context.window.HubEmoji.valid('👩‍💻'), 'emoji validation accepts one grapheme');
assert.equal(context.window.HubEmoji.valid('👍👍'), false, 'emoji validation rejects multiple graphemes');
assert.equal(context.window.HubEmoji.valid('🇺🇸'), true, 'emoji validation accepts flag');
assert.equal(context.window.HubEmoji.valid('1️⃣'), true, 'emoji validation accepts keycap');
assert.equal(context.window.HubEmoji.valid('👨‍👩‍👧‍👦'), true, 'emoji validation accepts family grapheme');
const segmenter = context.Intl.Segmenter; context.Intl.Segmenter = undefined;
assert.equal(context.window.HubEmoji.clusters('👩‍💻').length, 1, 'fallback keeps ZWJ emoji together');
assert.equal(context.window.HubEmoji.clusters('🇺🇸').length, 1, 'fallback keeps flag together');
context.Intl.Segmenter = segmenter;
assert.equal(chatTime(0), '', 'zero activity has no date');
assert.equal(chatTime('0'), '', 'serialized zero activity has no date');
assert.equal(context.__test.seconds(0),0,'zero activity stays zero before directory formatting');
assert.equal(context.__test.seconds('0'),0,'serialized zero activity stays zero');
data.messages = [{ id: 7, cards: [{ title: 'Approve budget' }] }];
assert.equal(quotedText({ reply_to: 7 }), 'Approve budget', 'card decision quotes card title');
data.approvals = { workspace: { tabs: { timely: [{ id: 'draft-1', text: 'A draft' }], funny: [] } } };
assert.equal(approvalsDrafts()[0].category, 'timely', 'Approvals tabs are parsed');
data.product = { unread: {} };
assert.equal(hasUnread({ id: 'agent:1', last_message: { text: 'hello' } }), false, 'server zero unread overrides local fallback');
data.product.unread['agent:1'] = 2;
assert.equal(hasUnread({ id: 'agent:1' }), true, 'server unread count appears');
// PASS15 B4-1: accessible tabs remain selected/focusable after keyboard navigation.
const settingTabs = document.querySelectorAll('[data-settings-tab]');
context.__test.selectSettingsTab('general');
assert.equal(settingTabs[0].tabIndex, 0);
let prevented = false;
context.__test.settingsTabKeydown({key:'End', currentTarget:settingTabs[0], preventDefault(){prevented=true;}});
assert.ok(prevented && settingTabs[3].focused);
assert.equal(settingTabs[3]['aria-selected'], 'true');
assert.equal(settingTabs[0].tabIndex, -1);
assert.equal(document.getElementById('settings-panel-help').hidden, false);
context.__test.settingsTabKeydown({key:'ArrowRight', currentTarget:settingTabs[3], preventDefault(){}});
assert.equal(settingTabs[0]['aria-selected'], 'true');
// B4-4: Retry has a distinct icon while Reply still quotes the same message.
const actionMessage = context.__test.messageNode({id:901,role:'assistant',text:'Answer'});
context.__test.openMessageMenu({id:901,role:'assistant',text:'Answer'}, actionMessage);
const retryAction = walk(body).find(n=>n['aria-label']==='Retry answer');
assert.equal(walk(retryAction).find(n=>n.tagName==='use').href, '#i-retry');
assert.equal(walk(walk(actionMessage).find(n=>n['aria-label']==='Reply')).find(n=>n.tagName==='use').href, '#i-reply');
context.__test.closeMessagePopover();
// B4-5: one empty state, with no duplicate empty running sections.
data.jobs=[]; data.workers={running:[],done:[]}; context.__test.renderWorkers();
assert.equal(document.getElementById('workersBody').querySelectorAll('.worker-section').length,0);
assert.ok(document.getElementById('workersBody').findText('No background jobs yet'));
data.workers={running:[],done:[{id:'finished',rc:0,message:'Finished answer'}]}; context.__test.renderWorkers();
assert.equal(document.getElementById('workersBody').querySelectorAll('.worker-section').length,1);
assert.ok(document.getElementById('workersBody').findText('Finished answer'));
// B4-6: a finished team cannot hide a helper review flag behind Done.
const reviewCard=context.__test.teamResultCard({status:'done',workers:[{role:'Critic',status:'issues',issue:'Missing evidence'}]});
assert.equal(reviewCard.querySelector('.team-status').textContent,'Needs review');
assert.ok(reviewCard.findText('Missing evidence'));
assert.equal(context.__test.teamResultCard({status:'done',workers:[{status:'pass'}]}).querySelector('.team-status').textContent,'Done');
const select = { value: '', replaceChildren(...options) { this.options = options; } };
modelSelect(select, 'codex', 'gpt-6-luna');
assert.equal(select.value, 'gpt-6-luna');
assert.equal(select.options[0].textContent, 'gpt-6-luna');
assert.match(select.options[0].title, /Fast everyday work/);
data.setup = { engines: { claude: { available: true, authenticated: 'ready' }, codex: { available: false } } };
assert.equal(context.__test.engineLabel('claude'), 'Claude Code — signed in');
assert.match(context.__test.engineLabel('codex'), /Not installed.*Help/);
assert.ok(context.__test.messageNode({ id: 50, role: 'user', text: 'hello', acknowledged: true }).findText('Seen'));
data.messages = [{ id: 7, role: 'user', text: 'Please plan today' }];
assert.equal(context.__test.messageNode({ id: 51, role: 'assistant', reply_to: 7, text: 'Here is a plan' }).findText('Please plan today'), false, 'assistant reply does not echo the user message');
data.messages = [{ id: 11, role: 'assistant', agent_id: 'first', text: 'First' }, { id: 12, role: 'assistant', agent_id: 'first', text: 'Second' }];
context.__test.addReply(11); context.__test.addReply(12);
assert.equal(data.replyTo.length, 2, 'two reply targets collected');
assert.equal(document.getElementById('replyPreview').children.length, 2, 'two reply chips shown');
const quoteNode = context.__test.messageNode({ id: 52, role: 'user', reply_to: [11, 12], text: 'Both' });
assert.equal(walk(quoteNode).filter((n) => n.className === 'quoted').length, 2, 'two quote lines rendered');
assert.equal(context.__test.plainInline('**Approve** my_file_name_here'), 'Approve my_file_name_here', 'quotes and confirmation strip markdown without mangling identifiers');
assert.equal(context.__test.plainInline('Apple\n\nBanana\n\n```py\nprint("hello")\n```'), 'Apple Banana print("hello")', 'quotes use Markdown source with spaces and code, excluding Copy buttons');
assert.equal(context.__test.confirmationText('approve', '**Approve** publishing title'), 'Approve publishing title?', 'approval confirmation does not duplicate verb or show markdown');
data.agents = [{id:'cy',name:'Cy',pip_style:{palette:'blue'}}];
const pipMessage = context.__test.messageNode({id:53,role:'assistant',agent_id:'cy',text:'Cy: Teal is the answer.'});
assert.equal(walk(pipMessage).filter((n)=>n.tagName==='svg' && n.className==='pip-avatar').length,1,'Pip avatars render as inline SVG nodes');
assert.equal(walk(pipMessage).filter((n)=>n.tagName==='img').length,0,'Pip avatars never use CSP-blocked data images');
assert.equal(pipMessage.findText('Cy: Teal'),false,'group replies do not repeat their speaker prefix');
data.messages=[{id:53,role:'assistant',agent_id:'cy',text:'Cy: Teal is the answer.'}];
const groupQuote=context.__test.messageNode({id:54,role:'user',reply_to:53,text:'Why?'});
assert.equal(groupQuote.findText('Cy: Cy:'),false,'quote chips do not repeat a speaker prefix');
data.chatId='group:test';data.chats=[{id:'group:test',type:'group',name:'Test',agents:['cy']}];
context.__test.renderHeader();
assert.equal(document.getElementById('modelSelector').textContent,'Best fit','group composer label is stable after replies');
data.chatId=null;data.chats=[];
assert.ok(walk(context.__test.messageNode({ id: 53, role: 'assistant', text: '**Done**', best_fit: true, best_fit_agent_name: 'First' })).some((n) => n.className === 'best-fit-note' && n.findText('First answered — best fit')), 'best-fit note');
const original = { id: 20, role: 'user', text: 'Original question', reply_to: [11] };
data.messages = [original, { id: 21, role: 'user', text: 'Later question' }];
const causalAnswer = context.__test.messageNode({ id: 22, role: 'assistant', text: 'Answer', reply_to: [20], best_fit: true, best_fit_agent_name: 'First' });
const askAll = walk(causalAnswer).find((n) => n.tagName === 'button' && n.textContent === 'Ask everyone');
document.getElementById('composer').requestSubmit = () => { document.getElementById('composer').submitted = true; };
askAll.events.click();
assert.equal(document.getElementById('messageInput').value, '@all Original question', 'Ask everyone reuses causal question');
assert.equal(data.replyTo[0], 11, 'Ask everyone preserves quote context');
assert.equal(document.getElementById('composer').submitted, true, 'Ask everyone sends reask');
data.chatId = 'group:tie'; data.chats = [{ id: 'group:tie', name: 'Team', type: 'group', agents: ['first','second'] }]; data.agents = [{ id:'first', name:'First' }, { id:'second', name:'Second' }];
data.messages = [{ id: 30, role: 'user', text: 'Write a tagline', reply_to: [11] }];
const tied = context.__test.messageNode({ id: 31, role: 'assistant', agent_id: 'first', text: 'Option', reply_to: [30], routing_kind: 'tie' });
const picker = walk(tied).find((n) => n.className === 'tie-agent-picker');
assert.ok(picker && picker.children.some((n) => n.value === 'second'), 'tie offers another group member');
picker.value = 'second'; picker.events.change();
assert.equal(document.getElementById('messageInput').value, '@second Write a tagline', 'tie picker resends causal prompt to selected agent');
assert.equal(data.replyTo[0], 11, 'tie picker preserves original quote');
const briefAll = context.__test.messageNode({ id: 32, role: 'assistant', agent_id: 'second', text: 'Short answer.', independent: true });
assert.equal(walk(briefAll).filter((n) => n.className === 'group-show-more').length, 0, 'short @all answer has no Show more');
data.chatId = null; data.chats = [];
const reactionNode = context.__test.messageNode({ id: 54, role: 'assistant', text: 'Ready', reactions: ['👍'] });
assert.ok(walk(reactionNode).some((n) => n.classList.contains('reaction-chip') && n.textContent === '👍'), 'saved reaction appears');
assert.equal(walk(reactionNode).filter((n) => n.className === 'reaction-button').length, 0, 'picker is floating, not part of each message');
const swipe = context.__test.messageNode({ id: 55, role: 'assistant', text: 'Swipe me' });
const pointer = (x, y, id = 1) => ({ pointerType: 'touch', clientX: x, clientY: y, pointerId: id, target: { closest: () => null } });
const replyCount = data.replyTo.length;
swipe.events.pointerdown(pointer(20, 20)); swipe.events.pointermove(pointer(80, 22));
assert.ok(swipe.classList.contains('swipe-reply'), 'horizontal pointer move reveals reply cue');
swipe.events.pointerup(pointer(80, 22));
assert.equal(data.replyTo.length, replyCount + 1, '56px horizontal swipe adds reply');
assert.equal(data.replyTo.at(-1), 55);
const afterSwipe = data.replyTo.length;
swipe.events.pointerdown(pointer(20, 20)); swipe.events.pointermove(pointer(25, 75)); swipe.events.pointerup(pointer(90, 75));
assert.equal(data.replyTo.length, afterSwipe, 'vertical scroll cancels horizontal reply');
swipe.events.pointerdown(pointer(20, 20)); swipe.events.pointermove(pointer(90, 22)); swipe.events.pointercancel(pointer(90, 22)); swipe.events.pointerup(pointer(90, 22));
assert.equal(data.replyTo.length, afterSwipe, 'pointercancel cannot add reply');
assert.ok(walk(context.__test.messageNode({ id: 56, role: 'assistant', text: 'Reply', model: 'haiku' })).some((n) => n.className === 'reply-model' && n.textContent === 'haiku'), 'reply shows model');
assert.equal(walk(context.__test.messageNode({ id: 57, role: 'system', text: 'Handoff', reply_to: 11 })).filter((n) => n.className === 'quoted').length, 0, 'handoff does not duplicate quote');
assert.ok(walk(context.__test.messageNode({ id: 58, role: 'system', text: '**Approved**' })).some((n) => n.tagName === 'strong' && n.textContent === 'Approved'), 'system message renders markdown');
data.routines = { routines: [{ id: 'r1', name: 'Morning briefing', agent_id: 'first', trigger: 'daily', time: '08:00', error: 'Hub was off', last_run: 1234567890 }], external: [] };
context.__test.renderRoutines();
assert.ok(walk(document.getElementById('routinesList')).some((n) => n.className === 'schedule-error-dot'), 'failed schedule has red dot');
assert.ok(document.getElementById('routinesList').findText('Hub was off'), 'failed schedule explains error');
const limitNode = context.__test.messageNode({ id: 59, role: 'system', text: 'Claude usage limit reached', usage_limit: { engine: 'claude', job_id: 5, alternate_engine: 'codex' } });
assert.ok(limitNode.findText('Retry') && limitNode.findText('Try with Codex'), 'usage card offers retry and alternate engine');
document.getElementById('messageList').replaceChildren(limitNode);
data.messages = [{ id: 59, role: 'system', text: 'Retried successfully' }];
context.__test.reconcileMessages();
assert.ok(!document.getElementById('messageList').findText('Retry'), 'retry controls disappear when usage hold clears');
const settingsBody = new Node();
context.__test.agentSettings(settingsBody, { id: 'first', name: 'Ava', title: 'Writer', emoji: '✍️', model: 'haiku', engine: 'claude', instructions: 'Write clearly', workdir: '/tmp/project' });
assert.ok(settingsBody.findText('Instructions') && settingsBody.findText('Private Pip') && settingsBody.findText('Can use Pip browser') && settingsBody.findText('Draft only'), 'agent settings expose instructions, access modes and the Pip browser');
const modeForm = settingsBody.querySelector('form');
const modePrivate = modeForm.querySelector('[name=private_pip]'), modeDraft = modeForm.querySelector('[name=draft_only]'), modeBrowser = modeForm.querySelector('[name=chrome]');
modeBrowser.checked = true; modePrivate.checked = true; modePrivate.events.change();
assert.equal(modeBrowser.disabled, true, 'Private disables Pip browser immediately');
assert.equal(modeBrowser.checked, false, 'Private clears an enabled Pip browser');
modePrivate.checked = false; modePrivate.events.change(); modeBrowser.checked = true; modeDraft.checked = true; modeDraft.events.change();
assert.equal(modeBrowser.disabled, true, 'Draft only disables Pip browser immediately');
assert.equal(modeBrowser.checked, false, 'Draft only clears an enabled Pip browser');
modeDraft.checked = false; modeDraft.events.change();
assert.equal(modeBrowser.disabled, false, 'full access restores the Pip browser option');
const externalSettings = new Node();
context.__test.agentSettings(externalSettings, { id: 'external', name: 'Outside', external: true, role: 'Read only' });
assert.ok(externalSettings.findText('read only') && externalSettings.querySelector('[name=instructions]').disabled, 'imported source settings are read only');
assert.ok(!externalSettings.querySelector('[name=private_pip]').disabled && !externalSettings.querySelector('[name=draft_only]').disabled, 'imported Pip access can be changed');
const requestCard = { kind: 'approval_request', index: 0, title: 'Send DM', text: '<script>exact text</script>', actions: ['Approve', "Don't"] };
const requestMessage = { id: 97, chat_id: 'agent:first', role: 'assistant', agent_id: 'first', text: 'Please review.', cards: [requestCard] };
const requestNode = context.__test.messageNode(requestMessage);
assert.equal(requestNode.querySelector('.message-body').textContent, 'Please review.', 'backend-normalized approval message displays its remaining text');
assert.equal(requestNode.querySelector('.approval-request-details').textContent, '<script>exact text</script>', 'exact details are literal text');
assert.deepEqual(requestNode.querySelector('.approval-request-actions').querySelectorAll('button').map((item) => item.textContent), ['Approve', "Don't"]);
const quotedFence = '> ```agent-hub\n> {"action":"approval_request","summary":"quoted","details":"keep me"}\n> ```';
const quotedWithCard = context.__test.messageNode({ ...requestMessage, id: 99, text: quotedFence });
assert.ok(quotedWithCard.findText('agent-hub') && quotedWithCard.findText('keep me'), 'a quoted fence stays visible beside a separate stored card');
const malformedRequest = context.__test.messageNode({ id: 98, role: 'assistant', agent_id: 'first', text: '```agent-hub\nnot json\n```' });
assert.ok(malformedRequest.findText('not json'), 'malformed fence remains ordinary safe message text');
data.swarms = [{ id: 'sample', goal: 'Octopus facts', shape: 'race', workers: [{ number: 1, role: 'Helper 1', status: 'pass', terminal: true, answer: 'An octopus has three hearts.', evidence: 'Technical evidence', report: 'PASS: verified' }] }];
context.__test.renderSwarmResults();
const teamCard = document.getElementById('swarmResults').children[0].children.find((child) => child.className === 'list-card team-answer');
assert.ok(teamCard, 'team answer card exists');
assert.equal(teamCard.children[1].textContent, 'An octopus has three hearts.', 'plain answer appears before technical details');
assert.equal(teamCard.children[2].tagName, 'details', 'technical details are collapsed by default');
context.__test.showSwarmError('Turn on separate file changes.');
assert.equal(document.getElementById('swarmError').hidden, false, 'team error is visible');
assert.equal(document.getElementById('toast').textContent, 'Turn on separate file changes.', 'team error also appears in toast');
assert.equal(document.getElementById('swarmError').scrolledWith.block, 'start', 'team error scrolls into view');
context.__test.clearSwarmError();
assert.equal(document.getElementById('swarmError').hidden, true, 'corrected team input clears stale error');
assert.equal(document.getElementById('swarmError').textContent, '');
data.jobs = [];
data.workers = { running: [], done: [] };
context.__test.renderWorkers();
assert.ok(document.getElementById('workersBody').findText('Send a Pip a task'), 'empty background jobs explains how to use it');
assert.equal(document.getElementById('workersButton').hidden, true, 'idle jobs pill is hidden');
data.jobs = [{ id: 41, status: 'held_limit', engine: 'claude', created: Date.now()/1000, task: 'Saved prompt' }];
data.setup = { engines: { codex: { available: true } } };
context.__test.renderWorkers();
assert.equal(document.getElementById('workersButton').hidden, false, 'held usage job keeps Jobs visible');
assert.ok(document.getElementById('workersBody').findText('Retry') && document.getElementById('workersBody').findText('Try with Codex'), 'held job exposes both recovery actions');
data.jobs = [];
data.settings = {};
document.getElementById('paletteDialog').open = true;
document.getElementById('paletteInput').value = 'team';
let escapePrevented = false;
context.__test.onPaletteKeydown({ key: 'Escape', preventDefault() { escapePrevented = true; } });
assert.equal(escapePrevented, true, 'palette Escape overrides search-field clear');
assert.equal(document.getElementById('paletteDialog').open, false, 'palette closes on first Escape with search text');
assert.equal(document.getElementById('paletteInput').value, 'team', 'Escape does not just clear the query');
assert.ok(!context.__test.paletteEntries().some((item) => item.label === 'Approvals'), 'Approvals hidden from search until the connector is connected');
data.settings = { approvals_url: 'http://localhost:4100' };
assert.ok(context.__test.paletteEntries().some((item) => item.label === 'Approvals'), 'Approvals searchable once the connector is connected');
data.settings = {};
assert.ok(context.__test.paletteEntries().some((item) => item.label === 'Background jobs'), 'Background jobs stays searchable when idle');

for (const [width, height] of [[390, 844], [1440, 900]]) {
  context.window.innerWidth = width; context.window.innerHeight = height;
  const savedChat = data.chatId; data.chatId = 'group:tour';
  for (const [step, targetId] of ['newChatButton','newChatButton','attachButton','composer'].entries()) {
  const target = document.getElementById(targetId);
  target.rect = step === 3 ? {left:20,top:height-120,right:width-20,bottom:height-10,width:width-40,height:110} : {left:20+step*110,top:105,right:125+step*110,bottom:149,width:105,height:44};
  context.__test.showCoach(step);
  const coach = document.getElementById('coachDialog');
  assert.equal(coach.hidden, false, `coach shown for step ${step}`);
  const left = Number.parseFloat(coach.style.left), top = Number.parseFloat(coach.style.top);
  assert.ok(left >= 0 && top >= 0 && left + Number.parseFloat(coach.style.width) <= width && top + coach.offsetHeight <= height, `tour fits ${width}x${height}`);
  assert.ok(left >= target.rect.right || left + Number.parseFloat(coach.style.width) <= target.rect.left || top >= target.rect.bottom || top + coach.offsetHeight <= target.rect.top, `coach does not cover target ${width}x${height}`);
  context.__test.closeCoach();
  }
  data.chatId = savedChat;
}
const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'style.css'), 'utf8');
assert.match(css, /sidebar-footer\.compact-footer\{[^}]*display:flex/, 'footer keeps settings and pills on one row');
assert.match(css, /\.message\{[^}]*touch-action:pan-y/, 'vertical touch scroll preserved on message bubbles');
assert.match(css, /\.quote-stack \.quoted\{[^}]*width:100%/, 'quote width constrained to its bubble');
assert.match(css, /\.reaction-button\{[^}]*min-height:44px/, 'reactions have touch targets');
require('./markdown_smoke.js');
(async () => {
  // This DOM harness has no layout engine. CSS size contracts are checked in test_ui.py.
  const payloads = [];
  context.location.hash = ''; context.location.pathname = '/';
  context.fetch = async (url, options = {}) => { if (options.body) payloads.push({ url, method: options.method, body: JSON.parse(options.body) }); return { ok: true, status: 200, json: async () => url === '/api/state' ? { agents: [], chats: [], statuses: [] } : {} }; };
  const agentForm = settingsBody.querySelector('form');
  agentForm.querySelector('[name=name]').value = 'Ava Renamed';
  agentForm.querySelector('[name=instructions]').value = 'Write precise copy.';
  agentForm.querySelector('[name=private_pip]').checked = true;
  agentForm.querySelector('[name=draft_only]').checked = true;
  agentForm.querySelector('[name=private_pip]').events.change();
  assert.equal(agentForm.querySelector('[name=chrome]').disabled, true, 'Private Pip disables Pip browser');
  await agentForm.events.submit({ preventDefault() {} });
  const savedAgent = payloads.find((request) => request.url === '/api/agents/update')?.body;
  assert.equal(savedAgent.name, 'Ava Renamed');
  assert.equal(savedAgent.instructions, 'Write precise copy.');
  assert.equal(savedAgent.chrome, false, 'managed settings persist the disabled browser flag');
  assert.equal(savedAgent.use_global_rules, undefined, 'legacy global-rules flag is not submitted');
  assert.equal(savedAgent.private_pip, true);
  assert.equal(savedAgent.draft_only, true);
  assert.equal(payloads.some((request) => request.url === '/api/agents/first'), false, 'managed settings save atomically in one request');
  assert.equal(savedAgent.workdir, '/tmp/project');
  await requestNode.querySelector('.approval-request-actions').querySelectorAll('button')[0].click();
  const cardDecision = payloads.find((request) => request.url === '/api/card')?.body;
  assert.equal(cardDecision.message_id, 97);
  assert.equal(cardDecision.index, 0);
  assert.equal(cardDecision.action, 'Approve');
  const linkedAccess = externalSettings.querySelector('.pip-access-form');
  linkedAccess.querySelector('[name=private_pip]').checked = true;
  linkedAccess.querySelector('[name=draft_only]').checked = true;
  await linkedAccess.events.submit({preventDefault(){}});
  const linkedPatch = payloads.find((request) => request.url === '/api/agents/external')?.body;
  assert.deepEqual(linkedPatch, {private_pip:true,draft_only:true}, 'linked access uses PATCH fields');
  assert.equal(payloads.find((request) => request.url === '/api/agents/external').method, 'PATCH');
  context.fetch = async () => ({ok:false,status:400,json:async()=>({error:'Working folder must be inside your home folder.'})});
  await agentForm.events.submit({preventDefault(){}});
  assert.ok(agentForm.findText('Working folder must be inside your home folder.'), 'save error appears in agent form');
  assert.equal(agentForm.querySelector('[name=workdir]')['aria-invalid'],'true','invalid workdir is marked');
  assert.equal(agentForm.querySelector('.form-error').scrolledWith.block,'nearest','save error scrolls beside button');
  assert.ok(!externalSettings.querySelector('form').events.submit, 'imported source settings have no save action');
  assert.ok(externalSettings.querySelector('.pip-access-form').events.submit, 'imported Pip access can be saved');
  const linkedSettings=new Node();context.__test.agentSettings(linkedSettings,{id:'linked',name:'Linked',linked:true,instructions:'Source instructions'});
  assert.ok(linkedSettings.findText('Linked Pip') && linkedSettings.querySelector('[name=instructions]').value==='Source instructions','linked instructions are shown read only');
  assert.ok(!linkedSettings.querySelector('form').events.submit,'linked source settings cannot be saved');
  assert.ok(linkedSettings.querySelector('.pip-access-form').events.submit,'linked Pip access can be saved');
  data.authenticated = true; data.messages = []; data.chatId = 'agent:first'; data.statuses = [];
  data.agents = [{id:'first', name:'Ava', engine:'claude', model:'haiku', private_pip:true, draft_only:true}];
  data.chats = [{id:'agent:first', name:'Ava', type:'direct', agents:['first']}];
  context.__test.renderHeader();
  assert.deepEqual(document.getElementById('pipAccessChips').children.map((item) => item.textContent), ['Private', 'Draft only']);
  data.agents[0].private_pip = false; data.agents[0].draft_only = false; context.__test.renderHeader();
  assert.equal(document.getElementById('pipAccessChips').textContent, 'Full access');
  data.chatId = 'group:design';
  data.agents = [{id:'first', name:'Ava', engine:'claude', model:'haiku', title:'Research'}, {id:'second', name:'Ben', engine:'codex', model:'gpt-6-luna', title:'Build'}];
  data.chats = [{id:'group:design', name:'Design', type:'group', agents:['first','second']}];
  data.settings = {};
  document.getElementById('messageInput').value = 'Plan the launch';
  await context.__test.openTeam();
  assert.equal(document.getElementById('swarmGoal').value, 'Plan the launch', 'team dialog uses composer draft');
  assert.equal(data.teamChatId, 'group:design', 'team task retains originating group');
  const selectedWorkers = document.getElementById('swarmWorkers').children;
  assert.deepEqual(Array.from(selectedWorkers, (row) => row.dataset.sourceAgentId), ['first','second'], 'group agents pre-selected');
  assert.equal(selectedWorkers[0].querySelector('select').value, 'claude');
  assert.equal(selectedWorkers[1].querySelectorAll('select')[1].value, 'gpt-6-luna');
  data.chatId = 'agent:first'; data.chats.push({id:'agent:first',type:'direct',agents:['first']});
  await context.__test.openTeam();
  assert.equal(document.getElementById('swarmWorkers').children.length, 1, 'direct agent is pre-selected');
  document.getElementById('swarmCount').value = '2'; context.__test.renderSwarmWorkers();
  const helper = document.getElementById('swarmWorkers').children[1];
  context.__test.setWorkerAgent(helper, data.agents[1]);
  assert.equal(helper.dataset.sourceAgentId, 'second', 'direct chat can pull another helper');
  const taskCard = {index:0, kind:'team_task', swarm_id:'run-1', goal:'Launch', status:'working', summary:'One helper finished', workers:[{role:'Ava',status:'done',answer:'Research findings'}]};
  const runningTaskMessage=context.__test.messageNode({id:200,role:'system',cards:[taskCard]});
  assert.ok(runningTaskMessage.classList.contains('team-task-message'),'team result messages use their own full-width layout');
  assert.match(css,/\.message\.system\.team-task-message\{justify-content:flex-start\}/,'team result aligns with the chat column');
  assert.match(css,/\.message\.system\.team-task-message \.message-content\{width:min\(100%,768px\);max-width:100%\}/,'system message width cannot shrink team card');
  const taskMessage = context.__test.messageNode({id:200,role:'system',cards:[taskCard]});
  const resultCard = walk(taskMessage).find((node) => node.classList.contains('team-result-card'));
  assert.ok(resultCard, 'team task is a structured chat card');
  assert.equal(resultCard.children[1].textContent, 'One helper finished', 'summary precedes agent details');
  assert.ok(resultCard.children.some((node) => node.tagName === 'details' && !node.open), 'agent answers are collapsed');
  assert.deepEqual(Array.from(resultCard.querySelectorAll('button'), (button) => button.textContent), ['Compare','Open results'], 'scratch results never offer Merge');
  assert.ok(context.__test.teamResultCard({...taskCard,workers:[{role:'Ava',status:'issues',answer:'Answer: Missing data',issue:'Could not verify source',has_changes:true}]}).findText('Could not verify source'), 'issue reason is visible');
  assert.ok(context.__test.teamResultCard({...taskCard,workers:[{role:'Ava',status:'pass',has_changes:true}]}).findText('Merge'), 'changed worktree may offer Merge');
  context.__test.updateCard(resultCard, {...taskCard,summary:'Finished'}, {});
  assert.ok(taskMessage.findText('Finished'), 'persistent result card refreshes in place');
  const legacy = {id:'group:swarm-old', name:'Old run',type:'group',agents:[]}; data.chats.push(legacy);
  context.__test.renderNav();
  assert.ok(document.getElementById('groupList').findText('Old run'), 'legacy team chat remains a group');
  assert.ok(document.getElementById('groupList').findText('Team task'), 'legacy group carries badge');
  context.__test.renderEmpty();
  assert.ok(document.getElementById('conversation').classList.contains('is-empty'), 'fresh composer is centered');
  assert.equal(document.getElementById('composer').hidden, false);
  data.messages = [{id:201,role:'assistant',agent_id:'first',text:'First'}, {id:202,role:'assistant',agent_id:'first',text:'Second'}];
  context.__test.reconcileMessages();
  assert.equal(document.getElementById('conversation').classList.contains('is-empty'), false, 'first message docks composer');
  assert.ok(document.getElementById('messageList').children.find((node) => node.dataset.messageId === '202').classList.contains('continued-run'), 'same-agent run hides repeated heading');
  data.statuses = [{id:99,chat_id:'agent:first',status:'working'}]; context.__test.renderSend();
  assert.equal(document.getElementById('sendButton')['aria-label'], 'Send message', 'send always sends');
  assert.equal(document.getElementById('stopButton').hidden, false, 'active response has a separate Stop button');
  const stopCalls = [];
  data.statuses.push({id:100,chat_id:'group:elsewhere',agent_id:'first',status:'working'});
  document.getElementById('messageInput').value = 'Keep my draft';
  context.fetch = async (url, options = {}) => {
    if (url === '/api/jobs/stop') stopCalls.push(JSON.parse(options.body));
    const result = url === '/api/state' ? {agents:data.agents,chats:data.chats,statuses:[]} : url === '/api/product' ? {getting_started:{completed:true}} : {};
    return {status:200,ok:true,json:async () => result};
  };
  await context.__test.stopResponse();
  assert.deepEqual(Array.from(stopCalls, (call) => call.job_id), [99], 'Stop only cancels the current chat');
  assert.equal(document.getElementById('messageInput').value, 'Keep my draft', 'Stop preserves the draft');
  data.statuses = []; context.__test.renderSend();
  assert.equal(document.getElementById('sendButton')['aria-label'], 'Send message');
  context.__test.setSidebarCollapsed(true);
  assert.ok(document.getElementById('app').classList.contains('sidebar-collapsed'));
  context.__test.setSidebarCollapsed(false);
  data.settings = {}; data.chatId = null; data.messages = [];
  await context.__test.openApprovals();
  assert.ok(document.getElementById('approvalsBody').findText('Connect an approvals workspace in Settings'), 'unconfigured Approvals explains setup');
  assert.ok(document.getElementById('approvalsBody').querySelectorAll('button').some((button) => button.textContent === 'Open settings'), 'unconfigured Approvals links to settings');
  context.fetch = async () => ({ status: 401, ok: false, json: async () => ({ error: 'Paste the correct token from Terminal.' }) });
  await assert.rejects(context.__test.api('/api/login', { method: 'POST' }), /Paste the correct token/);
  const calls = [];
  const results = { 'draft-1': ['pending', 'scheduled'], 'draft-2': ['pending', 'pending', 'pending'], 'draft-3': ['pending'], 'draft-4': ['scheduled'] };
  context.fetch = async (url, options = {}) => {
    const request = options.body ? JSON.parse(options.body) : null;
    calls.push({ url, method: options.method || 'GET', body: request });
    let body;
    if (url === '/api/approvals/review') {
      if (request.id === 'draft-3') throw new Error('Transport timeout');
      body = { ok: true };
    }
    else {
      const id = new URL(url, 'http://localhost').searchParams.get('id');
      const status = results[id].shift() || 'pending';
      body = { id, status, decision: { reason: 'Scheduling gate', result: status } };
    }
    return { ok: true, status: 200, json: async () => body };
  };
  data.authenticated = true;
  document.getElementById('approvalsDialog').open = true;
  const first = { id: 'draft-1', category: 'timely', text: 'A draft', hold_reasons: ['Missing source'], holds: [{ reason: 'Needs review' }], reason: 'Waiting for approval' };
  data.approvals = { workspace: { tabs: { timely: [first] } } };
  renderApprovals();
  assert.ok(document.getElementById('approvalsBody').findText('Missing source'), 'draft hold reasons render');
  assert.ok(document.getElementById('approvalsBody').findText('Needs review'), 'draft holds render');
  assert.ok(document.getElementById('approvalsBody').findText('Waiting for approval'), 'draft reason renders');
  await submitApprovalsReview(first, 'approve', '', '');
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1, 'approval POST happens once');
  renderApprovals();
  assert.ok(document.getElementById('approvalsBody').querySelectorAll('button').filter((button) => button.textContent === 'Approve for schedule').every((button) => button.disabled), 'reviewed draft stays disabled after redraw');
  await submitApprovalsReview(first, 'approve', '', '');
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1, 'redraw cannot repeat approval');
  assert.equal(calls.filter((call) => call.method === 'GET').length, 1, 'first decision GET happens after approval');
  assert.equal(data.approvalsReviews['draft-1'].phase, 'pending');
  assert.ok(document.getElementById('approvalsBody').findText('Review saved; waiting for scheduling result.'), 'pending does not promise publication');
  await timers.find((timer) => timer.ms === 2000 && !timer.cancelled).callback();
  assert.equal(data.approvalsReviews['draft-1'].phase, 'scheduled');
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1, 'poll never re-POSTs approval');
  assert.ok(document.getElementById('approvalsBody').findText('Decision reason: Scheduling gate'), 'decision reason renders');
  assert.ok(document.getElementById('approvalsBody').findText('Scheduled by the connected service.'), 'explicit scheduled result appears');

  const second = { id: 'draft-2', category: 'timely', text: 'Other draft' };
  data.approvals.workspace.tabs.timely.push(second);
  await submitApprovalsReview(second, 'approve', '', '');
  data.approvalsReviews['draft-2'].deadline = Date.now() - 1;
  await timers.filter((timer) => timer.ms === 2000 && !timer.cancelled).at(-1).callback();
  assert.equal(data.approvalsReviews['draft-2'].phase, 'pending_timeout', 'bounded poll ends with explicit pending state');
  const check = document.getElementById('approvalsBody').querySelectorAll('button').find((button) => button.textContent === 'Check status');
  assert.ok(check, 'manual GET status control remains');
  await check.events.click();
  assert.equal(calls.filter((call) => call.method === 'POST').length, 2, 'manual check never re-POSTs approval');
  assert.equal(calls.filter((call) => call.method === 'GET').length, 5, 'poll and manual check use GET');
  assert.ok(document.getElementById('approvalsBody').findText('scheduling result still pending'), 'timeout says pending');

  const uncertain = { id: 'draft-3', category: 'timely', text: 'Uncertain draft' };
  data.approvals.workspace.tabs.timely.push(uncertain);
  await submitApprovalsReview(uncertain, 'approve', '', '');
  assert.equal(data.approvalsReviews['draft-3'].phase, 'uncertain', 'transport uncertainty remains locked');
  const postBeforeRetry = calls.filter((call) => call.method === 'POST').length;
  await submitApprovalsReview(uncertain, 'approve', '', '');
  assert.equal(calls.filter((call) => call.method === 'POST').length, postBeforeRetry, 'uncertain review never re-POSTs');
  assert.ok(document.getElementById('approvalsBody').querySelectorAll('button').some((button) => button.textContent === 'Check status'), 'uncertain review has GET-only check');

  const edited = { id: 'draft-4', category: 'timely', text: 'Original text' };
  data.approvals.workspace.tabs.timely.push(edited);
  await submitApprovalsReview(edited, 'edit', 'Revised text', '');
  assert.equal(data.approvalsReviews['draft-4'].phase, 'saved');
  assert.equal(data.approvalsReviews['draft-4'].draft.text, 'Revised text', 'successful edit updates draft text');
  assert.ok(document.getElementById('approvalsBody').findText('Revised text'), 'revised text appears in card');
  assert.equal(calls.find((call) => call.body?.id === 'draft-4' && call.body.action === 'edit').body.text, 'Revised text', 'actual edited text sent upstream');
  const explicitApproval = approvalsDrafts().find((draft) => draft.id === 'draft-4');
  await submitApprovalsReview(explicitApproval, 'approve', '', '');
  assert.equal(data.approvalsReviews['draft-4'].phase, 'scheduled', 'edited draft may be explicitly approved later');
  assert.equal(calls.filter((call) => call.body?.id === 'draft-4' && call.body.action === 'approve').length, 1, 'later approval is a new explicit POST');

  // A newly opened chat may still be loading when the beginner presses Send.
  const input = document.getElementById('messageInput');
  const composer = document.getElementById('composer');
  const send = document.getElementById('sendButton');
  input.value = 'My first question';
  data.chatId = 'agent:first'; data.authenticated = false;
  let releaseChat;
  data.chatReady = { id: data.chatId, promise: new Promise((resolve) => { releaseChat = resolve; }) };
  const messageCalls = [];
  context.fetch = async (url, options = {}) => {
    if (url === '/api/message') { messageCalls.push(JSON.parse(options.body)); return { ok: true, status: 200, json: async () => ({ ok: true }) }; }
    return new Promise(() => {});
  };
  const firstSend = context.__test.sendMessage({ preventDefault() {} });
  assert.equal(messageCalls.length, 0, 'send waits until first chat finishes loading');
  assert.equal(input.value, '', 'composer clears immediately while the chat finishes loading');
  assert.ok(document.getElementById('messageList').findText('My first question'), 'optimistic bubble is visible before posting');
  releaseChat(true);
  await firstSend;
  assert.equal(messageCalls.length, 1, 'first message is posted once when ready');
  assert.equal(messageCalls[0].text, 'My first question');
  assert.equal(input.value, '', 'successful first send clears the draft');
  assert.equal(send.disabled, false);

  input.value = 'Send this question';
  data.chatReady = { id: data.chatId, promise: new Promise((resolve) => { releaseChat = resolve; }) };
  const sendWithNewDraft = context.__test.sendMessage({ preventDefault() {} });
  input.value = 'My next question'; data.retryRequest = null;
  releaseChat(true);
  await sendWithNewDraft;
  assert.equal(messageCalls[1].text, 'Send this question', 'captured message sends while a new draft is typed');
  assert.equal(input.value, 'My next question', 'successful send never erases a newer draft');

  let submitted = 0; composer.requestSubmit = () => { submitted++; };
  input.value = 'Ask two helpers'; context.__test.askEveryone();
  assert.equal(input.value, '@all Ask two helpers');
  assert.equal(submitted, 1, 'Ask everyone sends existing text with one tap');
  input.value = '@all '; context.__test.askEveryone();
  assert.equal(submitted, 1, 'bare @all prompts for text instead of sending');

  input.value = 'Keep this draft'; data.chatReady = { id: data.chatId, promise: Promise.resolve(true) };
  context.fetch = async () => { throw new Error('Network failed'); };
  await context.__test.sendMessage({ preventDefault() {} });
  assert.equal(input.value, '', 'failed send stays in its bubble while composer remains clear');
  assert.ok(document.getElementById('messageList').findText('Not delivered · Retry'), 'failed bubble has a retry action');
  assert.equal(document.getElementById('toast').textContent, 'Network failed', 'failed send gives a visible error');
  assert.equal(composer.dataset.pending, 'false');

  input.value = 'Do not erase me'; composer.hidden = false;
  await context.__test.openChat('agent:first');
  assert.equal(input.value, 'Do not erase me', 'opening the same chat again preserves an in-progress draft');

  // F05: the getting-started action opens the existing Guide without creating a Pip.
  const savedAgents = data.agents, savedChats = data.chats, savedChatId = data.chatId, savedMessages = data.messages;
  data.agents=[{id:'guide',name:'Guide',guide:true}];
  data.chats=[{id:'agent:guide',type:'direct',agent_id:'guide',agents:['guide']}];
  context.fetch=async (url)=>({ok:true,status:200,json:async()=>url.startsWith('/api/chat?') ? {messages:[]} : {}});
  await context.__test.openGettingStartedGuide();
  assert.equal(data.chatId,'agent:guide');
  assert.equal(document.getElementById('agentDialog').open,false);
  data.agents=savedAgents; data.chats=savedChats; data.chatId=savedChatId; data.messages=savedMessages;

  let releaseOldState;
  context.fetch = async (url) => url === '/api/state' ? new Promise((resolve) => { releaseOldState = resolve; }) : new Promise(() => {});
  const oldState = context.__test.refreshState();
  data.stateRequest++; // A successful creation invalidates state fetched before that POST.
  data.creatingChatId = null;
  releaseOldState({ ok: true, status: 200, json: async () => ({ agents: [], chats: [], statuses: [] }) });
  await oldState;
  assert.equal(data.chatId, 'agent:first', 'late pre-creation state cannot close the new chat after the creation marker clears');

  data.authenticated = true;
  data.messages = []; data.deltas.clear(); data.closedDeltas.clear(); context.__test.sendFeel.optimistic.clear(); context.__test.sendFeel.finishing.clear();
  document.getElementById('messageList').replaceChildren();
  context.fetch = async () => new Promise(() => {});
  context.__test.connectEvents();
  const change = (payload) => eventSource.listeners.change({ data: JSON.stringify(payload) });
  change({ kind: 'delta', job_id: 9, chat_id: 'agent:first', agent_id: 'first', text: 'Partial ans' });
  assert.ok(document.getElementById('messageList').findText('Partial ans'), 'partial answer appears live');
  assert.equal(document.getElementById('messageList').querySelectorAll('.streaming-message').length, 1);
  change({ kind: 'message', job_id: 9, chat_id: 'agent:first' });
  assert.equal(document.getElementById('messageList').querySelectorAll('.streaming-message').length, 1, 'final event retains draft until authoritative reply arrives');
  data.messages = [{ id: 99, role: 'assistant', agent_id: 'first', text: 'Final answer', job_id:9 }];
  context.__test.reconcileMessages();
  assert.ok(document.getElementById('messageList').findText('Final answer'), 'stored final answer replaces draft');
  change({ kind: 'delta', job_id: 9, chat_id: 'agent:first', agent_id: 'first', text: 'Late partial' });
  assert.equal(document.getElementById('messageList').querySelectorAll('.streaming-message').length, 0, 'late delta cannot resurrect finished draft');
  change({ kind: 'status', job_id: 9, chat_id: 'agent:first', status: 'working' });
  change({ kind: 'delta', job_id: 9, chat_id: 'agent:first', agent_id: 'first', text: 'Handoff answer' });
  assert.equal(document.getElementById('messageList').querySelectorAll('.streaming-message').length, 1, 'handoff may stream with reused job id');
  change({ kind: 'status', job_id: 9, chat_id: 'agent:first', status: 'stopped' });
  assert.equal(document.getElementById('messageList').querySelectorAll('.streaming-message').length, 0, 'stopped job removes partial answer');
  change({ kind: 'delta', job_id: 10, chat_id: 'agent:first', agent_id: 'first', text: 'Will fail' });
  change({ kind: 'status', job_id: 10, chat_id: 'agent:first', status: 'error' });
  assert.equal(document.getElementById('messageList').querySelectorAll('.streaming-message').length, 0, 'error removes partial answer');
  const reactionCalls = [];
  data.chatId = null;
  let confirmationText;
  context.confirm = (text) => { confirmationText = text; return true; };
  context.fetch = async (url, options = {}) => {
    if (url !== '/api/reaction') throw new Error(`Unexpected ${url}`);
    const body = JSON.parse(options.body); reactionCalls.push(body);
    return { ok: true, status: 200, json: async () => reactionCalls.length === 1 ? { confirmation_required: true, card_action: 'Approve', title: 'Draft' } : { reactions: ['👍'] } };
  };
  const button = new Node('button'), reacted = { id: 88, role: 'assistant', reactions: [] };
  await context.__test.react(reacted, '👍', button);
  assert.equal(reactionCalls.length, 2, 'approval reaction previews then confirms');
  assert.equal(confirmationText, undefined, 'primary approval never opens a browser dialog');
  assert.equal(reactionCalls[0].active, true, 'reaction requests desired state');
  assert.ok(reactionCalls[0].request_id && reactionCalls[0].request_id !== reactionCalls[1].request_id, 'preview and confirm use separate request IDs');
  assert.equal(reactionCalls[1].confirm, true, 'confirmation sent to guarded backend');
  assert.equal(reacted.reactions[0], '👍', 'confirmed reaction appears');
  reactionCalls.length=0;
  context.fetch=async (url,options={})=>{reactionCalls.push(JSON.parse(options.body));return {ok:true,status:200,json:async()=>reactionCalls.length===1?{confirmation_required:true,action:'Create',title:'Writer'}:{reactions:['✅']}};};
  await context.__test.react({id:89,role:'assistant',reactions:[]},'✅',new Node('button'));
  assert.equal(confirmationText,undefined,'Guide reaction creates without a browser dialog');
  assert.equal(reactionCalls[1].confirm,true,'Guide reaction confirms through reaction endpoint');

  // PASS 11: Pip styles keep their generated identity until the user edits the picker.
  const manyAgents = Array.from({length: 200}, (_, i) => ({id:`pip-${i}`,name:`Pip ${String(i).padStart(3,'0')}`,title:i===17?'Orchard research':'General helper',role:i===23?'chef':'helper'}));
  const assigned = context.window.Pips.assignPips(manyAgents);
  assert.equal(assigned.length, 200, 'new agents receive a saved Pip style');
  const signatures = assigned.map(({pip_style}) => JSON.stringify(pip_style));
  assert.equal(new Set(signatures).size, 200, '200 new Pips have distinct stable combinations');
  manyAgents.forEach((agent) => { agent.pip_style = assigned.find((item) => item.id === agent.id).pip_style; });
  assert.equal(context.window.Pips.assignPips(manyAgents).length, 0, 'saved Pip styles are never reassigned on refresh');
  const pip = context.__test.pipPicker(manyAgents[17]);
  assert.equal(context.__test.readPipPicker(pip).pip_style.palette, manyAgents[17].pip_style.palette, 'saved style round trips without edits');
  const freshPip = context.__test.pipPicker({id:'fresh-pip',name:'Fresh'});
  assert.equal(context.__test.readPipPicker(freshPip).pip_style, undefined, 'unmodified new Pip keeps its generated style');
  freshPip.querySelector('[name=palette]').value = 'coral'; freshPip.querySelector('[name=palette]').events.change();
  assert.equal(context.__test.readPipPicker(freshPip).pip_style.palette, 'coral', 'picker records a deliberate colour change');
  freshPip.querySelector('[name=avatar_style]').value = 'emoji'; freshPip.querySelector('[name=avatar_style]').events.change();
  assert.equal(context.__test.readPipPicker(freshPip).avatar_style, 'emoji', 'emoji remains an available override');

  const rows = context.__test.windowedRows(manyAgents, (item) => new Node(item.id), 'smoke-200', 60);
  assert.equal(rows.style.height, '420px', 'long lists keep a fixed viewport height');
  assert.equal(rows.querySelector('.window-spacer').style.height, '12000px', 'virtual spacer reserves all 200 row heights');
  assert.ok(rows.querySelector('.window-rows').children.length < 20, 'only visible rows are mounted');
  rows.scrollTop = 6000; rows.events.scroll();
  assert.equal(rows.querySelector('.window-rows').style.top, '5880px', 'scroll moves the mounted row window');
  assert.equal(rows.querySelector('.window-rows').children[0].tagName, 'pip-98', 'scroll displays rows near the requested position');

  for (const size of [3, 12, 13, 200]) {
    const agents = manyAgents.slice(0, size);
    data.agents = agents;
    data.chats = agents.map((a, i) => ({id:`agent:${a.id}`,type:'direct',name:a.name,agents:[a.id],updated:Math.floor(Date.now()/1000)-i*86400}));
    data.pinned = ['agent:pip-0']; data.navFilter = '';
    context.__test.renderNav();
    const list = document.getElementById('agentList');
    const ids = list.querySelectorAll('.nav-wrap').map((row) => row.dataset.chatId);
    assert.equal(ids.length, Math.min(size, 12), `${size} Pips have the expected visible count`);
    assert.equal(new Set(ids).size, ids.length, `${size} Pips have unique visible chat ids`);
    assert.equal(ids[0], 'agent:pip-0', `${size} Pips put pinned chat first`);
    assert.equal(list.querySelectorAll('.show-all-row').length, Number(size > 12), `${size} Pips expose directory only over twelve`);
  }
  data.agents = ['Amy','Zed','Bob','No activity','Alpha'].map((name, i) => ({id:`order-${i}`,name}));
  data.chats = data.agents.map((a, i) => ({id:`agent:${a.id}`,type:'direct',name:a.name,agents:[a.id],updated:[0,Date.now()/1000-30*86400,Date.now()/1000-2*86400,0,0][i]}));
  data.pinned = ['agent:order-0']; context.__test.renderNav();
  assert.deepEqual(document.getElementById('agentList').querySelectorAll('.nav-wrap').map((row)=>row.dataset.chatId), ['agent:order-0','agent:order-2','agent:order-1','agent:order-4','agent:order-3'], 'pinned, all activity by recency, then inactive names alphabetically');
  const groups = Array.from({length:13}, (_, i) => ({id:`group:sample-${i}`,type:'group',name:`Group ${i}`,agents:[],updated:0}));
  groups[5].source_chat_id = groups[5].id;
  data.chats.push(...groups); data.pinned.push(groups[0].id); context.__test.renderNav();
  const groupList = document.getElementById('groupList');
  assert.equal(groupList.querySelectorAll('.nav-wrap').length, 12, 'Groups use the same twelve-row preview');
  assert.equal(new Set(groupList.querySelectorAll('.nav-wrap').map((row)=>row.dataset.chatId)).size, 12, 'Groups have unique visible ids');
  groupList.querySelector('.show-all-row').click();
  assert.equal(document.getElementById('directoryGrid').querySelectorAll('.pip-card').length, 13, 'Show all Groups reaches every group');
  document.getElementById('directoryDialog').close();
  data.agents = manyAgents; data.chats = manyAgents.map((a,i) => ({id:`agent:${a.id}`,type:'direct',name:a.name,agents:[a.id],updated:Math.floor(Date.now()/1000)-i*86400}));
  data.pinned = ['agent:pip-0']; data.navFilter = ''; data.navExpanded = {}; data.navScroll = {};
  context.__test.renderNav();
  const sidebar = document.getElementById('agentList');
  assert.ok(sidebar.findText('Show all 200'), 'sidebar exposes the complete directory count');
  assert.equal(sidebar.querySelectorAll('.window-list').length, 1, 'one ordered Pip list replaces duplicate sections');
  assert.equal(sidebar.querySelectorAll('.nav-wrap').length, 12, 'large Pip lists show twelve rows');
  assert.equal(sidebar.querySelectorAll('.nav-pin').length, 1, 'pinned Pip has one pin marker');
  context.__test.setupSidebarSearch();
  const search = document.getElementById('searchButton');
  search.value = 'pip 042'; search.events.input();
  assert.deepEqual(sidebar.querySelectorAll('.nav-wrap').map((row) => row.dataset.chatId), ['agent:pip-42'], 'Search chats filters the sidebar live');
  search.events.keydown({key:'Enter',preventDefault(){}});
  assert.equal(document.getElementById('paletteDialog').open, true, 'Enter opens full search');
  assert.equal(document.getElementById('paletteInput').value, 'pip 042', 'full search receives sidebar query');
  document.getElementById('paletteDialog').close();
  document.events.keydown({key:'k',metaKey:true,preventDefault(){}});
  assert.equal(document.getElementById('paletteDialog').open, true, 'Command-K opens full search');
  document.getElementById('paletteDialog').close();
  search.value = ''; search.events.input();
  sidebar.querySelector('.show-all-row').click();
  assert.equal(document.getElementById('directoryDialog').open, true, 'Show all opens the directory');
  assert.equal(document.getElementById('directoryGrid').querySelectorAll('.pip-card').length, 60, 'directory keeps sixty-card pages');
  document.getElementById('directoryDialog').close();
  data.navFilter = 'orchard'; context.__test.renderNav();
  assert.ok(sidebar.findText('Pip 017'), 'sidebar search matches titles');
  data.navFilter = 'chef'; context.__test.renderNav();
  assert.ok(sidebar.findText('Pip 023'), 'sidebar search matches roles');
  data.navFilter = 'pip 042'; context.__test.renderNav();
  assert.ok(sidebar.findText('Pip 042'), 'sidebar search matches names');
  data.navFilter = ''; context.__test.renderNav();

  data.directoryKind = 'agents'; data.directorySelected.clear();
  document.getElementById('directorySearch').value = '';
  document.getElementById('directoryRole').value = '';
  document.getElementById('directorySort').value = 'name';
  context.__test.renderDirectory();
  const grid = document.getElementById('directoryGrid');
  assert.ok(grid.findText('Page 1 of 4'), '200 Pip directory uses bounded content-sized pages');
  assert.equal(grid.querySelectorAll('.pip-card').length, 60, 'directory mounts at most sixty content-sized cards');
  const allDirectoryIds = [];
  for (let page = 0; page < 4; page++) {
    allDirectoryIds.push(...grid.querySelectorAll('.pip-card').map((card) => card.dataset.chatId));
    if (page < 3) grid.querySelectorAll('button').find((n)=>n.textContent==='Next').click();
  }
  assert.equal(allDirectoryIds.length, 200, 'all 200 Pips are reachable in directory pages');
  assert.equal(new Set(allDirectoryIds).size, 200, 'directory pages contain each chat exactly once');
  data.directoryPage = 0; context.__test.renderDirectory();
  grid.querySelectorAll('button').find((n)=>n.textContent==='Next').click();
  assert.ok(grid.findText('Pip 060') && !grid.findText('Pip 000'), 'next page reaches the next Pips');
  grid.querySelectorAll('button').find((n)=>n.textContent==='Previous').click();
  assert.ok(grid.querySelector('.pip-card').findText('Pip 000'), 'name sort starts alphabetically');
  document.getElementById('directorySort').value = 'recent'; context.__test.renderDirectory();
  assert.ok(grid.querySelector('.pip-card').findText('Pip 000'), 'recent sort puts latest activity first');
  const researchChip = document.getElementById('directoryChips').children.find((n) => n.textContent === 'Research');
  assert.ok(researchChip, 'directory offers human role filters'); researchChip.click();
  assert.ok(grid.findText('Pip 017') && !grid.findText('Pip 000'), 'role filter narrows cards by job');
  data.directoryRole=''; context.__test.renderDirectory();
  assert.ok(document.getElementById('directoryRole').hidden, 'duplicate role dropdown stays hidden');
  document.getElementById('directoryRole').value = ''; document.getElementById('directorySearch').value = 'orchard'; context.__test.renderDirectory();
  assert.ok(grid.findText('Pip 017') && !grid.findText('Pip 000'), 'directory searches title');
  document.getElementById('directorySearch').value = ''; context.__test.renderDirectory();
  const selection = grid.querySelector('.pip-card').querySelector('input'); selection.checked = true; selection.events.change();
  assert.equal(data.directorySelected.size, 1, 'directory selection supports bulk actions');
  assert.equal(document.getElementById('directoryArchive').disabled, false, 'archive enabled after selection');
  data.hiddenAgents=[{id:'hidden-linked',name:'Hidden linked',title:'Research',linked:true,archived:true}];
  document.getElementById('directorySearch').value='Hidden linked'; context.__test.renderDirectory();
  assert.ok(!grid.findText('Hidden linked'),'hidden linked Pip is absent by default');
  document.getElementById('directoryShowHidden').checked=true;context.__test.renderDirectory();
  assert.ok(grid.findText('Hidden linked') && grid.findText('Linked') && grid.findText('Unarchive'),'Show hidden reveals linked Pip and restore action');
  document.getElementById('directoryShowHidden').checked=false;document.getElementById('directorySearch').value='';context.__test.renderDirectory();

  const guide = {id:'guide',name:'Guide',guide:true,title:'Makes agents, groups and team tasks for you'};
  data.agents = [guide]; data.chats = [{id:'agent:guide',type:'direct',name:'Guide',agents:['guide']}]; data.chatId = null; data.authenticated = true;
  const starters = context.__test.guideStarters();
  assert.deepEqual(Array.from(starters.children, (n)=>n.textContent), ['Make me a Pip that…','Set up a group for…','What can you do?','Try the Chef and Critic demo']);
  assert.ok(!starters.textContent.includes('Created'), 'rendering starters has no creation side effect');
  const proposal = {kind:'proposal',index:2,status:'pending',proposal:{action:'create_agent',name:'Writer',emoji:'✍️',title:'Writes clear copy',instructions:'Write concise drafts',engine:'claude',model:'haiku',workdir:'/tmp'}};
  const proposalMessage = {id:301,role:'assistant',agent_id:'guide',text:'Here is a proposal.',cards:[proposal]};
  const card = context.__test.proposalCard(proposal,proposalMessage);
  const nestedCard = context.__test.proposalCard({index:0,status:'pending',proposal:{action:'create_group',name:'Writing team',agents:[{name:'Editor',engine:'claude',model:'haiku',title:'Reviews drafts',instructions:'Check clarity.',workdir:'/home/example/project'}]}},proposalMessage);
  assert.ok(nestedCard.findText('Editor · Claude Code · haiku') && nestedCard.findText('Working folder: project') && !nestedCard.findText('/home/example/'),'nested creations disclose their model and working folder before approval');
  assert.ok(context.__test.proposalCard({index:0,status:'pending',proposal:{action:'start_team_task',group:'Writing team',mode:'split',task:'Review copy'}},proposalMessage).findText('Group: Writing team'),'team approval identifies its target group');
  assert.ok(card.findText('Writer') && card.findText('Writes clear copy') && card.findText('Instructions') && card.findText('haiku'), 'proposal card shows identity, preview and model');
  assert.deepEqual(Array.from(card.querySelectorAll('button'), (n)=>n.textContent), ['Create','Edit first','No thanks']);
  const twoCards = context.__test.messageNode({...proposalMessage,cards:[proposal,{...proposal,index:3}]});
  assert.ok(twoCards.findText('Create all'), 'multiple pending proposals expose Create all');
  data.messages = [proposalMessage]; document.getElementById('messageList').replaceChildren(context.__test.messageNode(proposalMessage));
  proposal.status = 'created'; proposal.result = {chat_id:'agent:writer'}; context.__test.reconcileMessages();
  assert.ok(document.getElementById('messageList').findText('Created · Open chat →'), 'reconciliation replaces pending controls with created state');
  assert.ok(!document.getElementById('messageList').findText('No thanks'), 'created card has no pending decision controls');
  assert.ok(context.__test.proposalCard({...proposal,status:'archived',demo:true},proposalMessage).findText('Archived'),'archived demo card replaces stale buttons');

  // Exercise real button handlers with a local, deterministic API response.
  const guideCalls = [];
  context.fetch = async (url, options={}) => { const body=options.body ? JSON.parse(options.body) : null; guideCalls.push({url,body});
    const value = url === '/api/state' ? {agents:[guide],chats:data.chats,statuses:[]} : url === '/api/product' ? {getting_started:{completed:true}} : url.startsWith('/api/chat?') ? {messages:data.messages} : url === '/api/guide/demo' ? {demo_chat_id:'group:demo'} : {ok:true};
    return {ok:true,status:200,json:async()=>value}; };
  await context.__test.archiveDirectory();
  assert.equal(guideCalls.filter((x)=>x.url==='/api/archive').length,0,'first tap only arms inline archive');
  await context.__test.archiveDirectory();
  assert.deepEqual(guideCalls.find((x)=>x.url==='/api/archive').body,{kind:'agent',id:'pip-0'},'bulk archive posts the selected Pip');
  assert.equal(data.directorySelected.size,0,'archived selection clears after refresh');
  data.hiddenAgents=[{id:'hidden-linked',name:'Hidden linked',linked:true,archived:true}];
  document.getElementById('directoryShowHidden').checked=true;document.getElementById('directorySearch').value='Hidden linked';context.__test.renderDirectory();
  await document.getElementById('directoryGrid').querySelectorAll('button').find((n)=>n.textContent==='Unarchive').click();
  assert.deepEqual(guideCalls.find((x)=>x.url==='/api/unarchive').body,{id:'hidden-linked'},'hidden linked Pip restores through unarchive API');
  document.getElementById('directoryShowHidden').checked=false;document.getElementById('directorySearch').value='';
  guideCalls.length = 0;
  data.chatId = null;
  await starters.children[0].click();
  assert.equal(data.chatId,'agent:guide','starter opens Guide chat');
  assert.equal(document.getElementById('messageInput').value,'Make me a Pip that…','starter pre-fills the Guide prompt');
  assert.equal(guideCalls.filter((x)=>x.url==='/api/message').length,0,'starter prefill does not send a model request');
  guideCalls.length = 0; data.chatId = null;
  const allButton = twoCards.querySelectorAll('button').find((n)=>n.textContent==='Create all');
  const createAll = allButton.click(); const duplicateAll = allButton.click(); await Promise.all([createAll,duplicateAll]);
  assert.equal(guideCalls.filter((x)=>x.url==='/api/guide/create-all').length,1,'Create all ignores a second click while pending');
  assert.deepEqual(guideCalls.find((x)=>x.url==='/api/guide/create-all').body,{message_id:301},'Create all names the originating message');
  guideCalls.length = 0;
  const completedMessage = {...proposalMessage,cards:[{...proposal,index:2,status:'created'},{...proposal,index:3,status:'dismissed'}]};
  data.messages = [completedMessage]; document.getElementById('messageList').replaceChildren(twoCards);
  context.__test.reconcileMessages();
  assert.ok(!document.getElementById('messageList').findText('Create all'),'Create all disappears after its proposals resolve');
  const pending = {...proposal,status:'pending'};
  const create = context.__test.proposalCard(pending,proposalMessage).querySelectorAll('button').find((n)=>n.textContent==='Create');
  const firstCreate = create.click(); const secondCreate = create.click(); await Promise.all([firstCreate,secondCreate]);
  assert.equal(confirmationText,undefined,'tapping Create never opens a browser dialog');
  assert.equal(guideCalls.filter((x)=>x.url==='/api/guide/proposal').length,1,'double click creates only once');
  assert.deepEqual(guideCalls.find((x)=>x.url==='/api/guide/proposal').body,{message_id:301,index:2,action:'create'},'Create sends the indexed proposal decision');
  guideCalls.length = 0;
  const dismiss = context.__test.proposalCard(pending,proposalMessage).querySelectorAll('button').find((n)=>n.textContent==='No thanks'); await dismiss.click();
  assert.deepEqual(guideCalls.find((x)=>x.url==='/api/guide/proposal').body,{message_id:301,index:2,action:'dismiss'},'No thanks sends dismissal only');
  guideCalls.length = 0;
  await starters.children[3].click();
  assert.equal(guideCalls[0].url,'/api/guide/demo','demo starter requests the demo route');
  assert.equal(data.chatId,'group:demo','demo result opens its group chat');

  document.getElementById('newAgentButton').events.click = () => document.getElementById('agentDialog').showModal();
  const edit = context.__test.proposalCard(pending,proposalMessage).querySelectorAll('button').find((n)=>n.textContent==='Edit first'); edit.click();
  assert.equal(data.proposalEdit.message_id,301,'edit records the original proposal');
  assert.equal(document.getElementById('agentName').value,'Writer','edit pre-fills the normal creation dialog');
  assert.equal(document.getElementById('agentRole').value,'Write concise drafts','edit preserves proposed instructions');
  assert.equal(document.getElementById('agentDialog').open,true,'edit opens the creation dialog');
  assert.equal(guideCalls.filter((x)=>x.url==='/api/guide/proposal').length,0,'edit opening does not create an agent');
  const renderCalls=[];
  data.chatId=null;data.guideOpened=true;context.location.hash='';
  context.fetch=async (url,options={})=>{renderCalls.push({url,method:options.method||'GET'});return {ok:true,status:200,json:async()=>url==='/api/state'?{agents:[{id:'swarm-worker-1',name:'Worker',swarm:true}],chats:[],statuses:[]}:url==='/api/product'?{}:{}};};
  await context.__test.refreshState();await context.__test.refreshState();
  assert.equal(renderCalls.filter((call)=>call.method!=='GET').length,0,'two renders with an unsaved worker style cause zero writes');
  // Exercise the real page mount with both scripts: Guide greeting already exists when setup arrives.
  const messageList=document.getElementById('messageList');
  messageList.replaceChildren();data.agents=[{id:'guide',name:'Guide',guide:true}];data.chatId='agent:guide';data.chats=[{id:'agent:guide',type:'direct',name:'Guide',agents:['guide']}];
  data.messages=[{id:900,chat_id:'agent:guide',role:'assistant',agent_id:'guide',text:'Welcome',starters:true}];
  context.__test.reconcileMessages();
  assert.ok(messageList.querySelector('.guide-starters'),'Guide greeting is mounted in index.html messageList');
  assert.equal(messageList.querySelector('.scan-offer'),null,'card is absent before first-run setup');
  data.product={};context.fetch=async (url)=>({ok:true,status:200,json:async()=>url==='/api/setup'?{first_run:true}:url==='/api/onboarding'?{status:null,sources:[]}:{}});
  await context.__test.loadSetup();
  const greeting=messageList.querySelector('.guide-starters'), offerCard=messageList.querySelector('.scan-offer');
  assert.ok(offerCard,'first-run setup mounts the scan card into the real index.html messageList');
  assert.equal(offerCard.parent,greeting.parent,'offer follows Guide greeting in the same message');
  await context.__test.loadSetup();
  assert.equal(messageList.querySelectorAll('.scan-offer').length,1,'repeated setup does not duplicate the card');
  const failedCard=context.__test.teamResultCard({index:0,goal:'Check work',status:'failed',workers:[{role:'Reviewer',status:'failed',issue:'Evidence missing'}]});
  assert.ok(failedCard.findText('Needs review means a helper flagged an issue'),'failed team result explains its status');
  const pendingEvent=timers.find((timer)=>timer.ms===250&&!timer.cancelled);
  if (pendingEvent) await pendingEvent.callback();
  let eventStateCalls=0;
  context.fetch=async (url)=>{if(url==='/api/state')eventStateCalls++;return {ok:true,status:200,json:async()=>url==='/api/state'?{agents:[{id:'guide',name:'Guide',guide:true}],chats:[{id:'agent:guide',type:'direct',agents:['guide']}],statuses:[]}:url.startsWith('/api/chat')?{messages:[]}: {}};};
  const timerCount=timers.length;
  for(let i=0;i<20;i++)change({kind:'agents'});
  const scheduled=timers.slice(timerCount).filter((timer)=>timer.ms===250);
  assert.equal(scheduled.length,1,'twenty agent events coalesce into one delayed refresh');
  await scheduled[0].callback();
  assert.equal(eventStateCalls,1,'event burst fetches state only once');
  let releaseState;
  context.fetch=async (url)=>url==='/api/state'?new Promise((resolve)=>{releaseState=resolve;}):{ok:true,status:200,json:async()=>({})};
  const beforeInflight=timers.length;change({kind:'agents'});
  const inFlight=timers.slice(beforeInflight).find((timer)=>timer.ms===250);
  const activeRefresh=inFlight.callback();
  const duringInflight=timers.length;
  for(let i=0;i<20;i++)change({kind:'agents'});
  assert.equal(timers.length,duringInflight,'events during a fetch do not launch overlapping refreshes');
  releaseState({ok:true,status:200,json:async()=>({agents:[{id:'guide',name:'Guide',guide:true}],chats:[{id:'agent:guide',type:'direct',agents:['guide']}],statuses:[]})});
  await activeRefresh;
  assert.equal(timers.slice(duringInflight).filter((timer)=>timer.ms===250).length,1,'in-flight events queue only one follow-up refresh');
  // PASS14: quotes keep a single author and complete words, including heading replies.
  for (const prefix of ['Critic: ', '## Critic\n', '**Critic**\n', '**Critic**: ', '**Critic:** ', 'Critic: Critic: ']) {
    assert.equal(context.__test.quotePreview(prefix + 'Clarity matters most.', 'Critic'), 'Clarity matters most.');
  }
  assert.equal(context.__test.quotePreview('A complete word followedbyaverylongword', '', 20), 'A complete word…');
  assert.equal(context.__test.quotePreview('xxxxxxxxxxxxxxxxxxxxxxxx', '', 10), '…', 'a single long token is not split');
  assert.equal(context.__test.quotePreview('Critic Clarity matters most.', 'Critic'), 'Critic Clarity matters most.', 'ordinary prose is preserved');
  assert.equal(context.__test.quotePreview('Recipe\n@@handoff critic: Review.', 'Chef'), 'Recipe');
  assert.equal(context.__test.visibleHandoffText('Recipe\n@@hand'), 'Recipe', 'partial streamed control line stays hidden');
  for (const [title,role] of [['Writer','Writing'],['Researcher','Research'],['Tester','Coding'],['Deployment helper','Ops'],['Email helper','Inbox'],['Designer','Design'],['SQL helper','Data'],['Chef','Other']]) {
    assert.equal(context.__test.pipRole({title,pip_style:{accessory:'bow'}}),role);
  }
  assert.equal(context.__test.friendlyFolder('/Users/example'), 'Home folder');
  assert.equal(context.__test.friendlyFolder('/Users/example/projects/hub'), 'hub');
  assert.ok(!card.findText('/tmp') && card.findText('Engine: Claude Code') && card.findText('Model: haiku') && card.findText('Folder: tmp'), 'proposal metadata uses named chips and friendly folders');
  data.agents=[{id:'chef',name:'Chef'}]; data.hiddenAgents=[{id:'guide',guide:true}];data.chats=[{id:'agent:chef',type:'direct',agents:['chef']}];data.chatId='agent:chef';data.messages=[];data.deltas.clear();
  context.__test.renderEmpty();assert.ok(document.getElementById('suggestionChips').hidden,'non-Guide empty chat hides Guide starters');
  data.product={};assert.equal(context.__test.shouldWelcome(),false,'existing Pips suppress welcome even when Guide is archived');
  data.agents=[];assert.equal(context.__test.shouldWelcome(),false,'hidden Pips also suppress welcome');
  data.hiddenAgents=[]; document.getElementById('welcomeDialog').open=false;
  const savedStorage=new Map();context.localStorage.getItem=(key)=>savedStorage.get(key)||null;context.localStorage.setItem=(key,value)=>savedStorage.set(key,value);
  assert.equal(context.__test.shouldWelcome(),true,'empty undismissed install offers welcome');
  context.fetch=async()=>({ok:true,status:200,json:async()=>({getting_started:{dismissed:true}})});
  await context.__test.dismissWelcome();data.product={};
  assert.equal(context.__test.shouldWelcome(),false,'Explore first survives setup reload');
  data.agents=[{id:'guide',name:'Guide',guide:true}];data.directorySelected=new Set(['guide']);document.getElementById('directoryArchive').disabled=false;
  let archiveRequests=0;context.fetch=async()=>{archiveRequests++;return {ok:true,status:200,json:async()=>({})};};
  context.confirm=(message)=>{confirmationText=message;return false;};await context.__test.archiveDirectory();
  assert.equal(archiveRequests,0,'first Guide archive tap leaves it in place');assert.equal(document.getElementById('directoryArchive').textContent,'Confirm archive?');
  const idleCalls=[];data.authenticated=true;
  context.fetch=async(url)=>{idleCalls.push(url);return {ok:true,status:200,json:async()=>({authenticated:true})};};
  await context.__test.idleCheck();assert.deepEqual(idleCalls,['/api/session'],'idle thirty-second check makes one request, no worker/jobs polling');
  const initialCalls=[];data.authenticated=false;
  context.fetch=async(url)=>{initialCalls.push(url);return {ok:true,status:200,json:async()=>({authenticated:false})};};
  await context.__test.startSession();assert.deepEqual(initialCalls,['/api/session'],'logged-out load never requests protected state');
  const downloads=[];const oldClick=Node.prototype.click;Node.prototype.click=function(){if(this.tagName==='a')downloads.push(this.href);return oldClick.call(this);};
  const cancelledExport=context.__test.exportFile('/api/export/everything');
  assert.equal(downloads.length,0,'declining export warning does not download');
  assert.ok(context.__test.sendFeel.dialog.findText("Exports include your chat text."));
  context.__test.sendFeel.dialog.querySelectorAll('button').find((n)=>n.textContent==='Cancel').click();await cancelledExport;
  for(const url of ['/api/export/chat?format=md','/api/export/chat?format=json','/api/export/everything']) { const exporting=context.__test.exportFile(url);context.__test.sendFeel.dialog.querySelector('form').events.submit({preventDefault(){}});await exporting; }
  assert.equal(downloads.length,3,'all export formats share the confirmation boundary');Node.prototype.click=oldClick;
  // PASS 16: readable table quote chips, reaction visibility, compact autosizing and Jobs copy.
  assert.equal(context.__test.quotePreview('| **Dish** | Protein |\n| --- | ---: |\n| Tofu | 20g |', ''), 'Dish · Protein Tofu · 20g');
  const input16 = elements.get('messageInput');
  input16.scrollHeight = 38; context.__test.resizeComposer(); assert.equal(input16.style.height, '38px');
  input16.scrollHeight = 160; context.__test.resizeComposer(); assert.equal(input16.style.height, '160px');
  input16.scrollHeight = 900; context.__test.resizeComposer(); assert.equal(input16.style.height, '360px');
  input16.scrollHeight = 38; context.__test.resizeComposer(); assert.equal(input16.style.height, '38px', 'composer shrinks after clearing');
  assert.match(css, /\.compose-line textarea\{height:38px;/, 'initial textarea explicitly starts at one or two lines');
  context.__test.data.jobs = []; context.__test.data.workers = {running:[],done:[],note:'Progress is not available.'};
  context.__test.renderWorkers();
  assert.equal(elements.get('workersBody').querySelectorAll('.empty-note').length, 1, 'empty Jobs shows one explanation');
  console.log('UI smoke checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
