import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const core = process.env.PI_PACKAGE_ROOT || resolve(dirname(process.execPath), '../lib/node_modules/@earendil-works/pi-coding-agent');
const req = createRequire(`${core}/package.json`);
const { createJiti } = req('jiti');
const jiti = createJiti(import.meta.url, {
  fsCache: false, moduleCache: true,
  alias: {
    '@earendil-works/pi-coding-agent': `${core}/dist/index.js`,
    '@earendil-works/pi-tui': req.resolve('@earendil-works/pi-tui'),
    '@earendil-works/pi-ai': `${core}/node_modules/@earendil-works/pi-ai/dist/index.js`,
  },
});
const { buildCleanTurns, textPhase } = await jiti.import(`${root}/model.ts`);
const { CleanHistoryView, displayText } = await jiti.import(`${root}/view.ts`);
const { default: install } = await jiti.import(`${root}/index.ts`);
const { SessionManager } = await import(`${core}/dist/core/session-manager.js`);
const { loadExtensions } = await import(`${core}/dist/core/extensions/loader.js`);
const { initTheme } = await import(`${core}/dist/modes/interactive/theme/theme.js`);
const tuiPackage = await import(req.resolve('@earendil-works/pi-tui'));
initTheme('dark', false);
const { theme } = await import(`${core}/dist/modes/interactive/theme/theme.js`);
let counter = 0;
const text = (value, phase) => ({ type: 'text', text: value, ...(phase ? { textSignature: JSON.stringify({v:1,id:'msg_example',phase}) } : {}) });
const tool = { type:'toolCall', id:'tool1', name:'read', arguments:{path:'private'} };
const thinking = { type:'thinking', thinking:'HIDDEN_REASONING' };
const message = (role, content, stopReason) => ({
  type:'message', id:`e${++counter}`, parentId:null, timestamp:'2026-09-09T00:00:00Z',
  message:{role,content,...(stopReason ? {stopReason}:{}),timestamp:1},
});
const user = value => message('user',value);
const assistant = (value, stop='stop') => message('assistant',typeof value === 'string' ? [text(value)] : value,stop);
const notification = {type:'custom_message',id:'notify',customType:'background-task-notification',content:'NOTIFICATION_SECRET',display:true};
const results = message('toolResult',[text('TOOL_OUTPUT_SECRET')]);
const freeze = value => { if(value && typeof value==='object'){Object.freeze(value); for(const child of Object.values(value))freeze(child);}return value; };

function fixture(mode='tui', entries=[]) {
  const handlers=new Map(),commands=new Map(),notices=[];
  let renderCount=0,reads=0, resolveOpen, view;
  const terminal={rows:18,columns:80};
  const tui={terminal,requestRender(){renderCount++;}};
  const ctx={
    mode,hasUI:mode==='tui'||mode==='rpc',running:false,
    isIdle(){return !this.running;},
    sessionManager:{getBranch(){reads++;return entries;}},
    ui:{notify(...args){notices.push(args);},
      custom(factory, options){
        assert.equal(options.overlay,true);
        return new Promise(resolve=>{
          resolveOpen=()=>{view?.dispose();resolve();};
          view=factory(tui,theme,{},resolveOpen);
        });
      },
    },
  };
  install({on(name,handler){handlers.set(name,handler);},registerCommand(name,command){commands.set(name,command);}});
  return {ctx,handlers,commands,notices,tui,entries,
    open(args=''){return commands.get('answers').handler(args,ctx);},
    get view(){return view;},get reads(){return reads;},get renderCount(){return renderCount;},
    close(){resolveOpen?.();},
  };
}
const plain = rows => rows.map(tuiPackage.stripTerminalSequences).join('\n');

