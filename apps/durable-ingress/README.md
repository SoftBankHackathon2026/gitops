# 실제 온프렘 → AWS 요청 접수와 전환

온프렘 접수 서비스를 app-of-apps로 배포한다. 앱 이미지는 sample-app PR #5의 merge SHA로 고정한다.
처음에는 paused이며 기존 봇 주소는 그대로다. AWS 준비 전에는 대상 전환하지 않는다.
실제 이전 시험은 아직 실행하지 않았다.

## 2026-11-06 실제 환경 확인

- 온프렘 sample-app: `migration_demo_return`, writes_paused=false, in_flight=0.
- AWS 외부 앱: version `9443835`, `/api/info`에 DB 정보 없음.
  `/readyz`와 `/api/requests/<id>` 모두 HTML 404. 온프렘 파드에서도 동일.
- 프로젝트 AWS 계정의 EKS `oneaction`은 ACTIVE. 현재 PC의 API TCP443 접속은 timeout.
  현재 출구 IPv4가 기존 EKS API allowlist에 없다. 기본 aws-eks 컨텍스트는 다른 계정이다.
- 따라서 대상 앱 준비 전에는 원본 fencing/트래픽 전환을 실행하지 않는다.

## 배포 순서

1. sample-app의 `src/durable-ingress/`와 202 접수 지원 봇을 PR로 게시한다.
   CI 통과·머지·이미지 게시 뒤 kustomization의 SHA에 해당하는 이미지 게시를 확인한다.
2. AWS EKS 접근을 기존 infra/eks Terraform allowlist 절차로 복구한다.
   기존 주소를 유지하고 현재 작업 PC /32만 추가한다. 노드/권한/다른 인프라 변경은 제외한다.
3. AWS Argo app-of-apps에서 기존 `sample-app-aws`가 `apps/sample-app/runtime/aws`를
   사용하는지 확인한다. 새 앱 이미지, `sample-app-db`, `sample-app-db-ca`,
   `sample-app-api-token` Secret 참조를 맞춘다. 값은 Secret Manager/기존 주입 경로로 전달한다.
   목표 DB `migration_demo`, 쓰기 정지 상태를 유지한다. 인증 토큰은 HTTP로 보내지 않는다.
4. 실제 AWS HTTPS 주소/인증 경로가 준비되면 `INGRESS_TARGETS`에 aws를 추가한다.
   `{url: <HTTPS주소>, token_env: AWS_REQUEST_API_TOKEN}` 구조, 토큰 env는 Secret 참조.
   sample-app `scripts/preflight-live-migration.js`로 양쪽 API·DB·대상 pause를 확인한다.
5. `argocd/onprem/durable-ingress.yaml`을 통해 Argo가 배포한다.
   Redis PVC·AOF·NetworkPolicy 동작과 ingress readiness를 확인한다.
6. 운영 포트를 port-forward한다. 제어 API는 파드 loopback:9092에만 바인딩되며 Service에 없다.
   `kubectl -n hackathon port-forward deploy/durable-ingress 19092:9092 18080:8080`
   `/status`의 epoch 확인 → `POST /resume {expected_epoch: "0"}` → 합성 요청 접수/DB 확인.
7. 봇 이미지를 같은 새 SHA로 고정하고 target ConfigMap을 `http://durable-ingress`로 변경한다.
   기존 봇 ledger를 지우지 않는다. 시험 전후 차이와 별도 run_id로 결과를 구분한다.

## 자동 전환 (cutover 가 큐를 제어)

`apps/live-db-cutover/configmap.yaml` 의 `ingress` 절이 있으면 `python -m migration.cutover run --approve <id>` 한 번으로
DB 와 접수 큐가 같이 넘어간다. cutover 가 FENCING 에서 `/pause`(settled·in_flight 0 확인) 뒤 원본을 REVOKE 하고,
SWITCHING 에서 대상 GRANT → 워커 전환 → 대상 앱 `/readyz`·`/api/info`(database 일치, writes_paused=false) 를
기다린 뒤 `/target` → `/resume` 한다. 실패하면 큐는 paused 로 남고(SWITCHING 전이면 `abort` 가 원본으로 resume),
SWITCHING 이후 실패는 NEEDS_RECOVERY 로 사람이 확정한다.

