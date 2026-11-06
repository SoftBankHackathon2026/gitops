# Team Ghost sample-app 배포

기존 Argo Rollout의 카나리·분석 흐름을 유지하면서 본선 DB API 이미지를 연결한다.
이 파일들은 GitOps 선언이며 실제 클러스터에 적용하거나 DB를 변경하지 않았다.

## 대상 환경

| Argo 경로 | Namespace | Argo CD Application | 분석 소스 |
| --- | --- | --- | --- |
| `runtime/aws` (wrapper) | `sample-app` | `argocd/sample-app-aws.yaml` | `analysis/prometheus` |
| `overlays/local` | `sample-app` | `argocd/sample-app-local.yaml` | `analysis/default` |
| `overlays/onprem` | `hackathon` | `argocd/onprem/sample-app.yaml` | `analysis/onprem` |

본선 홈랩은 `onprem`이다. 이전 예선용 `local`과 네임스페이스·클러스터 등록이
다르다. `onprem`에는 Ingress가 없으며 앱의 기존 Service로 접근한다.
사용자에게 노출할 공통 진입점과 라우팅은 별도 인프라 작업이다.

**이 디렉터리가 본선 배포 정본이다.** `sample-app` 저장소의 `k8s/`는 독립 적용
예시다. 같은 namespace에 둘을 함께 적용하지 않는다. 특히 `k8s/`와 이 저장소의
onprem은 모두 hackathon namespace에 `sample-app` Service를 만든다.

## AWS 층 순서

뒤 층이 앞 층을 덮는다.

1. `base/`: 사람이 관리. Rollout·Service·제어 ConfigMap(onprem·local 값).
1. `overlays/aws/`: review-service 렌더러 생성물. 앱 저장소 `deploy.yaml`에서
   만든다. 손으로 고치지 않는다. 다음 렌더에 지워진다.
1. `runtime/aws/`: 사람이 관리하는 wrapper. `overlays/aws`를 읽고 최종 patch를
   적용한다. Argo Application은 이 경로를 가져간다.

렌더러는 컨테이너 0번을 통째로 새로 만들고, Secret 이름을 `<app>-secrets`로
고정하며, ConfigMap·Secret volume을 표현하지 못한다. 그래서 wrapper가 다음을
넣는다.

- env `DATABASE_URL`(`sample-app-db/database-url`), `PGSSLMODE=verify-full`,
  `PGSSLROOTCERT=/db-ca/ca.pem`, `APP_CONTROL_FILE`.
- 요청 API 인증 env `REQUEST_API_AUTH=required`와 `REQUEST_API_TOKEN`
  (`sample-app-api-token/token`, `optional: true`). onprem overlay도 같다.
- mount `control`(`/app-control`)과 `db-ca`(`/db-ca`), 둘 다 readOnly.
- pod volume `db-ca`(Secret `sample-app-db-ca`), readiness timeout 3초.
- 제어 ConfigMap의 AWS 초기값 `{"writes_paused":true}`.

wrapper의 첫 두 op는 JSON6902 `test`다. 렌더 결과의 컨테이너 0번 이름이
`sample-app`이고 pod volumes가 `control` 하나뿐이어야 build가 된다. 렌더러가
storage volume을 만들거나 구조를 바꾸면 build가 실패해, mount가 조용히 빠진 채
배포되지 않는다. 생성 경로 밖에 둔 이유는 `apps/loadgen/aws`와 같다.

ALB tags는 렌더러 카탈로그 값(`Project=oneaction,…,Env=dev`)이다. 본선 전용
태그가 필요하면 review-service 카탈로그를 바꿔야 한다.

## 값 차이표

| 항목 | sample-app `k8s/` (예시) | 이 저장소 (정본) |
| --- | --- | --- |
| namespace | aws·onprem 모두 hackathon | aws sample-app, onprem hackathon, local sample-app |
| 종류·replicas | Deployment 2 | Rollout. aws 3, onprem·local 2 |
| memory req/limit | 128Mi/256Mi | aws 128Mi/256Mi, onprem·local 64Mi/128Mi. 앱 실측 없음 |
| DB TLS | aws `DB_SSL=true`+CA, onprem `false` | aws `verify-full`+CA, onprem·local `disable` |
| onprem `DEPLOY_ENV` | onprem | local. 팀 결정 필요 |
| 제어 초기값 | false | base false, aws wrapper true |
| 요청 API 인증 | `required`+Secret(optional) | aws wrapper·onprem `required`+Secret(optional), local 없음(open) |

