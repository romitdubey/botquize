import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {studyProgress} from '../web/study-progress.mjs';
const schedule=JSON.parse(fs.readFileSync(new URL('../web/schedule.js',import.meta.url),'utf8').split('export default ')[1].trim().replace(/;$/,''));
test('old completed Biochemistry dates contribute to Unit 1; weekend tests do not',()=>{
 const days=Object.fromEntries(['16','17','18','19','20','21','22'].map(day=>['2026-10-'+day,{studied:true}]));
 const result=studyProgress(schedule,days);
 assert.equal(result.length,15);
 assert.deepEqual([result[0].done,result[0].total,result[0].percent],[5,6,83]);
 assert.ok(result.slice(0,14).every(unit=>unit.total>0));
 assert.equal(result.reduce((n,u)=>n+u.done,0),5);
 assert.deepEqual([result[14].done,result[14].total],[0,49]);
});
test('main and aptitude completion change independently for the selected account',()=>{
 const days={'2026-10-23':{aptitude_studied:true}};
 let result=studyProgress(schedule,days);
 assert.equal(result[0].done,0);assert.equal(result[14].done,1);
 days['2026-10-23'].studied=true;
 result=studyProgress(schedule,days);assert.equal(result[0].done,1);assert.equal(result[14].done,1);
 assert.equal(studyProgress(schedule,{})[0].done,0);
});
test('all completed unit portions and aptitude reach 100%; mixed revision is separate',()=>{
 const days=Object.fromEntries(schedule.map(row=>[row.date,{studied:true,aptitude_studied:true}]));
 assert.ok(studyProgress(schedule,days).every(item=>item.percent===100));
 assert.equal(studyProgress(schedule,days).slice(0,14).reduce((n,u)=>n+u.total,0),39);
});
