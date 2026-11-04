# Team Ghost sample-app 배포

기존 Argo Rollout의 카나리·분석 흐름을 유지하면서 본선 DB API 이미지를 연결한다.
이 파일들은 GitOps 선언이며 실제 클러스터에 적용하거나 DB를 변경하지 않았다.

## 대상 환경

| Overlay | Namespace | Argo CD Application | 분석 소스 |
| --- | --- | --- | --- |
| `overlays/aws` | `sample-app` | `argocd/sample-app-aws.yaml` | `analysis/prometheus` |
| `overlays/local` | `sample-app` | `argocd/sample-app-local.yaml` | `analysis/default` |
| `overlays/onprem` | `hackathon` | `argocd/onprem/sample-app.yaml` | `analysis/onprem` |

본선 홈랩은 `onprem`이다. 이전 예선용 `local`과 네임스페이스·클러스터 등록이
다르다. `onprem`에는 Ingress가 없으며 앱의 기존 Service로 접근한다.
사용자에게 노출할 공통 진입점과 라우팅은 별도 인프라 작업이다.
GCP 파일은 삭제하지 않았으며 이번 DB 통합 대상에 포함하지 않았다.

## 이미지와 CI

이미지는 `ghcr.io/softbankhackathon2026/sample-app`이다.
CI는 이미지를 먼저 푸시한 뒤 아래 파일의 해당 이미지 `newTag`만 갱신한다.

```text
apps/sample-app/base/kustomization.yaml
```

`newTag`의 초기 값은 복제한 기존 앱 커밋이다. 새 DB 모듈을 포함한 이미지가
실제로 GHCR에 푸시된 뒤 그 커밋으로 갱신해야 한다. 이 브랜치의 설정만
먼저 적용하면 새 readiness API를 제공하지 않는 이미지가 배포될 수 있다.

## DB 준비

각 환경의 해당 namespace에 `sample-app-db` Secret이 필요하다.
`database-url` 키에는 환경별 앱 DB 계정의 PostgreSQL URL을 저장한다.
앱 역할은 스키마 소유자가 아니며 `public.migration_demo`의 SELECT·INSERT만
허용한다. 테이블과 권한은 앱 배포 전에 명시적으로 준비한다.
Secret 값은 이 저장소에 커밋하지 않는다.

AWS는 `PGSSLMODE=verify-full`이며 `sample-app-db-ca` Secret의 `ca.pem`을
`/db-ca/ca.pem`으로 마운트한다. 해당 RDS 서버 인증서를 검증할 CA를 넣는다.
Secret은 네임스페이스 단위이므로 다른 환경에 자동 복사되지 않는다.
로컬과 온프렘 데모는 사설 연결에서 `PGSSLMODE=disable`을 사용한다.
TLS를 제공하는 홈랩은 해당 overlay에 검증 CA와 TLS 설정을 명시해 사용한다.

```sh
# 접속 문자열 자체를 셸 기록에 넣지 않고 준비된 파일에서 읽는 예시.
kubectl -n sample-app create secret generic sample-app-db \
  --from-file=database-url=/secure/aws-database-url
kubectl -n sample-app create secret generic sample-app-db-ca \
  --from-file=ca.pem=/secure/rds-ca.pem
kubectl -n hackathon create secret generic sample-app-db \
  --from-file=database-url=/secure/onprem-database-url
```

## 헬스체크와 쓰기 제어

AWS·local·onprem의 readiness는 `/readyz`, liveness는 `/healthz`다.
DB 연결·테이블 조회가 실패하면 새 트래픽에서 제외하지만 DB 장애만으로
프로세스를 계속 재시작하지 않는다. `FAIL_RATE=0`이며 예선 `APP_NOTICE`
Secret 의존성을 제거했다. AWS ALB의 대상 헬스체크도 `/readyz`다.

`sample-app-control` ConfigMap의 `control.json`은 기본
`{"writes_paused":false}`다. 안정된 이름과 디렉터리 마운트로 파일 변경을
프로세스 재시작 없이 받는다. 쓰기를 정지하려면 Git에서 이 파일 값을
변경하고 동기화 후 모든 replica의 `/api/info` 상태를 확인해야 한다.
ConfigMap projection은 즉시 반영되지 않는다.

Argo CD는 `selfHeal`을 사용하므로 `kubectl patch`만으로 정지한 상태는 Git의
값으로 복원될 수 있다. 전환 제어는 선언과 상태를 함께 관리해야 한다.
파일 정지는 해당 앱 프로세스의 쓰기만 막으며 DB 권한 차단·진행 중
트랜잭션 정리·CDC 완료 검증을 대신하지 않는다.

## 트래픽 봇

새 영속 HTTP 봇의 배포 선언은 `sample-app` 저장소의 `k8s/traffic-bot`에 있다.
이 저장소의 기존 예선 `apps/loadgen`과 `argocd/sample-app-loadgen-aws.yaml`은
조회 전용 봇이므로 DB 저장·왕복 이전 검증용으로 간주하지 않는다.
두 봇을 동시에 실행해 측정 결과를 혼합하지 않도록 운영자가 구분한다.

## 로컬 렌더 검증

```sh
kubectl kustomize apps/sample-app/overlays/aws
kubectl kustomize apps/sample-app/overlays/local
kubectl kustomize apps/sample-app/overlays/onprem
kubectl kustomize apps/sample-app/analysis/onprem
```

Argo Rollouts·AnalysisTemplate CRD, 각 클러스터 등록, Prometheus, Secret과
실제 접속·권한은 렌더 성공만으로 검증되지 않는다.