// Projection and semantics.
test('groups each prompt with its LAST reply before the next prompt',()=>{
  const first=user('First question'), last=assistant('Actual answer');
  const turns=buildCleanTurns([first,assistant('Starting...'),notification,assistant([text('Reading'),tool],'toolUse'),results,last,user('Second question'),assistant('Second answer')]);
  assert.equal(turns.length,2);assert.equal(turns[0].reply,'Actual answer');assert.equal(turns[0].replyId,last.id);
  assert.equal(turns[0].hiddenReplies,2);assert.equal(turns[1].reply,'Second answer');
});
test('Codex commentary and final blocks in ONE message are filtered individually',()=>{
  const turns=buildCleanTurns([user('Question'),assistant([thinking,text('COMMENTARY','commentary'),text('Final part one','final_answer'),text('Final part two','final_answer')])]);
  assert.equal(turns[0].reply,'Final part one\n\nFinal part two');assert.equal(turns[0].status,'complete');
});
test('K3 and untagged providers use normal completion, not text style',()=>{
  const turns=buildCleanTurns([user('Question'),assistant([thinking,text('I finished!'),tool],'toolUse'),results,assistant([thinking,text('Plain K3 answer')])]);
  assert.equal(turns[0].reply,'Plain K3 answer');assert.equal(turns[0].status,'complete');
});
test('opaque, malformed, unknown-version and future signatures preserve readable text',()=>{
  for(const signature of ['msg_legacy','{broken','{"v":2,"phase":"commentary"}','{"v":1,"phase":"future"}','null']){
    const block={...text('Legacy answer'),textSignature:signature};
    assert.equal(textPhase(block),undefined);
    assert.equal(buildCleanTurns([user('Q'),assistant([block])])[0].reply,'Legacy answer');
  }
});
test('explicit commentary-only stop remains visibly incomplete',()=>{
  const turn=buildCleanTurns([user('Q'),assistant([text('Only an update','commentary')])])[0];
  assert.equal(turn.status,'incomplete');assert.equal(turn.replyKind,'partial');assert.equal(turn.reply,'Only an update');
});
test('toolUse text cannot overwrite a completed reply as another final',()=>{
  const turn=buildCleanTurns([user('Q'),assistant('Earlier answer'),notification,assistant([text('Continuing...'),tool],'toolUse')])[0];
  assert.equal(turn.reply,'Earlier answer');assert.equal(turn.replyKind,'previous');assert.equal(turn.status,'incomplete');
});
test('incomplete tool-only response does not expose thinking or tool arguments/results',()=>{
  const turn=buildCleanTurns([user('Q'),assistant([thinking,tool],'toolUse'),results])[0];
  assert.equal(turn.reply,undefined);assert.equal(turn.status,'incomplete');
});
for(const [reason,status] of [['aborted','aborted'],['error','error'],['length','truncated']]){
  test(`${reason}: partial text is retained without being labelled complete`,()=>{
    const turn=buildCleanTurns([user('Q'),assistant('Older answer'),assistant([thinking,text('Partial output')],reason)])[0];
    assert.equal(turn.reply,'Partial output');assert.equal(turn.replyKind,'partial');assert.equal(turn.status,status);
  });
  test(`${reason}: an empty failed attempt labels the old reply as earlier`,()=>{
    const turn=buildCleanTurns([user('Q'),assistant('Older answer'),assistant([],reason)])[0];
    assert.equal(turn.reply,'Older answer');assert.equal(turn.replyKind,'previous');assert.equal(turn.status,status);
  });
}
test('successful retry replaces both the failed partial and status',()=>{
  const turn=buildCleanTurns([user('Q'),assistant('Partial','error'),assistant('Recovered')])[0];
  assert.equal(turn.reply,'Recovered');assert.equal(turn.status,'complete');
});
test('consecutive prompts, empty prompts and the open last prompt remain visible',()=>{
  const turns=buildCleanTurns([user(''),user('Steering'),user('Latest')]);
  assert.equal(turns.length,3);assert.equal(turns[0].prompt,'[Empty user message]');
  assert.ok(turns.every(t=>t.status==='waiting'));
});
test('images are represented without exposing base64 blobs',()=>{
  const turns=buildCleanTurns([user([{type:'image',data:'BASE64_SECRET',mimeType:'image/png'}]),assistant('Image answer')]);
  assert.equal(turns[0].prompt,'[1 image attached]');assert.ok(!JSON.stringify(turns).includes('BASE64_SECRET'));
});
test('custom notifications never split turns; user-typed lookalikes still do',()=>{
  const turns=buildCleanTurns([user('Q'),assistant('Waiting'),notification,assistant('Done'),user('<background-task-notification> this is my question')]);
  assert.equal(turns.length,2);assert.equal(turns[0].reply,'Done');
});
test('no orphan assistant is falsely attributed to the first later user',()=>{
  const turns=buildCleanTurns([assistant('Orphan'),user('New prompt')]);
  assert.equal(turns.length,1);assert.equal(turns[0].reply,undefined);
});
test('normal compaction retains original ancestry, without duplicating retainedTail',()=>{
  const a=user('Before compaction'),b=assistant('Original answer');
  const turns=buildCleanTurns([a,b,{type:'compaction',id:'compact',retainedTail:[a.message,b.message]},user('After compaction'),assistant('New answer')]);
  assert.equal(turns.length,2);assert.equal(turns[0].reply,'Original answer');
});
test('actual SessionManager active branch excludes siblings, then updates after navigation',()=>{
  const sm=SessionManager.inMemory('/tmp/clean-history-test');
  const u=sm.appendMessage(user('Q').message);
  const a=sm.appendMessage(assistant('Branch A').message);
  sm.branch(u);sm.appendMessage(assistant('Branch B').message);
  assert.equal(buildCleanTurns(sm.getBranch())[0].reply,'Branch B');
  sm.branch(a);assert.equal(buildCleanTurns(sm.getBranch())[0].reply,'Branch A');
});
test('projection never mutates persisted entries and preserves message text',()=>{
  const entries=freeze([user('Q\n\n```c\nx();\n```'),assistant([thinking,text('A\n\n```rs\nfn main() {}\n```','final_answer')])]);
  const before=JSON.stringify(entries);buildCleanTurns(entries);assert.equal(JSON.stringify(entries),before);
});
test('pending, empty and unexpected stops are not success',()=>{
  for(const reason of ['pending','future']) assert.equal(buildCleanTurns([user('Q'),assistant('Not final',reason)])[0].status,'incomplete');
  assert.equal(buildCleanTurns([user('Q'),assistant([thinking])])[0].status,'incomplete');
});
test('legacy no-stopReason text is retained; no-stopReason tool calls are not finals',()=>{
  assert.equal(buildCleanTurns([user('Q'),assistant('Legacy',null)])[0].status,'complete');
  assert.equal(buildCleanTurns([user('Q'),assistant([text('Legacy update'),tool],null)])[0].status,'incomplete');
});

