'use strict';
const fs = require('node:fs');

// Both the native app document and PR56's current-version envelope are accepted.
// Never fall back to an old Kubernetes Secret: a successful boot proves consumption.
function databaseUrl(document) {
  let values = document;
  if (document.schema !== undefined) {
    if (document.schema !== 'aws-openbao-secret-v1') throw Error('UNSUPPORTED_SCHEMA');
    const value = document.values?.[document.current];
    if (value?.kind !== 'string' || typeof value.payload !== 'string') throw Error('INVALID_CURRENT');
    const bytes = Buffer.from(value.payload, 'base64');
    if (bytes.toString('base64') !== value.payload) throw Error('INVALID_ENCODING');
    try { values = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)); }
    catch { throw Error('INVALID_CURRENT_JSON'); }
  }
  if (!values || typeof values !== 'object') throw Error('INVALID_DOCUMENT');
  if (typeof values.database_url === 'string') {
    let url;
    try { url = new URL(values.database_url); } catch { throw Error('INVALID_DATABASE_URL'); }
    if (!['postgres:', 'postgresql:'].includes(url.protocol) || !url.hostname || !url.username || !url.password || url.pathname.length < 2) throw Error('INVALID_DATABASE_URL');
    return url.href;
  }
  for (const key of ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']) {
    if (typeof values[key] !== 'string' || !values[key]) throw Error('MISSING_DATABASE_FIELD');
  }
  if (!/^\d+$/.test(values.DB_PORT) || Number(values.DB_PORT) < 1 || Number(values.DB_PORT) > 65535) throw Error('INVALID_DATABASE_PORT');
  const url = new URL('postgresql://placeholder:placeholder@localhost/database');
  url.hostname = values.DB_HOST;
  url.port = values.DB_PORT;
  url.username = encodeURIComponent(values.DB_USER);
  url.password = encodeURIComponent(values.DB_PASSWORD);
  url.pathname = '/' + encodeURIComponent(values.DB_NAME);
  return url.href;
}

async function main(env = process.env, request = fetch) {
  const {BAO_ADDR, BAO_TOKEN, BAO_KV_PATH, OUTPUT_FILE} = env;
  if (!BAO_ADDR || !BAO_TOKEN || !BAO_KV_PATH || !OUTPUT_FILE) throw Error('MISSING_CONFIGURATION');
  // Remove any previous attempt's credential before making a new observation.
  fs.rmSync(OUTPUT_FILE, {force: true});
  let response;
  try {
    response = await request(`${BAO_ADDR}/v1/${BAO_KV_PATH}`, {
      headers: {'X-Vault-Token': BAO_TOKEN}, redirect: 'error', signal: AbortSignal.timeout(5000),
    });
  } catch { throw Error('OPENBAO_UNAVAILABLE'); }
  if (!response.ok) throw Error('OPENBAO_HTTP_' + response.status);
  let document;
  try { document = (await response.json()).data.data; } catch { throw Error('INVALID_RESPONSE'); }
  const url = databaseUrl(document);
  fs.writeFileSync(OUTPUT_FILE, url, {mode: 0o400, flag: 'wx'});
  console.log('DB credential loaded from OpenBao current value; fallback disabled');
}
if (require.main === module) main().catch(() => {
  // Never print upstream exceptions, URLs or response bodies containing secrets.
  console.error('OpenBao credential initialization failed'); process.exitCode = 1;
});
module.exports = {databaseUrl, main};
