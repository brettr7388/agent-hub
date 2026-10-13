/* Offline input, live ordering, stream identity, toast, and avatar regressions. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, document, elements, timers, Node };', fixture);
const { context, document, elements, Node } = fixture.fixture;
const app = context.__test, data = app.data;
const list = elements.get('messageList'), input = elements.get('messageInput'), composer = elements.get('composer');
const response = (value) => ({ ok: true, status: 200, json: async () => value });
const submit = { preventDefault() {} };
const ids = () => Array.from(list.children.filter((node) => node.dataset.messageId), (node) => node.dataset.messageId);
const native = () => { throw new Error('Native dialog invoked'); };
for (const name of ['alert','confirm','prompt']) context[name] = context.window[name] = native;
data.authenticated = true; data.chatId = 'agent:ada'; data.guideOpened = true;
data.agents = [{id:'ada',name:'Ada',pip_style:{palette:'teal',accessory:'pencil'}}];
data.chats = [{id:data.chatId,type:'direct',agents:['ada'],name:'Ada'}];

(async () => {
  // F2: another client's jobs can arrive before its message history. Saved ids
  // determine server order even when a stream is already mounted in the middle.
  data.messages = [{id:6,role:'user',text:'Original',created:90}]; app.reconcileMessages();
  const original = list.children[0];
  data.deltas.set('90',{chat_id:data.chatId,agent_id:'ada',text:'Answer streaming'}); app.renderDeltas();
  const stream = list.querySelector('.streaming-message');
  data.messages = [
    {id:10,role:'user',text:'Remote second',created:100},
    {id:6,role:'user',text:'Original',created:90},
    {id:9,role:'user',text:'Remote first',created:100},
    {id:7,role:'assistant',agent_id:'ada',text:'Earlier answer',created:99}
  ]; app.reconcileMessages();
  assert.deepEqual(ids(), ['6','7','9','10'], 'remote bubbles insert by server id, before existing placeholders');
  assert.equal(list.children[0], original, 'reordering retains mounted bubble identity');
  assert.ok(list.children.includes(stream));
  data.messages.push({id:11,role:'assistant',agent_id:'ada',text:'Answer streaming',created:100,job_id:90});
  app.reconcileMessages();
  assert.deepEqual(ids(), ['6','7','9','10','11']);
  assert.equal(list.children.at(-1), stream, 'final answer consumes the existing stream in its ordered slot');
  assert.ok(stream.classList.contains('stream-final'), 'stream completion suppresses entry animation');
  app.reconcileMessages(); assert.ok(stream.classList.contains('stream-final'), 'history refresh keeps completion unanimated');
  const merged = app.mergeSentMessages([
    {id:3,created:5},{id:2,created:5},{id:1,created:500}
  ],data.chatId);
  assert.deepEqual(Array.from(merged, (m)=>m.id), [1,2,3], 'persisted ids win over equal timestamps and clock changes');
  data.messages = [{id:'local-b',created:30,role:'user',text:'B'},{id:'local-a',created:20,role:'user',text:'A'}];
  app.reconcileMessages(); assert.deepEqual(ids(),['local-a','local-b'],'unsaved messages fall back to created order');

  // F3: exercise the actual Enter binding, with an active job and delayed POST.
  list.replaceChildren(); data.messages=[]; data.deltas.clear(); data.closedDeltas.clear();
  data.statuses = [{id:40,chat_id:data.chatId,agent_id:'ada',status:'working'}];
  data.deltas.set('40',{chat_id:data.chatId,agent_id:'ada',text:'Still answering'}); app.renderDeltas();
  const currentTurn = list.querySelector('.streaming-message');
  app.setupComposerInteractions();
  let sending, body, stopCalls=0, submitCount=0;
  const posts=[], releases=[], saved=[];
  composer.requestSubmit = () => { submitCount++; sending = composer.events.submit(submit); };
  context.fetch = async (url, options={}) => {
    if (url === '/api/message') {
      body=JSON.parse(options.body); const sent=body, id=20+posts.length; posts.push(sent);
      return new Promise((resolve)=>{releases.push(()=>{ saved.push({id,role:'user',text:sent.text,chat_id:sent.chat_id,request_id:sent.request_id,acknowledged:false,created:100}); resolve(response({message_id:id,job_id:41+id-20,job_ids:[41+id-20]})); });});
    }
    if (url === '/api/jobs/stop') { stopCalls++; return response({}); }
    if (url.startsWith('/api/chat?')) return response({messages:saved.slice()});
    if (url === '/api/state') return response({agents:data.agents,chats:data.chats,statuses:[]});
    return response({});
  };
  input.value='Queue this after the answer'; let prevented=false;
  input.events.keydown({key:'Enter',shiftKey:false,isComposing:false,preventDefault(){prevented=true;}});
  assert.ok(prevented); assert.equal(submitCount,1); assert.equal(stopCalls,0);
  assert.equal(body.text,'Queue this after the answer'); assert.equal(input.value,'');
  const queuedBubble=list.children.find((node)=>node.classList.contains('user'));
  assert.ok(queuedBubble.findText(body.text),'queued send is visible before the POST resolves');
  assert.ok(list.children.includes(currentTurn) && currentTurn.findText('Still answering'),'Enter preserves the active stream');
  const firstSend=sending;
  input.value='Send again before the first POST returns';
  input.events.keydown({key:'Enter',preventDefault(){}});
  const secondSend=sending;
  assert.equal(input.value,'');
  assert.ok(list.findText('Send again before the first POST returns'),'rapid second Enter is also immediately visible');
  assert.equal(posts.length,1,'POSTs preserve send order while responses are delayed');
  assert.equal(elements.get('sendButton').disabled,false,'a pending delivery does not disable Send');
  app.connectEvents();
  const change=(value)=>data.eventSource.listeners.change({data:JSON.stringify(value)});
  const secondPending=Array.from(app.sendFeel.optimistic.values()).find((m)=>m.text.startsWith('Send again'));
  const secondPlaceholder=list.children.find((n)=>n.dataset.jobId===`request:${secondPending.request_id}`);
  change({kind:'status',status:'queued',chat_id:data.chatId,job_id:98,agent_id:'ada',request_id:'another-device-request'});
  assert.equal(secondPlaceholder.dataset.jobId,`request:${secondPending.request_id}`,'another device cannot claim a local send placeholder');
  change({kind:'status',status:'queued',chat_id:data.chatId,job_id:41,agent_id:'ada',request_id:posts[0].request_id});
  assert.equal(secondPlaceholder.dataset.jobId,`request:${secondPending.request_id}`,'each queued event claims only its matching request');
  releases[0](); await firstSend; await new Promise(setImmediate);
  assert.equal(posts.length,2); assert.equal(posts[1].text,secondPending.text);
  releases[1](); await secondSend;
  input.value=posts[0].text;
  input.events.keydown({key:'Enter',preventDefault(){}});
  assert.equal(posts.length,3);
  assert.notEqual(posts[2].request_id,posts[0].request_id,'intentional repeated text gets a new delivery id');
  releases[2](); await sending;
  assert.equal(queuedBubble.querySelector('.message-ack').textContent,'Sent','queued message stays Sent until its job launches');
  assert.equal(elements.get('sendButton')['aria-label'],'Send message');
  assert.equal(elements.get('stopButton').hidden,false);
  input.events.keydown({key:'Enter',preventDefault(){}}); await sending;
  assert.equal(stopCalls,0,'empty Enter never stops an active response');
  input.value='Keep this draft';
  input.events.keydown({key:'Enter',shiftKey:true,preventDefault(){throw new Error('Shift+Enter was intercepted');}});
  input.events.keydown({key:'Enter',isComposing:true,preventDefault(){throw new Error('IME Enter was intercepted');}});
  assert.equal(submitCount,4,'newline and IME confirmation do not submit');
  await elements.get('stopButton').click();
  assert.equal(stopCalls,1,'only the explicit Stop button stops the job');
  assert.equal(input.value,'Keep this draft','Stop preserves the composer draft');
  assert.equal(elements.get('stopButton').hidden,true);

  // F4: direct-chat placeholder follows the selected Pip; groups and home reset.
  app.renderHeader(); assert.equal(input.placeholder,'Message Ada…');
  data.agents[0].name='Ada Renamed'; app.renderHeader(); assert.equal(input.placeholder,'Message Ada Renamed…');
  data.chats.push({id:'group:friends',type:'group',name:'Friends',agents:['ada']});
  data.chatId='group:friends'; app.renderHeader(); assert.equal(input.placeholder,'Ask anything…');
  data.chatId=null; app.renderHeader(); assert.equal(input.placeholder,'Ask anything…');
  data.chatId='agent:ada'; app.renderHeader();

  // Undo stays 12px above the composer across a taller draft and viewport resize.
  composer.hidden=false; composer.rect={top:730,bottom:885};
  app.showCreatedToast({result:{agent:{id:'nova',name:'Nova'}}});
  const toast=elements.get('toast');
  assert.equal(toast.style.bottom,'182px');
  assert.ok(900-parseFloat(toast.style.bottom) < composer.rect.top,'toast lower edge is above composer');
  composer.rect.top=640; app.resizeComposer(); assert.equal(toast.style.bottom,'272px','draft growth moves the toast');
  context.window.innerHeight=844; app.positionToast(); assert.equal(toast.style.bottom,'216px','viewport resize recomputes clearance');

  // Pending and created proposal cards both use the persisted style, or created
  // result for historical cards whose preview predated persisted styles.
  const p={action:'create_agent',name:'Nova',instructions:'Write clearly',emoji:'✍️',avatar_style:'pip',pip_style:{palette:'charcoal',accessory:'pencil',eyes:'happy'}};
  const card={kind:'proposal',index:0,status:'pending',proposal:p};
  let preview=app.proposalCard(card,{id:30});
  assert.equal(preview.querySelector('svg').source,context.window.Pips.avatarHTML({...p,id:'nova'}));
  const created={id:'nova',name:'Nova',avatar_style:'pip',pip_style:{palette:'coral',accessory:'calendar'}};
  preview=app.proposalCard({...card,status:'created',result:{agent:created}},{id:30});
  assert.equal(preview.querySelector('svg').source,context.window.Pips.avatarHTML(created),'created card matches actual sidebar Pip even for legacy previews');
  preview=app.proposalCard({...card,proposal:{...p,avatar_style:'emoji'}},{id:30});
  assert.ok(preview.querySelector('.avatar').findText('✍️')); assert.equal(preview.querySelector('svg'),null);

  // A hung POST from the previous login cannot block or replay sends in a new
  // login, even when the owner reopens the same conversation.
  const beforeAgents=data.agents, beforeChats=data.chats, loginPosts=[], loginReleases=[];
  context.fetch=async(url,options={})=> {
    if(url==='/api/message') { const payload=JSON.parse(options.body); loginPosts.push(payload); return new Promise((resolve)=>loginReleases.push(()=>resolve(response({message_id:80+loginPosts.length,job_ids:[]})))); }
    return response({messages:[]});
  };
  input.value='Old login in-flight'; const oldSend=app.sendMessage(submit);
  input.value='Old login waiting'; const oldWaiting=app.sendMessage(submit);
  assert.equal(loginPosts.length,1);
  app.showLogin();
  data.authenticated=true; data.agents=beforeAgents; data.chats=beforeChats; data.chatId='agent:ada';
  input.value='New login message'; const newSend=app.sendMessage(submit);
  assert.equal(loginPosts.length,2,'new login sends without waiting for the old hung POST');
  loginReleases[1](); await newSend;
  loginReleases[0](); await oldSend; await oldWaiting;
  assert.equal(loginPosts.length,2,'old queued sends do not replay in the new login');
  assert.ok(!list.findText('Old login'),'old response cannot resurrect the cleared conversation');
  console.log('Messaging queue smoke checks passed');
})().catch((error)=>{console.error(error);process.exitCode=1;});
