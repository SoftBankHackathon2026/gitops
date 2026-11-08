# 트래픽봇 기반 DB 전환 배포

러너는 HTTP 트래픽봇의 생성량을 제한하고 접수 큐를 전환한다.
DB insert 워커의 API와 원장은 사용하지 않는다. 작업이 끝나면 새 요청 생성을
정지하고 이미 접수된 요청이 정리됐는지 확인한다. 봇 Pod와 PVC는 남겨 두어
상태 조회와 재시작 후 정지 상태 복구가 가능하게 한다.

## 적용 전제

이 변경의 매니페스트만 기존 이미지에 적용하면 새 러너가 동작하지 않는다.
현재 커밋의 봇 이미지 `beaea996`와 러너 이미지 `1d80b61`은 배포 기록을
보존하려고 그대로 두었다. 아래 두 이미지 빌드가 성공한 뒤 실제 immutable
태그로 교체하고 GitOps PR을 머지한다. 존재하지 않는 태그를 미리 넣지 않는다.

- sample-app: 영속 생성 상태, 절대 생성 한도, 원장 식별자, 생성 제어 API 지원.
- Hackathon: `bot`·`ingress` 설정을 읽는 새 전환 러너.
- Secret `demo-traffic-agent`의 `bot_control_token` 키: 봇과 러너가 같은 값 참조.
- Secret `durable-ingress-control`의 `token` 키: 접수 큐와 러너가 같은 값 참조.

시크릿 값은 Git·문서·로그에 쓰지 않는다. 각 Secret 존재와 키 이름만 확인한다.

## GitOps 적용 순서

1. `apps/traffic-bot/kustomization.yaml`의 `images[].newTag`를 새 봇의
   빌드된 커밋 태그로 바꾸고 이 디렉터리의 설정과 함께 반영한다.
   `BOT_GENERATION=stopped`는 새 원장의 초기값이며 기존 원장 상태를 덮지 않는다.
   이미 돌던 봇은 인증된 `/control/generation`으로 정지하고 응답과 재시작 후
   `/control`에서 `generation=stopped`를 확인한다.
2. 봇 `/control`에서 `control_enabled=true`, `ledger_id`, `run_id`,
   `generated_total`, `generation_limit`, `request_endpoint`를 확인한다.
   기대 접수 경로는 `http://durable-ingress.hackathon.svc.cluster.local/api/requests`다.
3. `apps/live-db-cutover/runner.yaml`의 runner 이미지를 새 러너의 빌드된
   커밋 태그로 바꾸고 ConfigMap·환경변수 변경과 함께 반영한다.
   Argo CD 자동 동기화 및 Pod 준비 상태를 확인한다. `kubectl apply`는 쓰지 않는다.
4. 읽기 전용 사전 확인 후 새 `job_id`로 이전을 실행한다. 과거 완료된
   `durable_forward_001` 등의 ID를 재사용하지 않는다. 플랫폼 보고기는 base 설정의
   `bot`·`ingress`를 보존하고 job 절만 해당 작업의 방향으로 바꾼다.
5. 실제 시연에서 정방향·귀환, 중간 실패·재시도, 완료 후 봇 정지를 확인한다.
   로컬 테스트와 운영 통합 테스트 완료는 별도로 기록한다.

`onprem_return`은 실제 sample-app의 `migration_demo_return`, `aws`는
sample-app-rds의 `migration_demo`, `rehearsal`은 sample-app-rehearsal의
`migration_demo_rehearsal`에 대응한다. 기존 `targets.onprem`의
`migration_demo`는 현재 접수 큐 경로가 없으므로 이전 대상으로 선택하지 않는다.

1000건 시연을 사용할 때는 별도의 준비 절차로 원본 seed 800건·빈 대상·새 봇
원장을 준비하고 `cutover.demo_total_rows: 1000`을 설정한다. 이 배포는 기존 DB나
원장을 자동 초기화하지 않는다. 기본 설정도 봇 생성량을 단계별로 제한한다.

## 검증과 복구

```sh
kubectl kustomize apps/traffic-bot
kubectl kustomize apps/live-db-cutover
python3 tests/cutover-bot-wiring.test.py
```

완료 조건은 봇 생성 정지·미확인 요청 정리·대상 DB 검증이다. Pod Ready만으로
이전 성공을 판정하지 않는다. 대상 DB 쓰기가 열린 뒤 실패한 작업은
`NEEDS_RECOVERY` 상태에서 실제 쓰기 대상을 확인한다. 이미 쓰기를 받은 대상이
있을 때 과거 러너 이미지나 DB봇을 복구해서 원본에 다시 쓰게 만들지 않는다.

이미지·설정 문제의 복구는 봇을 정지한 상태로 GitOps 커밋을 수정한다.
새 봇 원장의 영속 제어 메타데이터를 이해하지 못하는 구버전 봇으로 롤백하면
생성이 다시 시작될 수 있으므로 구버전 이미지 롤백은 자동 복구 절차가 아니다.