배선: `durable-ingress-control` Service(9092) + NetworkPolicy(러너 `app=live-db-cutover`, 워커
`app.kubernetes.io/name=db-insert-worker` 만), ingress 파드 `INGRESS_CONTROL_HOST=0.0.0.0`,
양쪽에 Secret `durable-ingress-control`/`token`(optional) 을 `INGRESS_CONTROL_TOKEN` 으로 준다.
토큰 Secret 은 운영자가 만든다(값은 GitOps 에 넣지 않는다):

```
read -s TOKEN; kubectl -n hackathon create secret generic durable-ingress-control --from-literal=token="$TOKEN"
```

Secret 이 없으면 NetworkPolicy 만으로 보호되고 토큰 검사는 꺼진다. 아래 수동 순서는 `ingress` 절을 지우거나
비상시에 그대로 쓸 수 있다(제어 API 자체는 바뀌지 않았다). 자동 전환은 **실제 클러스터에서 아직 실행하지 않았다**
(로컬 Redis+ingress+앱 통합 시험만 통과).

## 실제 전환 순서 (현재 onprem_return → aws)

1. 새 job_id로 기존 migration.cutover CDC를 시작해 READY까지 준비한다. 이전 job/offset 재사용 금지.
   초기 snapshot과 대상 배포는 5분 시연 전에 마친다. 현재 source는 `migration_demo_return`이다.
2. 고정 접수 주소로 요청을 계속 보낸다. 생성·최초 POST 결과·202·최종 committed를 각각 기록한다.
   기존 직접 DB 워커는 기존 전환 도구가 제어하며 외부 요청 봇과 지표를 합치지 않는다.
3. `POST /pause {}`가 `settled:true, in_flight:0`을 반환할 때까지 기다린다.
   접수 API는 계속 202를 반환한다. 다음으로 GitOps 앱 쓰기 정지를 반영하고
   모든 원본 앱 파드의 writes_paused=true/in_flight=0을 확인한다.
4. 기존 cutover 승인을 실행한다: DB 워커 pause/drain → 원본 권한 fencing → CDC 최종 동기화
   → source/target ID·필드 비교 → 대상 writer 승격. 어느 단계든 미확정이면 큐는 paused 유지.
   기존 도구가 COMPLETED라고 해도 앱/접수 큐 전환이 끝난 것은 아니다.
5. AWS 앱의 쓰기를 GitOps로 열고 readiness/DB identity 확인. 큐의 `POST /target`에
   `{target:"aws", expected_epoch:<현재문자열>}`을 전송한다. 반환된 새 epoch로 `/resume`한다.
   앱 readiness를 맞추는 동안에도 접수는 지속되며 고정 주소는 바뀌지 않는다.
6. 요청별 최종 DB ID·모든 필드·중복·대기열 잔여를 비교한다. AWS 앱 응답의 environment=aws와
   database=migration_demo를 별도로 확인한다. 측정된 전환 구간이 300초 이내인지 기록한다.

## 실패 시

- 대상 쓰기를 열기 전 실패: cutover abort로 원본 writer 복구를 확인한 뒤 원본 앱 쓰기 재개,
  큐 target=onprem을 확인하고 현재 epoch로 resume한다.
- 대상 쓰기를 연 이후: 옛 DB로 자동 복귀 금지. 큐는 접수하되 소비를 멈추고 데이터가 어디까지
  반영됐는지 확인한다. 새 데이터를 보존하는 별도 귀환 절차를 따른다.
- Redis 자체 중단은 새 요청 접수 503이다. 단일 Redis/PVC 구성은 노드·디스크 손실에 대한 HA가 아니다.
- 소비자 재시작은 항상 paused. 단일 consumer lease와 Recreate로 중복 실행을 막는다.
  운영 제어는 순차 수행하고 원본 DB fencing을 반드시 유지한다.
- 기록 보존 상한은 100,000건이다. committed stream도 자동 삭제하지 않는다.
  큐 포화/접수 오류를 재시도로 감춰 실패 0으로 계산하지 않는다.

## 판정

202는 접수 성공일 뿐 DB 완료가 아니다. 최초 요청 실패 0, 접수 ID = 최종 DB ID,
필드 불일치 0, 중복 0, pending 0이 모두 확인돼야 해당 회차가 성공이다.
이 문서와 사전 코드 시험은 실제 이전 통과 증거가 아니다.