## 이미지와 CI

이미지는 Docker Hub 공개 저장소 `docker.io/kty1021/sample-app`이다.
amd64·arm64를 묶은 커밋 SHA 태그만 쓰고 `latest`는 쓰지 않는다. 공개
저장소라 imagePullSecrets는 없다.
sample-app CI는 두 arch를 스캔·게시한 뒤 아래 파일의 해당 이미지 `newTag`만
갱신한다. main의 이 파일이 아직 Docker Hub 경로가 아니면 태그를 바꾸지 않고
실패한다.

```text
apps/sample-app/base/kustomization.yaml
```

`newTag`의 초기 값은 새 DB 모듈과 인증을 포함한 앱 커밋
`dda34482ed5106e90e7bcce358015e8cda0f7002`다. 이 태그는 2026-11-04 Docker
Hub 공개 저장소에 게시됐고, 로그인 없이 index와 두 arch의 manifest·config를
받을 수 있음을 확인했다. amd64·arm64를 묶은 index digest는
`sha256:4e219077ff61e90dab00762e81e1ab97bc4344b06a9dc9af2f9ec19aade0f41b`다.
CI가 아니라 손으로 게시한 부트스트랩 이미지이며, 다음 태그부터는 병합 뒤
sample-app main CI가 갱신한다. 클러스터에서 실제로 pull하지는 않았다.
GHCR에만 있던 옛 태그는 Docker Hub에 없다.

## DB 준비

공유 DB의 테이블·역할은 팀의 `migration-db-init`이 정본이다. 앱 역할은
스키마 소유자가 아니며 `public.migration_demo`의 SELECT·INSERT만 허용한다.
테이블과 권한은 앱 배포 전에 명시적으로 준비한다.

각 환경의 해당 namespace에 `sample-app-db` Secret이 필요하다.
`database-url` 키에는 환경별 앱 DB 계정의 PostgreSQL URL을 저장한다.
Secret 값은 이 저장소에 커밋하지 않는다.

AWS는 `PGSSLMODE=verify-full`이며 `sample-app-db-ca` Secret의 `ca.pem`을
`/db-ca/ca.pem`으로 마운트한다. 해당 RDS 서버 인증서를 검증할 CA를 넣고,
인증서 SAN이 접속 호스트와 맞는지 확인한다. Secret은 네임스페이스 단위이므로
다른 환경에 자동 복사되지 않는다. 로컬과 온프렘 데모는 사설 연결에서
`PGSSLMODE=disable`을 사용한다. 온프렘 PostgreSQL이 비TLS를 허용하지 않으면
해당 overlay에 검증 CA와 TLS 설정을 명시한다.

```sh
# 접속 문자열 자체를 셸 기록에 넣지 않고 준비된 파일에서 읽는 예시.
kubectl -n sample-app create secret generic sample-app-db \
  --from-file=database-url=/secure/aws-database-url
kubectl -n sample-app create secret generic sample-app-db-ca \
  --from-file=ca.pem=/secure/rds-ca.pem
kubectl -n hackathon create secret generic sample-app-db \
  --from-file=database-url=/secure/onprem-database-url
```

## 요청 API 인증

AWS wrapper와 onprem은 `REQUEST_API_AUTH=required`다. `/api/requests`의
POST·GET은 Bearer 토큰이 필요하고, 화면·`/healthz`·`/readyz`·`/api/info`·
`/metrics`는 인증 없이 열려 있다. 토큰은 `sample-app-api-token` Secret의 `token` 키에서
읽는다. 참조가 `optional: true`라 Secret이 없어도 Pod는 뜨고 요청 API만 503
`API_AUTH_UNCONFIGURED`로 닫힌다.

