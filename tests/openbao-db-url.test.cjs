const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {databaseUrl, main} = require('../apps/sample-app/overlays/onprem/render-db-url.js');
const fields = {DB_HOST:'postgres', DB_PORT:'5432', DB_NAME:'migration_demo_return', DB_USER:'app', DB_PASSWORD:'p@ss:/?#%'};
test('password comes from OpenBao, with reserved characters preserved', () => {
 const u = new URL(databaseUrl(fields)); assert.equal(decodeURIComponent(u.password), fields.DB_PASSWORD); assert.equal(u.pathname, '/migration_demo_return');
});
test('PR56 current selects current rather than previous', () => {
 const doc = {schema:'aws-openbao-secret-v1', current:'v2', previous:'v1', values:{v1:{kind:'string',payload:Buffer.from(JSON.stringify({database_url:'postgres://app:old@postgres/db'})).toString('base64')},v2:{kind:'string',payload:Buffer.from(JSON.stringify({database_url:'postgres://app:new@postgres/db'})).toString('base64')}}};
 assert.equal(new URL(databaseUrl(doc)).password, 'new');
});
test('missing passwords, invalid versions and unsupported binary fail closed', () => {
 assert.throws(()=>databaseUrl({...fields,DB_PASSWORD:undefined}));
 assert.throws(()=>databaseUrl({schema:'unknown'}));
 assert.throws(()=>databaseUrl({schema:'aws-openbao-secret-v1',current:'missing',values:{}}));
 assert.throws(()=>databaseUrl({database_url:'https://app:pass@postgres/db'}));
});
for(const status of [403,503]) test(`HTTP ${status} cannot reuse stale file or legacy secret`, async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'bao-test-'));const output=path.join(dir,'db');fs.writeFileSync(output,'stale');
 try {await assert.rejects(main({BAO_ADDR:'http://bao',BAO_TOKEN:'test',BAO_KV_PATH:'test',OUTPUT_FILE:output,BASE_DATABASE_URL:'postgres://old:old@old/old'},async()=>({ok:false,status})));assert.equal(fs.existsSync(output),false);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('network failure cannot reuse stale credentials',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'bao-test-'));const output=path.join(dir,'db');fs.writeFileSync(output,'stale');
 try{await assert.rejects(main({BAO_ADDR:'http://bao',BAO_TOKEN:'test',BAO_KV_PATH:'test',OUTPUT_FILE:output},async()=>{throw Error('sensitive upstream');}),/OPENBAO_UNAVAILABLE/);assert.equal(fs.existsSync(output),false);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('success writes only current credentials with owner read-only permissions',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'bao-test-'));const output=path.join(dir,'db');
 try{await main({BAO_ADDR:'http://bao',BAO_TOKEN:'test',BAO_KV_PATH:'test',OUTPUT_FILE:output},async()=>({ok:true,json:async()=>({data:{data:fields}})}));assert.equal(new URL(fs.readFileSync(output,'utf8')).password,encodeURIComponent(fields.DB_PASSWORD));assert.equal(fs.statSync(output).mode & 0o777,0o400);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
