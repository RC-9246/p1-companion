'use strict';
// Evaluate the real frontend against an in-memory DOM; no browser, HTTP or host
// commands. Only remove the automatic first refresh; call real handlers below.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const assert=require('node:assert/strict');const catalog=JSON.parse(fs.readFileSync(path.join(root,'modules/catalog.json'),'utf8'));const fixture={catalog,plan:{enabled:['core'],enable:[],disable:['maintenance','monitor'],dependencies_added:[]}};
const elements=new Map();
function node(tag='div') {
 const x={tag,value:'',textContent:'',disabled:false,children:[],listeners:{},dataset:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},append(...n){this.children.push(...n)},replaceChildren(...n){this.children=n},addEventListener(k,f){this.listeners[k]=f},removeAttribute(){}};
 Object.defineProperty(x,'checked',{get(){return this._checked||false},set(v){this._checked=!!v}});
 Object.defineProperty(x,'id',{get(){return this._id},set(v){this._id=v;elements.set(v,this)}});
 return x;
}
function get(id){if(!elements.has(id)){const x=node();x.id=id}return elements.get(id)}
const posts=[];
const context=vm.createContext({document:{getElementById:get,createElement:node,querySelectorAll(){return []},querySelector(){return {value:'new'}}},location:{hash:'',pathname:'/'},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},history:{replaceState(){}},window:{scrollTo(){}},setTimeout(){return 0},clearTimeout(){},confirm(){return true},posts});
const script=fs.readFileSync(path.join(root,'deploy/wizard/app.js'),'utf8').replace('renderMode();refresh();','renderMode();');
vm.runInContext(script,context,{filename:'deploy/wizard/app.js'});
vm.runInContext('request=async(path,body)=>{posts.push({path,body});return {}};refresh=async()=>{};',context);
context.fixture=fixture;
get('root').value='/srv/p1-agent';get('modules-accepted').checked=true;
(async()=>{
 vm.runInContext('renderModules(fixture.catalog,[])',context);
 await vm.runInContext("runModules('modules_apply')",context);
 const blockedBefore={moduleLoaded:vm.runInContext('moduleLoaded',context),posts:posts.length,message:get('modules-result').textContent};
 vm.runInContext("renderModules(fixture.catalog,[{id:'synthetic-plan',action:'modules_plan',status:'succeeded',result:fixture.plan}])",context);
 await vm.runInContext("runModules('modules_apply')",context);
 const planBypass={before:blockedBefore,after:{moduleLoaded:vm.runInContext('moduleLoaded',context),lastAction:posts.at(-1),planDisable:fixture.plan.disable,hostSelections:['maintenance','resource_guard','monitor'].map(id=>({id,checked:get('mod-'+id).checked}))}};
 get('upgrade-component').value='astrbot';
 context.catalogJobs=[{id:'astrbot-list',action:'upgrade_check',status:'succeeded',result:{component:'astrbot',versions:[{version:'v4.29.1',released:'2026-10-01'}]}}];
 vm.runInContext('renderUpgrade({},catalogJobs)',context);
 get('upgrade-component').value='snowluma';get('upgrade-component').listeners.change();
 const immediatelyAfterChange={component:get('upgrade-component').value,version:get('upgrade-version').value,catalog:get('upgrade-catalog').textContent};
 vm.runInContext('renderUpgrade({},catalogJobs)',context);
 const afterPoll={component:get('upgrade-component').value,version:get('upgrade-version').value,catalog:get('upgrade-catalog').textContent,options:get('upgrade-versions').children.map(x=>x.value)};
 const result={U5_module_plan_bypasses_read_state:planBypass,U6_component_catalog_stale:{immediatelyAfterChange,afterPoll}};
 assert.equal(planBypass.after.moduleLoaded,false);assert.equal(posts.length,0);assert.equal(afterPoll.version,'');assert.deepEqual(afterPoll.options,[]);
 process.stdout.write(JSON.stringify({passed:true,cases:['module_plan_is_not_loaded_state','changed_component_ignores_stale_catalog']})+'\n');
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