지금 공개 진입점은 HTTP 80이다. HTTPS·도메인·인증서·Secret 작성은 외부
작업이며 이 변경에 포함하지 않았다. 그래서 적용 직후에는 익명 쓰기가 503
또는 401로 막히고, 봇은 `http://` 진입점에 토큰을 보내지 않고 시작을
거절한다(fail-closed).

`overlays/local`은 개발용이라 인증 env를 넣지 않았다(open). 매니페스트는
localhost 바인딩을 보장하지 않는다. k3d를 `-p "8081:80@loadbalancer"`로
만들면 모든 인터페이스에 열려 같은 LAN에서 익명 쓰기가 된다
([argocd/install/README.md](../../argocd/install/README.md) 참고).
`-p "127.0.0.1:8081:80@loadbalancer"`로 만들고, 공개 진입점이나 공유망에
연결하지 않는다. 인증 env는 gcp overlay, `base/rollout.yaml`, argocd에 넣지
않았다. gcp overlay는 이 PR 전체에서 바뀌지 않았다. 다만 PR 전체로는
`base/rollout.yaml`의 이미지 경로·control volume·readiness timeout과
`argocd/sample-app-aws.yaml`의 소스 경로(`runtime/aws`)가 바뀌었다.

wrapper와 onprem의 `REQUEST_API_AUTH`·`REQUEST_API_TOKEN`이 빠지는 회귀를
막는 자동 시험은 이 저장소에 없다. gitops 저장소에는 CI가 없어서다. 지금은
변경 때 `kubectl kustomize`로 두 env가 한 번씩 있는지 직접 확인한다. 자동
검사 추가는 후속 작업이며 담당자는 김태윤이다.

토큰 파일에는 32자 이상 b64token 하나만 넣고 끝에 줄바꿈을 두지 않는다. 값을
명령행 literal로 넣거나 출력하지 않는다. 봇은 `hackathon` namespace라 온프렘과
같은 Secret을 쓴다.

```sh
# 같은 파일에서 AWS·온프렘(봇 포함) namespace에 같은 값을 만든다.
kubectl -n sample-app create secret generic sample-app-api-token \
  --from-file=token=/secure/request-api-token
kubectl -n hackathon create secret generic sample-app-api-token \
  --from-file=token=/secure/request-api-token
```

교체·롤백·Pod별 확인 명령과 남는 위험은 sample-app 저장소의
`docs/deployment.md` 요청 API 인증 절에 있다.

## 헬스체크와 쓰기 제어

AWS·local·onprem의 readiness는 `/readyz`, liveness는 `/healthz`다.
readiness는 DB 조회 가능 여부만 본다. 제어 파일이 깨져도 readiness는 내려가지
않고 쓰기만 정지한다. 이상은 `/api/info`의 `write_control.healthy`로 드러난다.
DB 장애만으로 프로세스를 계속 재시작하지 않는다. `FAIL_RATE=0`이며 예선
`APP_NOTICE` Secret 의존성을 제거했다. AWS ALB의 대상 헬스체크도 `/readyz`다.

`sample-app-control` ConfigMap의 `control.json`은 base에서
`{"writes_paused":false}`, AWS wrapper에서 `{"writes_paused":true}`다. 안정된
이름과 디렉터리 마운트로 파일 변경을 프로세스 재시작 없이 받는다.
ConfigMap projection은 즉시 반영되지 않는다.

Argo CD는 `selfHeal`을 사용하므로 `kubectl patch`만으로 정지한 상태는 Git의
값으로 복원될 수 있다. 쓰기 정지는 Git에서 바꾼다. 파일 정지는 해당 앱
프로세스의 쓰기만 막으며 DB 권한 차단·진행 중 트랜잭션 정리·CDC 완료 검증을
대신하지 않는다. 쓰기 정지 중에는 이미지 rollout을 하지 않는다.

## 기존 INSERT 워커와의 전환 순서

팀의 `db-insert-worker`, `migration.cutover`, `migration-db-init`은 바꾸지
않는다. 새 봇은 워커와 함께 돌며 run_id `ghost_bot_forward_001`을 쓴다.
워커의 `forward_NNN`·`return_NNN`과 겹치지 않는다.

