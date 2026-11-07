const https=require('https'),fs=require('fs');
const rows=new Map();
for (const [port,environment] of [[8443,'aws'],[8444,'gcp']]) {
 https.createServer({key:fs.readFileSync('/fixture/key.pem'),cert:fs.readFileSync('/fixture/cert.pem')},(req,res)=>{
  const out=(n,b)=>{res.writeHead(n,{'Content-Type':'application/json'});res.end(JSON.stringify(b));};
  if(req.url==='/readyz')return out(200,{status:'ok'});
  if(req.url==='/api/info')return out(200,{environment,database:{name:environment},writes_paused:false});
  if(req.headers.authorization!=='Bearer local-test-backend')return out(401,{});
  if(req.method==='POST'&&req.url==='/api/requests'){
   let b='';req.on('data',x=>b+=x);req.on('end',()=>{const r=JSON.parse(b);rows.set(r.request_id,{request:r,environment});out(200,{status:'committed'});});return;
  }
  const row=rows.get(req.url.split('/').pop());return row?out(200,{status:'committed',...row}):out(404,{});
 }).listen(port,'0.0.0.0');
}
