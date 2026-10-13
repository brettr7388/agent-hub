/* Real controls, delayed fake API/SpeechRecognition, offline DOM layout contracts. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
fixtureSource = fixtureSource.replace("vm.runInNewContext(source, context);", "vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'chat-parity.js'), 'utf8'), context); vm.runInNewContext(source, context);");
fixtureSource = fixtureSource.replace('globalThis.__test = { setupComposerInteractions,', 'globalThis.__test = { parity, refreshChat, ');
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, document, elements, timers, Node };', fixture);
const { context, document, elements, timers, Node } = fixture.fixture;
const app = context.__test, { data, parity } = app;
const get = id => elements.get(id), viewport = get('messageViewport'), list = get('messageList'), input = get('messageInput');
for (const name of ['alert','confirm','prompt','open']) context[name] = context.window[name] = () => { throw new Error('Native dialog used'); };
const response = value => ({ ok: true, status: 200, json: async () => value });
const event = (key, extras = {}) => ({ key, prevented: false, preventDefault() { this.prevented = true; }, ...extras });
const writer = { id: 'writer', name: 'Writer', engine: 'claude' };
data.authenticated = true; data.chatId = 'agent:writer'; data.agents = [writer,{id:'critic',name:'Critic'}];
data.chats = [{id:data.chatId,name:'Writer',type:'direct',agents:['writer']},{id:'chat:two',name:'Project notes',type:'direct',agents:['writer']},{id:'group:crew',name:'Crew',type:'group',agents:['writer','critic']}];
data.statuses = []; data.messages = [{id:1,role:'user',text:'Original question'},{id:2,role:'assistant',agent_id:'writer',text:'Original answer'}];
get('app').hidden = false; get('composer').hidden = false; viewport.hidden = false;
viewport.scrollHeight = 1200; viewport.clientHeight = 600; viewport.scrollTop = 600;
let scrolls = 0; viewport.scrollTo = options => { scrolls++; viewport.scrollTop = Math.max(0, options.top-viewport.clientHeight); };
context.window.addEventListener = () => {};
parity.setup(); assert.ok(get('voiceButton').hidden, 'unsupported recognition hides mic');
assert.match(fs.readFileSync(path.join(__dirname,'..','static','index.html'),'utf8'), /id="voiceButton"[^>]*aria-label="Voice typing"/);

(async () => {
  // Edit own last / any message; send uses edit API, retries retain dedup key.
  input.value = '';
  const up = event('ArrowUp', {target:input}); parity.shortcut(up);
  assert.ok(up.prevented && parity.editing.id === 1); assert.equal(input.value,'Original question');
  assert.ok(!get('editMessageBar').hidden); assert.equal(get('sendButton')['aria-label'],'Save edit and resend');
  get('cancelMessageEdit').click(); assert.equal(parity.editing,null); assert.equal(input.value,'');
  input.value = 'Preserve draft'; parity.startEdit(data.messages[0]); get('cancelMessageEdit').click(); assert.equal(input.value,'Preserve draft');
  data.statuses = [{id:7,chat_id:data.chatId,status:'typing'}]; parity.startEdit(data.messages[0]); assert.equal(parity.editing,null,'busy edit guarded'); data.statuses=[];
  parity.startEdit(data.messages[0]); input.value='Revised question';
  const calls=[]; let fail=true, selectedVersion='v2';
  context.fetch=async(url,options={})=> {const body=options.body && JSON.parse(options.body);calls.push({url,body});if(url==='/api/messages/edit'){if(fail)throw new Error('Lost response');return response({message_id:3,job_id:8});}if(url==='/api/chats/version'){selectedVersion=body.version_id;return response({});}if(url==='/api/state')return response({agents:data.agents,chats:data.chats,statuses:[]});if(url.startsWith('/api/chat?'))return response({messages:[{id:3,role:'user',text:'Revised question'}],versions:[{id:'v1',active:selectedVersion==='v1',label:'Original'},{id:'v2',active:selectedVersion==='v2',label:'Edit'}],active_version:selectedVersion});return response({});};
  await app.sendMessage(event('submit')); assert.ok(parity.editing); const firstId=calls.find(c=>c.url==='/api/messages/edit').body.request_id;
  fail=false; await app.sendMessage(event('submit'));
  assert.equal(calls.filter(c=>c.url==='/api/messages/edit').at(-1).body.request_id,firstId);
  assert.equal(parity.editing,null); assert.ok(!calls.some(c=>c.url==='/api/message'),'edit does not accidentally use ordinary send');
  assert.equal(input.value,''); assert.ok(!get('chatVersions').hidden); assert.match(get('chatVersionSummary').textContent,/2\/2/);
  assert.ok(!get('chatVersionBar').hidden);
  assert.equal(get('chatVersionSummary').textContent,'2/2');
  assert.ok(get('chatVersions').open === false,'earlier version list starts collapsed');
  assert.ok(!get('previousChatVersion').hidden && !get('previousChatVersion').disabled);
  assert.ok(get('nextChatVersion').disabled,'latest version disables forward navigation');
  const switchVersion = get('previousChatVersion').onclick();
  assert.ok(get('previousChatVersion').disabled && get('chatVersionOptions').children.every(button=>button.disabled),'all choices lock during a version switch');
  get('chatVersionOptions').children[0].click();
  await switchVersion;
  assert.deepEqual(JSON.parse(JSON.stringify(calls.filter(c=>c.url==='/api/chats/version').at(-1).body)),{chat_id:'agent:writer',version_id:'v1'});
  assert.equal(get('chatVersionSummary').textContent,'1/2');
  assert.ok(get('previousChatVersion').disabled && !get('nextChatVersion').disabled,'refreshed active version determines arrows after a switch');
  assert.ok(get('chatVersionOptions').children[0].disabled && !get('chatVersionOptions').children[1].disabled,'active version alone is disabled');
  await get('nextChatVersion').onclick();
  assert.equal(get('chatVersionSummary').textContent,'2/2');
  assert.ok(!get('previousChatVersion').disabled && get('nextChatVersion').disabled,'forward switch restores latest controls');
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c=>c.url==='/api/chats/version').body)),{chat_id:'agent:writer',version_id:'v1'});
  // Context menu offers editing arbitrary earlier user messages; timestamps hover.
  const message=app.messageNode({id:15,role:'user',text:'Earlier',created:1700000000});
  app.openMessageMenu({id:15,role:'user',text:'Earlier'},message);
  const edit=document.body.querySelectorAll('button').find(b=>b['aria-label']==='Edit and resend'); assert.ok(edit); edit.click(); assert.equal(parity.editing.id,15); get('cancelMessageEdit').click();
  assert.ok(message.title && message.querySelector('time').title,'hover timestamp on bubble/time');
  // Pip expands recent named conversations; rename/delete use app dialogs and APIs.
  const pip=app.navButton(data.chats[0],writer), base=new Node();base.append(pip);
  parity.pipRow(data.chats[0],base); base.querySelector('.conversation-toggle').click();
  const expanded=new Node();expanded.append(app.navButton(data.chats[0],writer));parity.pipRow(data.chats[0],expanded);
  const starCss=fs.readFileSync(path.join(__dirname,'..','static','style.css'),'utf8');
  const polishCss=starCss.split('/* Chat/UI polish; append-only merge scope. */')[1];
  assert.match(polishCss,/\.pip-conversations>\.pin-button\{top:8px;transform:none\}/,'expanded lists cannot move the star off the owner row');
  assert.ok(expanded.findText('Project notes'));
  assert.equal(expanded.findText('New chat with Writer'),false,'expanded Pip list has no duplicate new-chat action');
  assert.equal(expanded.findText('Ongoing chat'),false,'default conversation uses its real name');
  const row=expanded.querySelectorAll('.pip-conversation-row').find(r=>r.dataset.chatId==='chat:two'); row.querySelector('.conversation-more').click();
  const rename=get('conversationActionsBody').children[0].click();
  assert.ok(app.sendFeel.dialog.open);app.sendFeel.dialog.querySelector('input').value='Renamed';app.sendFeel.dialog.querySelector('form').events.submit(event('submit'));await rename;
  assert.equal(calls.find(c=>c.url==='/api/chats/rename').body.name,'Renamed');
  row.querySelector('.conversation-more').click();const deleting=get('conversationActionsBody').children[1].click();app.sendFeel.dialog.querySelector('form').events.submit(event('submit'));await deleting;
  assert.equal(calls.find(c=>c.url==='/api/chats/delete').body.chat_id,'chat:two');
  data.chats[0].name='Renamed ongoing';app.renderNav();assert.equal(get('agentList').querySelector('.nav-name').textContent,'Writer','conversation rename preserves the parent Pip name');assert.ok(get('agentList').findText('Renamed ongoing'),'renamed default conversation appears in expanded list');
  data.navFilter='Project';app.renderNav();assert.ok(get('agentList').findText('Writer'),'sidebar search includes conversation title');data.navFilter='';
  // New-chat shortcut and sheet; Esc stops active reply while modal Escape stays local.
  context.fetch=async(url,options={})=>{const body=options.body&&JSON.parse(options.body);calls.push({url,body});if(url==='/api/chats/new')return response({chat:{id:'chat:fresh',name:'New chat',type:'direct',agents:['writer']}});if(url==='/api/state')return response({agents:data.agents,chats:[...data.chats,{id:'chat:fresh',name:'New chat',type:'direct',agents:['writer']}],statuses:[]});if(url.startsWith('/api/chat?'))return response({messages:[]});return response({});};
  const shortcut=event('O',{metaKey:true,shiftKey:true});parity.shortcut(shortcut);await new Promise(setImmediate);assert.ok(shortcut.prevented);assert.equal(calls.find(c=>c.url==='/api/chats/new').body.agent_id,'writer');assert.equal(data.chatId,'chat:fresh');
  const sheet=event('/',{ctrlKey:true});parity.shortcut(sheet);assert.ok(sheet.prevented&&get('shortcutsDialog').open);get('shortcutsDialog').close();
  data.statuses=[{id:91,chat_id:data.chatId,status:'typing'}];const escape=event('Escape');parity.shortcut(escape);await new Promise(setImmediate);assert.ok(escape.prevented);assert.equal(calls.find(c=>c.url==='/api/jobs/stop').body.job_id,91);data.statuses=[];
  // Recognition: live interim/final content, click-to-stop, chat switch/signout cleanup.
  let speech;
  class Speech {constructor(){speech=this;}start(){this.started=true;}stop(){this.stopped=true;}}
  context.window.SpeechRecognition=Speech;parity.setup();assert.ok(!get('voiceButton').hidden);
  input.value='My prefix';get('voiceButton').click();assert.ok(speech.started&&speech.interimResults&&speech.continuous);
  const transcript=(text,final)=>Object.assign([{transcript:text}],{isFinal:final});
  speech.onresult({results:[transcript('live words',false)]});assert.equal(input.value,'My prefix live words');assert.equal(get('voiceStatus').textContent,'live words');
  speech.onresult({results:[transcript('final words',true),transcript('next',false)]});assert.equal(input.value,'My prefix final words next');get('voiceButton').click();assert.ok(speech.stopped);assert.equal(get('voiceButton')['aria-pressed'],'false');
  const before=input.value;speech.onresult({results:[transcript('late',true)]});assert.equal(input.value,before,'late stopped result ignored');
  get('voiceButton').click();get('chatVersionBar').hidden=false;get('chatVersions').open=true;get('jumpLatest').hidden=false;parity.reset();assert.ok(get('jumpLatest').hidden&&get('chatVersionBar').hidden&&get('previousChatVersion').hidden&&get('nextChatVersion').hidden&&!get('chatVersions').open,'switch/signout clears floating controls and collapses versions');speech.onresult({results:[transcript('private stale',true)]});assert.equal(input.value,before,'reset cannot leak dictated text into another chat');
  get('voiceButton').click();speech.onerror({error:'not-allowed'});assert.ok(get('toast').findText('Microphone access was denied'));assert.equal(get('voiceButton')['aria-pressed'],'false');
  // B+1: group text visibly grows in the same bubble, routing box is there on first token.
  data.chatId='group:crew';data.messages=[{id:100,role:'user',text:'Question'}];data.deltas.clear();data.closedDeltas.clear();list.replaceChildren();
  data.deltas.set('92',{chat_id:data.chatId,agent_id:'writer',text:'First',reply_to:100,best_fit:true,routing_kind:'best_fit'});app.renderDeltas();
  const stream=list.querySelector('.streaming-message'), route=stream.querySelector('.best-fit-note');assert.ok(route&&stream.findText('First'));
  // Structural layout geometry: routing and quotes before body must be identical at finalize.
  const aboveBody=node=>({quote:node.querySelector('.quote-stack')?.textContent||'',route:node.querySelector('.best-fit-note')?.textContent||'',head:node.querySelector('.message-head')?.querySelector('strong')?.textContent});
  const early=aboveBody(stream);data.deltas.get('92').text='First visible answer';app.renderDeltas();assert.equal(list.querySelector('.streaming-message'),stream);assert.equal(stream.querySelector('.best-fit-note'),route);
  data.messages.push({id:101,role:'assistant',agent_id:'writer',text:'First visible answer',reply_to:100,best_fit:true,routing_kind:'best_fit',job_id:92});app.reconcileMessages();assert.equal(list.children.find(n=>n.dataset.messageId==='101'),stream);assert.deepEqual(aboveBody(stream),early,'best-fit completion adds zero blocks above the body');
  // B+2: handoff quote reserved on first streamed token; finalize adds zero quote height.
  data.deltas.set('93',{chat_id:data.chatId,agent_id:'critic',text:'Review',reply_to:101});app.renderDeltas();const handoff=list.querySelector('.streaming-message');assert.ok(handoff.querySelector('.quote-stack'));
  // A handoff can stream before its parent is fetched; preview reserves its real quote height.
  data.deltas.set('missing-parent',{chat_id:data.chatId,agent_id:'critic',text:'Already reviewing',reply_to:888,reply_parent:{id:888,role:'assistant',agent_id:'writer',text:'A long visible sender answer that arrived before the next history fetch.'}});app.renderDeltas();
  const earlyHandoff=list.querySelectorAll('.streaming-message').find(node=>node.dataset.jobId==='missing-parent');
  assert.ok(earlyHandoff.querySelector('.quoted').findText('A long visible sender answer'));
  const earlyQuote=earlyHandoff.querySelector('.quoted').textContent;
  data.messages.push({id:888,role:'assistant',agent_id:'writer',text:'A long visible sender answer that arrived before the next history fetch.'});app.renderDeltas();
  assert.equal(earlyHandoff.querySelector('.quoted').textContent,earlyQuote,'fetching quote parent does not change streamed quote content/height');
  data.deltas.delete('missing-parent');data.messages=data.messages.filter(message=>message.id!==888);
  const handoffBefore=aboveBody(handoff);data.messages.push({id:102,role:'assistant',agent_id:'critic',text:'Review',reply_to:101,job_id:93});app.reconcileMessages();assert.deepEqual(aboveBody(handoff),handoffBefore);
  // B+3: Ask everyone x-position contract is invariant when Stop toggles.
  const css=fs.readFileSync(path.join(__dirname,'..','static','style.css'),'utf8');
  assert.match(css,/\.stop-slot\{[^}]*width:38px[^}]*flex:0 0 38px/);assert.match(css,/\.compose-toolbar>\.send-button\{margin-left:0/);
  const slot=get('stopButton').parent;assert.ok(slot.classList.contains('stop-slot'));
  const toolbarWidth=700,sendWidth=38,gap=8,slotWidth=38,pillWidth=100;
  const pillLeft=()=>toolbarWidth-sendWidth-slotWidth-2*gap-pillWidth;
  const left= pillLeft();app.renderSend();data.statuses=[{id:94,chat_id:data.chatId,status:'typing'}];app.renderSend();assert.equal(pillLeft(),left,'reserved stop width keeps pill x unchanged');assert.equal(get('stopButton').hidden,false);data.statuses=[];app.renderSend();assert.equal(pillLeft(),left);
  // B+4: Created/Undo toast is bottom-left on centered empty state, above docked composer.
  get('conversation').classList.add('is-empty');get('composer').rect={top:450};app.showCreatedToast({result:{agent:{id:'made',name:'Made'}}});assert.equal(get('toast').style.bottom,'20px');assert.match(css,/\.toast\{left:20px;transform:none/);
  get('conversation').classList.remove('is-empty');app.positionToast();assert.equal(get('toast').style.bottom,'462px');
  // B+5: inserting sidebar Pip retains old row indices/scroll position.
  assert.match(css,/@keyframes nav-row-added\{from\{opacity:0\}to\{opacity:1\}\}/);
  const old=[{id:'agent:a'},{id:'agent:b'}],initial=parity.stableOrder(old,'layout');const added=parity.stableOrder([{id:'agent:c'},...old].reverse(),'layout');assert.deepEqual(Array.from(added,x=>x.id),['agent:a','agent:b','agent:c']);assert.equal(added.indexOf(old[1])*48,initial.indexOf(old[1])*48,'new row causes zero shift to visible existing row');const inserted=new Node();parity.animateRow(inserted,'agent:c');assert.ok(inserted.classList.contains('nav-added'),'new row fades in at its final size');
  const sidebarScroller=get('sidebar').querySelector('.side-scroll');sidebarScroller.scrollTop=72;app.renderNav();assert.equal(sidebarScroller.scrollTop,72);
  // B+6/B5: incoming streaming + final replies preserve an up-scrolled reader; jump is actionable.
  viewport.scrollTop=120;viewport.scrollHeight=1800;viewport.clientHeight=600;
  app.connectEvents();const change=value=>data.eventSource.listeners.change({data:JSON.stringify(value)});
  const scrollCount=scrolls;change({kind:'delta',chat_id:data.chatId,job_id:95,agent_id:'writer',text:'New answer',reply_to:100,best_fit:true});assert.equal(viewport.scrollTop,120);assert.equal(scrolls,scrollCount);assert.ok(!get('jumpLatest').hidden);
  context.fetch=async(url)=>response(url.startsWith('/api/chat?')?{messages:[...data.messages,{id:103,role:'assistant',agent_id:'writer',text:'New answer',reply_to:100,best_fit:true,job_id:95}]}:{});
  await app.refreshChat();assert.equal(viewport.scrollTop,120);assert.ok(!get('jumpLatest').hidden);
  get('jumpLatest').click();assert.equal(viewport.scrollTop,1200);assert.ok(get('jumpLatest').hidden);
  // Moving up while a history request is pending must cancel automatic following.
  let deliverHistory;context.fetch=async(url)=>url.startsWith('/api/chat?')?new Promise(resolve=>{deliverHistory=resolve;}):response({});
  const pendingHistory=app.refreshChat();viewport.scrollTop=100;const beforeHistoryScrolls=scrolls;
  deliverHistory(response({messages:data.messages}));await pendingHistory;assert.equal(viewport.scrollTop,100);assert.equal(scrolls,beforeHistoryScrolls);
  viewport.scrollTop=1200;
  const scrollNow=scrolls;change({kind:'delta',chat_id:data.chatId,job_id:96,agent_id:'writer',text:'Following latest'});assert.ok(scrolls>scrollNow,'already-bottom reader follows stream');
  console.log('Parity and six layout-stability smoke checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