// Rendering and control: real Markdown, no actual terminal/agent/network.
test('native Pi extension loader loads it without tools, providers or context-mutating hooks',async()=>{
  const loaded=await loadExtensions([`${root}/index.ts`],process.cwd());
  assert.deepEqual(loaded.errors,[]);assert.equal(loaded.extensions.length,1);
  const ext=loaded.extensions[0];assert.equal(ext.tools.size,0);assert.equal(ext.shortcuts.size,0);
  assert.deepEqual([...ext.commands.keys()],['answers']);
  assert.ok(!ext.handlers.has('context'));assert.ok(!ext.handlers.has('input'));assert.ok(!ext.handlers.has('before_provider_request'));
});
for(const mode of ['rpc','print','json']) test(`${mode}: command never opens terminal UI or generates output`,async()=>{
  const f=fixture(mode);await f.open();assert.equal(f.view,undefined);assert.equal(f.reads,0);
});
test('invalid arguments do not open an overlay',async()=>{
  const f=fixture();await f.open('unexpected');assert.equal(f.view,undefined);assert.equal(f.notices.length,1);
});
test('wide/narrow Unicode, long code, huge answers and tiny terminals stay in bounds',()=>{
  const f=fixture();const view=new CleanHistoryView(f.tui,theme,()=>{});
  view.update(buildCleanTurns([user('中文 👨‍👩‍👧‍👦 query'),assistant('```text\n'+'long'.repeat(100)+'\n```\n'+'response '.repeat(3000))]),false);
  for(const rows of [1,2,3,10,24]) for(const width of [1,2,5,20,80,150]){
    f.tui.terminal.rows=rows;const lines=view.render(width);
    assert.equal(lines.length,rows);assert.ok(lines.every(line=>tuiPackage.visibleWidth(line)<=width),`${rows}x${width}`);
  }
  assert.deepEqual(view.render(0),[]);view.dispose();assert.deepEqual(view.render(80),[]);
});
test('scrolling, paging, prompt jumps, refresh and follow-bottom behavior',()=>{
  const f=fixture();f.tui.terminal.rows=8;const view=new CleanHistoryView(f.tui,theme,()=>{});
  const entries=[user('FIRST_PROMPT'),assistant('first\n'.repeat(20)),user('SECOND_PROMPT'),assistant('second\n'.repeat(20))];
  view.update(buildCleanTurns(entries),false);assert.match(plain(view.render(80)),/second/);
  view.handleInput('g');assert.match(plain(view.render(80)),/FIRST_PROMPT/);
  view.handleInput(']');assert.match(plain(view.render(80)),/SECOND_PROMPT/);
  view.handleInput('[');assert.match(plain(view.render(80)),/FIRST_PROMPT/);
  entries.push(user('THIRD_PROMPT'),assistant('third\n'.repeat(20)));
  view.update(buildCleanTurns(entries),true);assert.match(plain(view.render(80)),/FIRST_PROMPT/);
  view.handleInput('G');assert.match(plain(view.render(80)),/third/);
  const before=plain(view.render(80));view.handleInput('\x1b[5~');assert.notEqual(plain(view.render(80)),before);
  const result=view.handleMouse({type:'wheel',wheelDelta:-3});assert.equal(result.handled,true);
});
test('d/u and Ctrl+D/Ctrl+U scroll half pages and clamp at either end',()=>{
  const f=fixture();const view=new CleanHistoryView(f.tui,theme,()=>assert.fail('Scroll must not close viewer'));
  view.update(buildCleanTurns([user('Q'),assistant('line\n'.repeat(100))]),false);
  const position=()=>{
    const footer=plain(view.render(200)).split('\n').at(-1);
    const match=footer.match(/(\d+)–\d+\/(\d+)\s*$/);
    assert.ok(match,footer);return {offset:Number(match[1])-1,total:Number(match[2])};
  };
  // With at least one body row, the first visible line identifies the offset.
  for(const rows of [3,4,9,18,19]){
    f.tui.terminal.rows=rows;view.render(200);
    const half=Math.max(1,Math.floor((rows-2)/2));
    for(const [down,up] of [['d','u'],['\x04','\x15']]){
      view.handleInput('g');assert.equal(position().offset,0);
      view.handleInput(up);assert.equal(position().offset,0);
      view.handleInput(down);assert.equal(position().offset,half);
      view.handleInput(down);assert.equal(position().offset,2*half);
      view.handleInput(up);assert.equal(position().offset,half);
      view.handleInput(up);assert.equal(position().offset,0);
      view.handleInput('G');const bottom=position().offset;
      view.handleInput(down);assert.equal(position().offset,bottom);
      view.handleInput(up);assert.equal(position().offset,bottom-half);
      view.handleInput(down);assert.equal(position().offset,bottom);
    }
  }
  // One/two-row terminals have no body: their footer is not an offset oracle.
  for(const rows of [1,2]){
    f.tui.terminal.rows=rows;view.render(80);
    for(const key of ['g','d','u','G','\x04','\x15']){
      view.handleInput(key);const lines=view.render(80);
      assert.equal(lines.length,rows);
      assert.ok(lines.every(line=>tuiPackage.visibleWidth(line)<=80));
    }
  }
  view.dispose();
});
test('half-page steps follow resized viewport while full-page keys remain unchanged',()=>{
  const f=fixture();const view=new CleanHistoryView(f.tui,theme,()=>{});
  view.update(buildCleanTurns([user('Q'),assistant('line\n'.repeat(100))]),false);
  const offset=()=>Number(plain(view.render(200)).match(/(\d+)–\d+\/\d+\s*$/)[1])-1;
  view.render(200);view.handleInput('g');view.handleInput('d');assert.equal(offset(),8);
  f.tui.terminal.rows=10;view.render(200);view.handleInput('d');assert.equal(offset(),12);
  view.handleInput('u');assert.equal(offset(),8);
  for(const down of [' ','\x1b[6~','\x06']){
    view.handleInput('g');view.handleInput(down);assert.equal(offset(),7);
  }
  for(const up of ['\x1b[5~','\x02']){
    view.handleInput('g');view.handleInput('d');view.handleInput('d');view.handleInput(up);assert.equal(offset(),1);
  }
  view.dispose();
});
test('q/Esc/f close without aborting or altering the underlying session',async()=>{
  for(const key of ['q','f','\x1b','\x03']){
    const f=fixture('tui',[user('Q'),assistant('A')]);const opened=f.open();
    const before=JSON.stringify(f.entries);f.view.handleInput(key);await opened;
    assert.equal(JSON.stringify(f.entries),before);assert.deepEqual(f.view.render(80),[]);
  }
});
test('safe boundaries refresh after persistence even with delayed message-end handlers',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture('tui',[user('Q')]);const opened=f.open();f.view.render(80);
  const end=assistant('New reply');f.ctx.running=true;
  assert.equal(f.handlers.has('message_end'),false);
  f.handlers.get('message_start')({message:user('ignored').message},f.ctx);
  t.mock.timers.tick(0);assert.equal(f.reads,1);
  f.handlers.get('message_start')({message:end.message},f.ctx);
  // Other extensions could still be awaiting message_end: a timer alone must
  // neither manufacture completion nor prevent the later durable refresh.
  t.mock.timers.tick(0);assert.equal(f.reads,2);
  assert.doesNotMatch(plain(f.view.render(100)),/New reply/);
  f.entries.push(end);
  f.handlers.get('turn_end')({},f.ctx);
  f.handlers.get('agent_end')({},f.ctx);
  assert.equal(f.reads,2);t.mock.timers.tick(0);
  assert.equal(f.reads,3);assert.match(plain(f.view.render(100)),/New reply/);
  assert.match(plain(f.view.render(120)),/agent working/);
  f.ctx.running=false;f.handlers.get('agent_settled')({},f.ctx);t.mock.timers.tick(0);
  assert.doesNotMatch(plain(f.view.render(120)),/agent working/);
  f.close();await opened;
});
test('closed viewers do not read sessions; shutdown cancels pending refresh and permits reopening',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture('tui',[user('Q')]);f.handlers.get('turn_end')({},f.ctx);t.mock.timers.tick(0);assert.equal(f.reads,0);
  const opened=f.open();f.handlers.get('turn_end')({},f.ctx);f.handlers.get('session_shutdown')({},f.ctx);
  t.mock.timers.tick(0);await opened;assert.equal(f.reads,1);
  const reopened=f.open();assert.equal(f.reads,2);f.close();await reopened;
});
for(const Renderer of [tuiPackage.TuiMainScreen,tuiPackage.TuiAltScreen]) {
  test(`${Renderer.name}: native overlay captures input and restores original editor`,()=>{
    const writes=[],editorKeys=[];
    const terminal={rows:18,columns:80,kittyProtocolActive:false,
      start(input){this.input=input;},stop(){},drainInput:async()=>{},
      write(data){writes.push(data);},moveBy(){},hideCursor(){},showCursor(){},
      clearLine(){},clearFromCursor(){},clearScreen(){},setTitle(){},setProgress(){},
    };
    const tui=new Renderer(terminal);
    const editor={focused:false,render(){return ['RAW_FULL_CHAT'];},invalidate(){},handleInput(data){editorKeys.push(data);}};
    tui.addChild(editor);tui.setFocus(editor);tui.start();
    let overlay;
    const view=new CleanHistoryView(tui,theme,()=>{overlay.hide();view.dispose();});
    try {
      view.update(buildCleanTurns([user('CLEAN_PROMPT'),assistant('CLEAN_REPLY')]),false);
      overlay=tui.showOverlay(view,{width:'100%',maxHeight:'100%',anchor:'top-left',margin:0});
      writes.length=0;tui.renderNow(true);
      assert.equal(tui.getFocusedComponent(),view);
      assert.match(writes.join(''),/CLEAN_REPLY/);assert.doesNotMatch(writes.join(''),/RAW_FULL_CHAT/);
      terminal.input('a');assert.deepEqual(editorKeys,[]);
      terminal.input('q');assert.equal(tui.getFocusedComponent(),editor);
      terminal.input('x');assert.deepEqual(editorKeys,['x']);
      writes.length=0;tui.renderNow(true);assert.match(writes.join(''),/RAW_FULL_CHAT/);
    } finally {overlay?.hide();view.dispose();tui.stop();}
  });
}

test('terminal sequences are display-sanitized, never applied to the source text',()=>{
  const input='hello\x1b[2Jworld\x1b]52;c;YWJj\x07\nnext\tcolumn';
  const output=displayText(input);assert.ok(!output.includes('\x1b'));assert.ok(!output.includes('\x07'));
  assert.match(output,/hello.*world/);assert.match(output,/next\tcolumn/);
});