1. 5단계: onprem `control.json`을 true로 Git에 커밋하고 동기화한다.
1. cutover `--approve` 전에 모든 replica의 `/api/info`에서
   `writes_paused=true`, `writes_in_flight=0`을 Pod마다 확인한다.
1. 6단계: cutover의 `migration_app` 권한 회수가 실제 차단이다. API 정지만으로
   차단했다고 주장하지 않는다.
1. 9단계: 공개 진입점 전환 뒤 봇을 `BOT_PHASE=aws_live`로 재기동하고 AWS
   `control.json`을 false로 바꾼다. 그 전에 공개 HTTPS, 세 namespace의 같은
   토큰 Secret, 봇 `https://` base-url을 갖추고, AWS·온프렘 Rollout 완전
   승격 뒤 Pod마다 `mode="enforced"`와 인증 GET 통과를 확인한다. 한 Pod라도
   통과하지 않으면 봇을 재개하지 않는다. 토큰 교체 뒤에도 같다.

cutover의 자동 행 수 게이트는 모든 writer의 합계다. writer별 증거는 run_id별
`count(*)`·`count(DISTINCT request_no)` 증분과 각자의 ledger로 따로 남긴다.
명령과 수락 조건은 sample-app 저장소의 `docs/deployment.md`에 있다.

## 트래픽 봇

새 영속 HTTP 봇의 배포 선언은 `sample-app` 저장소의 `k8s/traffic-bot`에 있다.
이 저장소의 기존 예선 `apps/loadgen`과 `argocd/sample-app-loadgen-aws.yaml`은
조회 전용 봇이므로 DB 저장·왕복 이전 검증용으로 간주하지 않는다.
두 봇을 동시에 실행해 측정 결과를 혼합하지 않도록 운영자가 구분한다.

## GCP

`argocd/sample-app-gcp.yaml`은 아직 적용하지 않는다(GKE 미등록). 이번 변경은
`overlays/gcp`를 바꾸지 않았지만 base 변경이 gcp 렌더에 들어간다.

- 이미지 조직 경로, 제어 ConfigMap·volume·mount, readiness timeout 3초.
- gcp overlay는 env를 통째로 바꾸므로 `DATABASE_URL`이 없어 DB API가 503이다.
  readiness가 `/healthz`라 Pod는 Ready로 보인다.

DB·Secret·readiness·`newTag` 결정을 마치기 전에는 GCP Application을
활성화하지 않는다.

## 로컬 렌더 검증

```sh
kubectl kustomize apps/sample-app/runtime/aws
kubectl kustomize apps/sample-app/overlays/local
kubectl kustomize apps/sample-app/overlays/onprem
kubectl kustomize apps/sample-app/analysis/onprem
```

Argo Rollouts·AnalysisTemplate CRD, 각 클러스터 등록, Prometheus, Secret과
실제 접속·권한은 렌더 성공만으로 검증되지 않는다. Argo CD에 내장된 kustomize
버전에서 JSON6902 `test`가 동작하는지도 클러스터에서 확인하지 않았다.

## 온프렘 실제 값 (2026-11-05, 가연)

- 플랫폼 Postgres 는 `hostssl` 만 허용하고 self-signed 인증서(SAN `postgres`, `postgres.hackathon.svc.cluster.local`)를 쓴다.
  앱의 `require` 도 인증서를 검증하므로 온프렘은 `PGSSLMODE=verify-full` + `PGSSLROOTCERT=/db-ca/ca.pem` 이고,
  Secret `sample-app-db-ca` 의 `ca.pem` 은 Secret `postgres-tls` 의 `tls.crt` 를 그대로 복사한 것이다.
- `DATABASE_URL` 은 `postgresql://migration_app:<migration-db-credentials.app_password>@postgres.hackathon.svc.cluster.local:5432/migration_demo`.
  테이블·역할은 `migration-db-init` 이 만든다. 앱은 테이블을 만들지 않는다.
- 요청 API 인증은 온프렘에서 `optional`(open)이다. 공개 진입점이 없고 트래픽 봇이 ClusterIP 로 붙어야 하기 때문이다.
  봇 선언은 `apps/traffic-bot/`(Argo `traffic-bot`), 토큰 없이 돈다.

