'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.hidden = false; this.disabled = false; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  set innerHTML(value) { throw new Error('Unsafe HTML assignment'); }
  append(...items) { items.forEach((item)=>{item.parent=this;this.children.push(item);}); }
  after(item) { if (!this.parent) return; const at=this.parent.children.indexOf(this);this.parent.children.splice(at+1,0,item);item.parent=this.parent; }
  replaceChildren(...items) { this.children = []; this._text = ''; this.append(...items); }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute(name, value) { this[name] = value; }
  querySelectorAll(selector) { return this.children.flatMap(x => [x, ...x.querySelectorAll('*')]).filter(x => selector === '*' || selector.split(',').includes(x.tagName)); }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const body = new Element('body'); const scan = new Element('button'); scan.id = 'scanComputer'; body.append(scan);
const document = { body, createElement: tag => new Element(tag), getElementById: id => body.querySelectorAll('*').find(x => x.id === id), querySelector: selector => body.querySelectorAll('*').find(x => x.className?.split(' ').includes(selector.slice(1))), querySelectorAll: () => [] };
const calls = []; let info = { status: null, sources: [{id:'claude', label:'Claude Code', details:'Only named files'}, {id:'code',label:'Code folders',details:'Names and README excerpts'}] };
const suggestions = ['motion-architect','Reviewer','Researcher','Writer'].map(name => ({name,emoji:'🤖',title:name,role:'Help with useful work',engine:'claude',model:'haiku',project_folder:null,why:'A useful role'}));
let failCreate = true;
const window = { HubApp: {
  api: async url => { calls.push({url}); return info; },
  post: async (url, request) => {
    calls.push({url,request});
    if(url.endsWith('/preview')) return {summary:'<img src=x onerror=alert(1)>\nSafe inventory',token:'reviewed-token',findings:1};
    if(url.endsWith('/suggest')) return {suggestions,group:{name:'Helpers',agents:['Builder','Reviewer']},team:{name:'Code review',agents:['Builder','Reviewer']}};
    if(url.endsWith('/create')) { if(failCreate) { failCreate = false; throw new Error('Temporary failure'); } return {agents:[{id:'edited'}],status:'done'}; }
    return {status:'skipped'};
  }, refreshState: async () => {}, openChat: async id => { calls.push({open:id}); }, showToast: message => { calls.push({toast:message}); }
}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/onboarding.js'),'utf8'), {window,document});
const findButton = text => body.querySelectorAll('button').find(x => x.textContent === text);
(async () => {
  await window.HubOnboarding.refreshScanLabel();
  assert.equal(scan.textContent, 'Scan this computer');
  info.status='skipped'; await window.HubOnboarding.refreshScanLabel();
  assert.equal(scan.textContent, 'Scan this computer', 'skipping does not claim a previous scan');
  info.scanned=true; await window.HubOnboarding.refreshScanLabel();
  assert.equal(scan.textContent, 'Scan this computer again');
  info.scanned=false; info.status='done'; await window.HubOnboarding.refreshScanLabel();
  assert.equal(scan.textContent, 'Scan this computer again', 'existing completed setups remain recognized');
  info.status=null; calls.length=0;
  assert.equal(await window.HubOnboarding.offer(false), false); assert.equal(calls.length,0);
  assert.equal(await window.HubOnboarding.offer(true), true);
  const index = fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
  assert.match(index, /id="messageList"[^>]*role="log"/, 'the actual page has a message mount');
  const messageList = new Element('div'); messageList.id='messageList'; body.append(messageList);
  const greeting = new Element('div'); greeting.className='guide-starters'; messageList.append(greeting);
  window.HubOnboarding.mountOffer(); window.HubOnboarding.mountOffer();
  assert.equal(messageList.children.length,2,'first-run card mounts immediately after the existing Guide greeting, once');
  assert.equal(messageList.children[1].className,'card scan-offer');
  const offer = window.HubOnboarding.offerCard(); assert.ok(offer.textContent.includes('Find Pips for your work'));
  assert.equal(calls.filter(x=>x.request).length,0,'first-login card never scans or calls a model');
  await offer.querySelectorAll('button').find(x=>x.textContent==='Scan this computer').events.click();
  const dialog = document.getElementById('scanDialog'); assert.ok(dialog.open);
  const checks = body.querySelectorAll('input').filter(x=>x.type==='checkbox'); assert.ok(checks.every(x=>x.checked)); checks[1].checked=false;
  await findButton('Scan').events.click();
  assert.equal(scan.textContent,'Scan this computer again','successful local scan updates Settings immediately');
  assert.deepEqual(Array.from(calls.at(-1).request.sources),['claude']);
  assert.ok(dialog.textContent.includes('<img src=x onerror=alert(1)>'),'preview uses literal text');
  assert.equal(calls.filter(x=>x.url.endsWith('/suggest')).length,0,'model requires second explicit click');
  await findButton('Suggest Pips').events.click(); assert.equal(calls.at(-1).request.token,'reviewed-token');
  assert.ok(dialog.textContent.includes('Motion Architect'));
  assert.ok(dialog.textContent.includes('Claude · haiku'));
  assert.ok(dialog.textContent.includes('Help with useful work'));
  const selected = body.querySelectorAll('input').filter(x=>x.type==='checkbox');
  assert.deepEqual(selected.slice(0,8).map(x=>x.checked),[true,false,true,false,true,false,false,false],'top three selected; globals always off');
  const names = body.querySelectorAll('input').filter(x=>x['aria-label']==='Pip name'); names[0].value='Edited';
  await findButton('Create selected').events.click(); assert.ok(dialog.textContent.includes('Temporary failure'));
  assert.equal(findButton('Create selected').disabled,false,'failed creation can retry without losing selections');
  await findButton('Create selected').events.click();
  const create = calls.filter(x=>x.url?.endsWith('/create')).at(-1).request;
  assert.equal(create.token,'reviewed-token'); assert.equal(create.suggestions.length,3); assert.equal(create.suggestions[0].original_name,'motion-architect'); assert.equal(create.suggestions[0].name,'Edited');
  assert.ok(create.suggestions.every(x=>!x.use_global_rules)); assert.equal(create.group,null);
  assert.ok(findButton('Set up suggested team task'),'team is offered without launching any work');
  await findButton('Open my helpers').events.click(); assert.equal(dialog.open,false); assert.equal(calls.at(-1).open,'agent:edited');
  assert.equal(await window.HubOnboarding.offer(true),false,'automatic offer only once this page');
  await window.HubOnboarding.open();
  const beforeEscape = calls.length;
  await dialog.events.cancel({preventDefault(){}});
  assert.equal(dialog.open,false);
  assert.equal(calls.length,beforeEscape,'Escape closes a manual rescan without changing status');
  await window.HubOnboarding.open(); await dialog.querySelectorAll('button').find(x=>x.textContent==='Skip').events.click(); assert.equal(calls.at(-1).url,'/api/onboarding/skip'); assert.equal(dialog.open,false);
  console.log('Onboarding UI smoke checks passed');
})().catch(error=>{ console.error(error); process.exitCode=1; });
