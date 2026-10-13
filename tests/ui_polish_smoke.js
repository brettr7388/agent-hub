/* Real UI functions with local DOM/API fakes; no browser or network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
fixtureSource = fixtureSource.replace('globalThis.__test = { setupComposerInteractions,', 'globalThis.__test = { media, fitChatTitle, fillScheduleAgents, refreshChat, cardNode, ');
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, document, elements, Node };', fixture);
const { context, document, elements, Node } = fixture.fixture;
const app = context.__test, { data } = app;
const get = id => elements.get(id);
const response = (value, status = 200) => ({ ok: status === 200, status, json: async () => value });
context.window.addEventListener = () => {};
context.history.replaceState = () => {};
context.location.pathname = '/'; context.location.hash = '';
context.localStorage.getItem = () => null; context.localStorage.setItem = () => {};
context.document.visibilityState = 'hidden';
data.authenticated = true; data.agents = [{id:'ada',name:'Ada',model:'haiku'},{id:'ben',name:'Ben',model:'haiku'},{id:'helper',name:'Ada',swarm:true}];
data.chats = [{id:'agent:ada',name:'First question',type:'direct',agents:['ada'],updated:1700000000},{id:'chat:latest',name:'Newest question',type:'direct',agents:['ada'],updated:1700000300},{id:'group:pair',name:'Pair',type:'group',agents:['ada','ben']}];
data.chatId = 'group:pair'; data.product = { unread: {} }; data.statuses = [];

// F10: selected Pip label matches the explicit routing sent by the composer.
data.composeAgentId = null; app.renderHeader(); assert.equal(get('modelSelector').textContent, 'Best fit');
data.composeAgentId = 'ada'; app.renderHeader(); assert.equal(get('modelSelector').textContent, 'Ada');
// F11: newest child conversation drives the parent Pip timestamp, still hover-only.
app.renderNav(); const adaRow = get('agentList').querySelectorAll('.nav-item').find(n => n.dataset.chatId === 'agent:ada');
assert.equal(adaRow.querySelector('.nav-time').textContent, app.chatTime(1700000300));
const css = fs.readFileSync(path.join(__dirname,'..','static','style.css'),'utf8');
assert.match(css,/\.pip-conversations>\.pin-button\{[^}]*position:absolute/);
assert.match(css,/\.sidebar \.nav-pin\{display:none\}/);
assert.match(css,/\.sidebar \.nav-item \.nav-time\{display:none\}/);
assert.equal(get('agentList').querySelectorAll('.pin-button').length, 2, 'one actionable star per visible owner Pip');
// F11: actual width measurement removes whole words and restores the full title on resize.
const title=get('chatTitle'); title.dataset.fullTitle='A long descriptive title with complete words'; title.clientWidth=140;
Object.defineProperty(title,'scrollWidth',{configurable:true,get(){return this.textContent.length*8;}});
app.fitChatTitle(); assert.equal(title.textContent,'A long…'); assert.equal(title.dataset.fullTitle,'A long descriptive title with complete words');
title.clientWidth=600; app.fitChatTitle(); assert.equal(title.textContent,title.dataset.fullTitle);
// P1-3: unavailable media and late image failures remain visible.
const blocked=app.media({name:'overflow.png',kind:'unavailable',unavailable:true,reason:'Image unavailable'});
assert.ok(blocked.findText('overflow.png') && blocked.findText('Image unavailable')); assert.equal(blocked.querySelector('img'),null);
const available=app.media({name:'overflow.png',kind:'image',url:'/api/file?chat_id=agent%3Aada&message_id=4&path=%2Fproject%2Foverflow.png'});
assert.ok(available.querySelector('img')); available.querySelector('img').events.error(); assert.ok(available.findText('Image unavailable'));
// F3/P2-1: previews retain the full screenshot, including text at its edges.
assert.match(css,/\.image-open img\{height:auto;max-height:320px;object-fit:contain;object-position:top\}/);
assert.match(css,/\.upload-thumbnail\{object-fit:contain;object-position:top/);
// F7: user hover time is a visible styled element, outside bubble flow.
const user=app.messageNode({id:5,role:'user',text:'Hello',created:1700000000}); assert.ok(user.querySelector('time').textContent);
assert.match(css,/\.message\.user:hover \.message-head,\.message\.user:focus-within \.message-head\{opacity:1;visibility:visible\}/);
// P1-6/F9: action buttons never wrap and phone approvals/content use the space.
assert.match(css,/\.list-card button\{overflow-wrap:normal;white-space:nowrap;flex:none\}/);
assert.match(css,/\.list-card \.row-actions button\{[^}]*width:auto[^}]*min-height:44px/);
assert.match(css,/\.approval-request-actions button,\.card-actions button\{min-height:44px\}/);
assert.match(css,/@media\(max-width:700px\)\{\s*\.pip-conversations>\.pin-button\{top:10px\}\s*\.message-list\{width:100%;padding:20px 12px 28px\}/);
assert.match(css,/\.message\.assistant>\.message-content,\.message\.system\.team-task-message \.message-content\{width:min\(100%,768px\);max-width:100%\}/);
// F9: a microphone drawing exists and is accessible even without recognition support.
assert.ok(get('voiceButton').querySelector('svg')); assert.match(fs.readFileSync(path.join(__dirname,'..','static','index.html'),'utf8'),/id="voiceButton"[^>]*aria-label="Voice typing"/);
// P2-5: helper Pips never appear in the picker; visible copy calls these schedules.
app.fillScheduleAgents(); assert.deepEqual(Array.from(get('routineAgent').children,n=>n.value),['ada','ben']);
const html=fs.readFileSync(path.join(__dirname,'..','static','index.html'),'utf8'); assert.ok(html.includes('<h2>New schedule</h2>')); assert.ok(!/>[^<]*\broutine\b/i.test(html));
data.routines={routines:[{id:'r',name:'Daily',agent_id:'ada',trigger:'daily',enabled:true,last_run:0,last_status:'skipped',error:'Hub was unavailable'}]};app.renderRoutines();assert.ok(!get('routinesList').textContent.includes('Last run'));
data.routines.routines[0].error=null;app.renderRoutines();assert.ok(get('routinesList').textContent.includes('Schedule skipped'));assert.ok(!get('routinesList').textContent.includes('Last run'));
// F5: rename dialog uses its requested field label, retaining normal draft labels elsewhere.
const renamed=app.appActionDialog({title:'Rename chat',value:'Old title',fieldLabel:'Chat name'});
assert.equal(app.sendFeel.dialog.querySelector('textarea')['aria-label'],'Chat name'); app.sendFeel.dialog.querySelectorAll('button')[0].click();
// UC1 F7: destination is literal Pip metadata, never inferred from summary or rendered as HTML.
const approval=app.cardNode({kind:'approval_request',index:0,summary:'Send this draft',details:'Exact text',destination:'http://127.0.0.1:4841 / @alex_k <b>local</b>'},{id:7,chat_id:data.chatId});
assert.ok(approval.findText('Destination: http://127.0.0.1:4841 / @alex_k <b>local</b>')); assert.ok(!approval.findText('Instagram'));
assert.ok(approval.findText('Provided by the Pip')); assert.equal(approval.querySelector('b'),null);
(async()=>{
  let sent;
  data.chatId='group:pair'; data.composeAgentId='ada'; get('messageInput').value='Explain fractions';
  context.fetch=async(url,options={})=> {if(url==='/api/message'){sent=JSON.parse(options.body);return response({message_id:10,job_ids:[]});} if(url.startsWith('/api/chat?'))return response({chat:data.chats.find(c=>c.id===data.chatId),messages:[{id:10,role:'user',text:'Explain fractions',request_id:sent?.request_id}]});return response({});};
  await app.sendMessage({preventDefault(){}});assert.equal(sent.agent_id,'ada');assert.equal(sent.text,'Explain fractions');
  // P1-4: deleted chat rejects promptly and replaces its loading skeleton with an action.
  context.fetch=async()=>response({error:'Chat not found.'},404);data.messages=[];
  await app.openChat('agent:deleted');assert.ok(get('messageList').findText('no longer available'));assert.ok(get('messageList').findText('Open Guide'));assert.equal(get('messageList').querySelector('.list-skeleton'),null);assert.ok(get('composer').hidden);assert.ok(!get('messageViewport').hidden);
  console.log('UI polish smoke checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
