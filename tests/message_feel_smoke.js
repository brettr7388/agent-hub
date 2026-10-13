/* Playwright-free delayed-network checks using the existing plain-DOM fixture. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, document, elements, timers, Node };', fixture);
const { context, document, elements, timers, Node } = fixture.fixture;
const app = context.__test, data = app.data;
const input = elements.get('messageInput'), list = elements.get('messageList'), viewport = elements.get('messageViewport');
const forbidden = () => { throw new Error('Native browser dialog invoked'); };
for (const name of ['confirm', 'alert', 'prompt']) context[name] = context.window[name] = forbidden;
const response = (value, ok = true) => ({ ok, status: ok ? 200 : 503, json: async () => value });
const submit = { preventDefault() {} };
let scroll; const scrollRequests = [];
viewport.scrollHeight = 700; viewport.clientHeight = 650; viewport.scrollTop = 50;
viewport.scrollTo = (options) => { scroll = options; scrollRequests.push(options); viewport.scrollTop = options.top; };
data.chatId = 'agent:writer'; data.authenticated = true; data.guideOpened = true;
data.agents = [{ id: 'writer', name: 'Writer' }]; data.chats = [{ id: data.chatId, type: 'direct', agents: ['writer'] }];

(async () => {
  let releaseChat, releaseSend, sentBody, posts = 0;
  data.chatReady = { id: data.chatId, promise: new Promise((resolve) => { releaseChat = resolve; }) };
  context.fetch = async (url, options = {}) => {
    if (url === '/api/message') { posts++; sentBody = JSON.parse(options.body); return new Promise((resolve) => { releaseSend = resolve; }); }
    if (url.startsWith('/api/chat?')) return response({ messages: [{ id: 101, role: 'user', text: 'Hello instantly', request_id: sentBody.request_id, acknowledged: false, chat_id: data.chatId }] });
    return response({});
  };
  input.value = 'Hello instantly';
  const sending = app.sendMessage(submit);
  assert.equal(posts, 0, 'chat loading still gates the POST');
  assert.equal(input.value, '', 'composer clears before any round trip');
  assert.ok(input.focused, 'composer keeps focus');
  const userBubble = list.children.find((node) => node.classList.contains('user'));
  assert.ok(userBubble.findText('Hello instantly'));
  assert.ok(userBubble.classList.contains('optimistic-send'));
  assert.equal(userBubble.querySelector('.message-ack').textContent, '', 'optimistic storage never means Seen');
  const waitingBubble = list.querySelector('.streaming-message');
  assert.equal(waitingBubble.querySelector('.typing-bubble').children.length, 3);
  assert.equal(scroll.behavior, 'smooth');
  assert.equal(app.mergeSentMessages([], data.chatId).length, 1, 'stale history retains the optimistic message');
  releaseChat(true); await new Promise(setImmediate);
  assert.equal(posts, 1);
  input.value = 'Next question';
  app.connectEvents();
  const change = (value) => data.eventSource.listeners.change({ data: JSON.stringify(value) });
  change({kind:'status',status:'choosing',chat_id:data.chatId});
  assert.ok(elements.get('activity').hidden, 'routing uses the reserved dots rather than inserting a layout-shifting status bar');
  change({ kind: 'status', status: 'queued', job_id: 81, chat_id: data.chatId, request_id: sentBody.request_id });
  assert.equal(list.querySelectorAll('.streaming-message').length, 1, 'queued event migrates the reserved typing bubble');
  assert.equal(list.querySelector('.streaming-message'), waitingBubble);
  change({ kind: 'seen', chat_id: data.chatId, message_id: 101, request_id: sentBody.request_id, job_id: 81 });
  assert.equal(userBubble.querySelector('.message-ack').textContent, 'Seen');
  releaseSend(response({ message_id: 101, request_id: sentBody.request_id, job_id: 81, job_ids: [81] }));
  await sending;
  assert.equal(list.children.find((node) => node.classList.contains('user')), userBubble, 'server acknowledgment retains bubble identity');
  assert.equal(userBubble.dataset.messageId, '101');
  assert.equal(data.messages.length, 1, 'request_id reconciliation removes duplicates');
  assert.equal(userBubble.querySelector('.message-ack').textContent, 'Seen', 'late stale history cannot erase a receipt');
  assert.equal(input.value, 'Next question', 'confirmation preserves a newly typed draft');
  assert.equal(scrollRequests.length, 1, 'acknowledgment does not cancel the initial smooth scroll');

  change({ kind: 'delta', job_id: 81, chat_id: data.chatId, agent_id: 'writer', text: 'Hello' });
  const replyBubble = list.querySelector('.streaming-message'), replyHead = replyBubble.querySelector('.message-head');
  assert.equal(replyBubble, waitingBubble);
  assert.equal(replyBubble.querySelector('.typing-bubble'), null, 'first reply text replaces dots');
  change({ kind: 'delta', job_id: 81, chat_id: data.chatId, agent_id: 'writer', text: 'Hello back' });
  assert.equal(list.querySelector('.streaming-message'), replyBubble, 'stream deltas retain the article');
  assert.equal(replyBubble.querySelector('.message-head'), replyHead, 'stream deltas retain the avatar/header');
  change({ kind: 'message', chat_id: data.chatId, job_id: 81 });
  assert.ok(replyBubble.findText('Hello back'), 'final event keeps text while history loads');
  data.messages.push({ id: 102, role: 'assistant', agent_id: 'writer', text: 'Hello back!', job_id: 81 }); app.reconcileMessages();
  assert.ok(list.children.includes(replyBubble), 'authoritative reply replaces streaming content in place');
  assert.ok(replyBubble.findText('Hello back!'));
  const react = replyBubble.querySelectorAll('button').find((button) => button['aria-label'] === 'React'); react.click();
  assert.ok(replyBubble.classList.contains('message-menu-open'), 'final reply controls target the mounted bubble');
  change({ kind: 'delta', chat_id: data.chatId, job_id: 81, text: 'Late' });
  assert.equal(list.querySelectorAll('.streaming-message').length, 0, 'late deltas cannot resurrect a finished reply');

  data.agents.push({id:'critic',name:'Critic'});
  change({kind:'status',status:'working',job_id:81,chat_id:data.chatId,agent_id:'critic'});
  change({kind:'delta',job_id:81,chat_id:data.chatId,agent_id:'critic',text:'A second opinion'});
  const handoffBubble = list.querySelector('.streaming-message');
  app.reconcileMessages();
  assert.equal(list.querySelector('.streaming-message'), handoffBubble, 'prior saved reply cannot consume a new handoff with the same job ID');
  assert.ok(handoffBubble.findText('Critic'));
  change({kind:'message',job_id:81,chat_id:data.chatId,message_id:104});
  data.messages.push({id:104,role:'assistant',agent_id:'critic',text:'A second opinion.',job_id:81});app.reconcileMessages();
  assert.ok(handoffBubble.findText('A second opinion.'));assert.ok(list.children.includes(replyBubble));

  data.chatReady = null; data.statuses = []; input.value = 'Try once'; let retryBody;
  context.fetch = async (url, options = {}) => { if (url === '/api/message') { retryBody = JSON.parse(options.body); throw new Error('Connection lost'); } return response({}); };
  await app.sendMessage(submit);
  const failed = list.children.find((node) => node.findText('Try once')), failedMessage = data.messages.find((message) => message.text === 'Try once'), originalId = retryBody.request_id;
  assert.ok(failed.findText('Not delivered · Retry'));
  assert.equal(input.value, ''); input.value = 'Keep my newer draft';
  context.fetch = async (url, options = {}) => {
    if (url === '/api/message') { retryBody = JSON.parse(options.body); return response({ message_id: 103, request_id: originalId, job_ids: [] }); }
    if (url.startsWith('/api/chat?')) return response({ messages: [...data.messages.filter((message) => message !== failedMessage), { id: 103, role: 'user', text: 'Try once', chat_id: data.chatId, request_id: originalId }] });
    return response({});
  };
  await failed.querySelector('.delivery-retry').click();
  assert.equal(retryBody.request_id, originalId, 'Retry reuses the deduplication key');
  assert.equal(retryBody.text, 'Try once'); assert.equal(input.value, 'Keep my newer draft');
  assert.ok(list.children.includes(failed)); assert.ok(!failed.findText('Not delivered'));
  assert.equal(data.messages.filter((message) => message.request_id === originalId).length, 1);

  let rejectAcknowledgment, uncertainBody;
  input.value='Accepted despite lost response';
  context.fetch=async(url,options={})=>url==='/api/message'?new Promise((resolve,reject)=>{uncertainBody=JSON.parse(options.body);rejectAcknowledgment=reject;}):response({});
  const uncertainSend=app.sendMessage(submit);
  change({kind:'seen',chat_id:data.chatId,request_id:uncertainBody.request_id,message_id:105,job_id:82});
  rejectAcknowledgment(new Error('POST response lost'));await uncertainSend;
  const accepted=data.messages.find((message)=>message.request_id===uncertainBody.request_id);
  assert.equal(accepted.delivery,'sent','agent-start event proves delivery when the HTTP acknowledgment is lost');
  assert.ok(list.children.find((node)=>node.dataset.requestId===accepted.request_id).querySelector('.message-ack').findText('Seen'));

  data.chatId=null;data.chatReady=null;input.value='First message from the empty screen';let releaseFirstHistory,firstHistory=true,firstPosts=0;
  context.fetch=async(url,options={})=>{
    if(url.startsWith('/api/chat?') && firstHistory){firstHistory=false;return new Promise((resolve)=>{releaseFirstHistory=resolve;});}
    if(url==='/api/message'){firstPosts++;const body=JSON.parse(options.body);return response({message_id:106,request_id:body.request_id,job_ids:[]});}
    return response({messages:[]});
  };
  const firstFromEmpty=app.sendMessage(submit);
  assert.equal(firstPosts,0);assert.equal(input.value,'');
  assert.ok(list.findText('First message from the empty screen'),'first-chat send is optimistic before history loads');
  releaseFirstHistory(response({messages:[]}));await firstFromEmpty;assert.equal(firstPosts,1);

  const archive = new Node('button'); archive.textContent = 'Archive';
  assert.equal(app.inlineAction(archive, 'Confirm archive?'), false);
  const expiry = timers.findLast((timer) => timer.ms === 4000 && !timer.cancelled); expiry.callback();
  assert.equal(archive.textContent, 'Archive', 'inline confirmation expires after four seconds');
  assert.equal(app.inlineAction(archive, 'Confirm archive?'), false); assert.equal(app.inlineAction(archive, 'Confirm archive?'), true);
  const editing = app.appActionDialog({ title: 'Edit draft', value: 'Old draft', accept: 'Save draft' });
  const dialog = app.sendFeel.dialog; assert.ok(dialog.open);
  dialog.querySelector('textarea').value = 'New draft'; dialog.querySelector('form').events.submit(submit);
  assert.equal(await editing, 'New draft'); assert.equal(app.sendFeel.dialog, null);
  const skipping = app.appActionDialog({title:'Skip draft?',value:'',optional:true}); app.sendFeel.dialog.events.cancel(submit);
  assert.equal(await skipping, null, 'Escape cancels app-owned input without a side effect');

  const calls = []; data.authenticated = false;
  context.fetch = async (url, options = {}) => { calls.push({url, body:options.body && JSON.parse(options.body)}); return response(url === '/api/state' ? { agents: [], chats: [], statuses: [] } : {}); };
  app.showCreatedToast({ card: {proposal:{name:'Note Tidier'}}, result: {agent:{id:'note-tidier',name:'Note Tidier'}} });
  assert.ok(elements.get('toast').findText('Created Note Tidier · Undo'));
  assert.equal(timers.findLast((timer) => !timer.cancelled).ms, 6000);
  await elements.get('toast').querySelector('.toast-undo').click();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find((call) => call.url === '/api/archive').body)), {kind:'agent',id:'note-tidier'});
  app.showLogin();assert.equal(app.sendFeel.optimistic.size,0);assert.equal(app.sendFeel.receipts.size,0);
  assert.ok(elements.get('toast').hidden);assert.equal(elements.get('toast').textContent,'','sign-out removes pending messages and Undo actions from the local view');
  console.log('Message feel smoke checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
