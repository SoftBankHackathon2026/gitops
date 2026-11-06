// init 컨테이너. OpenBao 의 DB_HOST/PORT/NAME/USER 와 Secret sample-app-db 의 비밀번호로 DATABASE_URL 파일을 만든다.
// 비밀번호와 토큰은 로그에 남기지 않는다.
//
// OpenBao 에 닿지 않거나 봉인(503)이면 Secret 의 URL 그대로 시작한다. OpenBao 는 재시작마다 수동 unseal 이 필요해
// 봉인 때문에 공용 sample-app 이 못 뜨면 안 된다. 그 밖의 오류(토큰 거절, 값 없음)는 설정 문제이므로 실패시킨다.
// 저장소에 틀린 값이 있으면 그 값을 그대로 쓴다. 장애 주입과 AI 수정은 이 경로로 동작한다.
'use strict';
const fs = require('node:fs');

function fallback(reason, baseUrl, outputFile) {
  console.warn(`경고: OpenBao 를 읽지 못해 Secret 의 DB URL 로 시작한다 (${reason}). 저장소 값이 반영되지 않았다`);
  writeUrl(outputFile, baseUrl);
}

function writeUrl(outputFile, url) {
  fs.rmSync(outputFile, {force: true}); // 재실행 시 0400 파일을 덮어쓸 수 없다
  fs.writeFileSync(outputFile, url, {mode: 0o400});
}

async function main() {
  const {BAO_ADDR, BAO_TOKEN, BAO_KV_PATH, BASE_DATABASE_URL, OUTPUT_FILE} = process.env;
  let res;
  try {
    res = await fetch(`${BAO_ADDR}/v1/${BAO_KV_PATH}`, {
      headers: {'X-Vault-Token': BAO_TOKEN},
      redirect: 'error',
      signal: AbortSignal.timeout(5000),
    });
  } catch (error) {
    return fallback(error.name, BASE_DATABASE_URL, OUTPUT_FILE);
  }
  if (res.status === 503) return fallback('봉인', BASE_DATABASE_URL, OUTPUT_FILE);
  if (!res.ok) throw new Error(`OpenBao HTTP ${res.status}`);
  const values = (await res.json())?.data?.data ?? {};
  for (const key of ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER']) {
    if (!values[key]) throw new Error(`OpenBao 값 없음: ${key}`);
  }
  const url = new URL(BASE_DATABASE_URL); // 비밀번호와 쿼리는 그대로 둔다
  url.hostname = values.DB_HOST;
  url.port = String(values.DB_PORT);
  url.username = encodeURIComponent(values.DB_USER);
  url.pathname = `/${encodeURIComponent(values.DB_NAME)}`;
  writeUrl(OUTPUT_FILE, url.href);
  console.log(`DB URL 생성: host=${values.DB_HOST} port=${values.DB_PORT} db=${values.DB_NAME} user=${values.DB_USER}`);
}

main().catch((error) => {
  console.error(`DB URL 생성 실패: ${error.message}`);
  process.exit(1);
});