## 온프렘 DB 설정 경로 (OpenBao)

온프렘 파드는 시작할 때 init 컨테이너 `render-db-url` 이 OpenBao
`secret/data/hackathon/sample-app/onprem` 의 `DB_HOST`·`DB_PORT`·`DB_NAME`·`DB_USER` 와
Secret `sample-app-db` 의 비밀번호로 접속 URL 을 만들어 `/run/db/database-url`(메모리 emptyDir)에 쓴다.
앱은 `DATABASE_URL_FILE` 로 이 파일을 시작할 때 한 번 읽는다. verify-full 과 `sample-app-db-ca` 는 그대로다.

- OpenBao 에 닿지 않거나 봉인(503)이면 경고를 남기고 **Secret 의 URL 그대로 시작한다.** 봉인 때문에 공용 앱이 못 뜨는 일을 막기 위해서다. 이때는 저장소 값이 반영되지 않으므로 init 로그를 확인한다.
- 토큰 거절(403)이나 값 없음은 설정 오류라 init 이 실패하고 새 파드가 시작하지 않는다. 토큰 Secret 이 없어도 같다.
- sample-app 쪽 egress 를 막는 NetworkPolicy 는 없고 OpenBao 는 같은 네임스페이스 ingress 를 허용하므로 정책 추가는 필요 없다.
- `sample-app-smoke` Service 는 NotReady 파드까지 포함한다. AI 에이전트 스모크 전용이다 (`service-smoke.yaml` 설명 참고).

### 이 overlay 를 main 에 올리기 전에 (한 번만)

순서를 지킨다. 값이 없는 상태로 배포하면 카나리 파드가 Init 에서 멈추고 Rollout 이 abort 된다 (stable 은 유지된다).

```sh
export KUBECONFIG=~/.kube/oneport-onprem.yaml
NS="-n hackathon"

# 1) 봉인 해제 (파드가 다시 뜰 때마다 필요). apps/openbao/README.md 참고
kubectl $NS exec openbao-0 -- bao status | grep Sealed

# 2) 관리자 토큰은 Secret 에서 읽어 셸 변수로만 쓴다. 값을 출력하지 않는다
ROOT=$(kubectl $NS get secret openbao-init -o jsonpath='{.data.init\.json}' | base64 -d | python3 -c 'import sys,json; print(json.load(sys.stdin)["root_token"])')
bao_exec() { kubectl $NS exec -i openbao-0 -- env BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN="$ROOT" bao "$@"; }

# 3) 지금 쓰는 접속 URL 에서 비밀이 아닌 값만 뽑아 저장소에 넣는다 (비밀번호는 넣지 않는다)
kubectl $NS get secret sample-app-db -o jsonpath='{.data.database-url}' | base64 -d | python3 -c '
import json,sys,urllib.parse as u
p=u.urlsplit(sys.stdin.read().strip())
print(json.dumps({"DB_HOST":p.hostname,"DB_PORT":str(p.port or 5432),"DB_NAME":p.path.lstrip("/"),"DB_USER":u.unquote(p.username)}))
' | bao_exec kv put -mount=secret hackathon/sample-app/onprem -

# 4) 읽기 전용 정책과 앱 전용 토큰. 토큰은 Secret 에만 남긴다 (에이전트 토큰 재사용 금지)
printf 'path "secret/data/hackathon/sample-app/onprem" { capabilities = ["read"] }\n' | bao_exec policy write sample-app-read -
bao_exec token create -orphan -no-default-policy -policy=sample-app-read -ttl=720h -format=json \
  | python3 -c 'import sys,json; sys.stdout.write(json.load(sys.stdin)["auth"]["client_token"])' \
  | kubectl $NS create secret generic sample-app-openbao --from-file=token=/dev/stdin
unset ROOT

# 5) 확인: 앱 토큰으로 읽히고 쓰이지 않아야 한다 (쓰기는 403)
```

토큰 TTL 은 720시간이다. 만료되면 새 파드가 시작하지 못하니 데모 뒤에도 계속 쓰면 다시 발급한다.
