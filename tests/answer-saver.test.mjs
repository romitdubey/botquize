import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AnswerSaver} from '../web/answer-saver.mjs';
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('a slow save does not block new selections or a different question',async()=>{
 const first=deferred(),calls=[];
 const saver=new AnswerSaver(async p=>{calls.push(p);if(calls.length===1)await first.promise;return {saved:true}});
 saver.set({index:0,answer:0,flagged:false});await tick();
 saver.set({index:0,answer:2,flagged:true});saver.set({index:1,answer:1,flagged:false});
 assert.equal(saver.pending,2);assert.equal(calls.length,1);
 let finished=false;const flushed=saver.flush().then(result=>{finished=result});await tick();assert.equal(finished,false);
 first.resolve();await flushed;
 assert.equal(finished,true);assert.deepEqual(calls.map(p=>[p.index,p.answer]),[[0,0],[0,2],[1,1]]);
 assert.equal(saver.pending,0);
});

test('waiting responses coalesce to the latest answer and flag state',async()=>{
 const gate=deferred(),calls=[];
 const saver=new AnswerSaver(async p=>{calls.push(p);if(p.index===0)await gate.promise});
 saver.set({index:0,answer:0,flagged:false});await tick();
 saver.set({index:1,answer:0,flagged:false});saver.set({index:1,answer:2,flagged:true});saver.set({index:1,answer:null,flagged:false});
 gate.resolve();assert.equal(await saver.flush(),true);
 assert.deepEqual(calls,[{index:0,answer:0,flagged:false},{index:1,answer:null,flagged:false}]);
});

test('an old failed request cannot revert or discard a newer selection',async()=>{
 const gate=deferred();let calls=0;const saved=[];
 const saver=new AnswerSaver(async p=>{if(++calls===1)await gate.promise;saved.push(p)});
 saver.set({index:0,answer:0,flagged:false});await tick();
 saver.set({index:0,answer:3,flagged:true});gate.reject(Error('old connection failed'));
 assert.equal(await saver.flush(),true);assert.equal(saver.failed,0);assert.equal(saved.at(-1).answer,3);
});

test('failed responses stay dirty for local recovery; retry clears only after acknowledgement',async()=>{
 let offline=true;
 const saver=new AnswerSaver(async()=>{if(offline)throw Error('offline')});
 saver.set({index:4,answer:2,flagged:true});await tick();
 assert.equal(saver.failed,1);assert.deepEqual(saver.drafts(),[{index:4,answer:2,flagged:true}]);
 assert.equal(await saver.flush(),false);
 offline=false;assert.equal(await saver.flush(),true);assert.deepEqual(saver.drafts(),[]);
});

test('failure of one question does not discard other queued responses',async()=>{
 const saved=[];const saver=new AnswerSaver(async p=>{if(p.index===0)throw Error('offline');saved.push(p.index)});
 saver.set({index:0,answer:1,flagged:false});saver.set({index:1,answer:2,flagged:false});await tick();
 assert.deepEqual(saved,[1]);assert.equal(saver.failed,1);assert.deepEqual(saver.drafts().map(p=>p.index),[0]);
});

test('server finalized exam stops queued writes without retrying after deadline',async()=>{
 const calls=[];const saver=new AnswerSaver(async p=>{calls.push(p);return {submitted:true}});
 saver.set({index:0,answer:0,flagged:false});saver.set({index:1,answer:0,flagged:false});
 assert.equal(await saver.flush(),true);assert.equal(saver.closed,true);assert.equal(calls.length,1);
 saver.set({index:2,answer:1,flagged:false});assert.equal(saver.pending,0);
});
