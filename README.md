# gitops

![전체 흐름에서 gitops 의 자리](docs/architecture.png)

> 위 그림 ③ 의 **"gitops 레포에 커밋"** 과 **Argo CD** 가 이 레포입니다. 검토를 통과한 명세와 CI 가 빌드한 이미지 태그가 여기로 모이고, Argo CD 가 각 환경에 배포합니다.
> 그림 원본은 [docs/architecture.excalidraw](docs/architecture.excalidraw) (Excalidraw).

Argo CD가 바라보는 배포 설정 레포입니다. 앱 레포의 CI가 이미지 태그를 갱신하면 Argo CD가 각 클러스터에 자동으로 동기화합니다. **사람이 이 레포를 직접 고치는 일은 거의 없습니다.**

```
apps/sample-app/
  base/                      공통 Rollout·Service (이미지 태그는 CI가 갱신)
  analysis/default/          응답 분석 (로컬·GCP Application의 두 번째 source)
  analysis/prometheus/       응답·Prometheus 에러율 분석 (AWS의 두 번째 source)
  overlays/local/            부산 로컬 (k3s)
  overlays/aws/              서울 (EKS, ap-northeast-2)
  overlays/gcp/              도쿄 (GKE, asia-northeast1)
apps/review-service/         검토 서비스. AWS EKS platform 네임스페이스 전용
                             Review API · 워커 · Qdrant · 시크릿 · 플랫폼 ALB 연결
apps/loadgen/aws/            카나리 분석이 "볼 것"을 만드는 부하 장치 (AWS 전용)
argocd/                      클러스터별 Argo CD Application
  install/                   Argo CD · Argo Rollouts 설치 순서와 버전, 재조회 주기
  notifications/             배포 결과를 검토 서비스로 보내는 설정
scripts/loadgen.sh           같은 일을 노트북에서. 클러스터 접근 없이 공개 주소로 쏜다
```

렌더링 확인: overlay와 해당 Application의 두 번째 `analysis/` source를 각각 `kubectl kustomize`로 확인합니다. overlay만 렌더링하면 AnalysisTemplate이 포함되지 않습니다.

## 누가 이 레포에 커밋하나

세 곳이 커밋합니다. 같은 시점에 겹칠 수 있어 **push 충돌 시 재시도**가 모두 들어가 있습니다.

| 누가 | 무엇을 |
| --- | --- |
| sample-app CI | `apps/sample-app/base` 의 이미지 태그 |
| review-service CI | `apps/review-service` 의 이미지 태그 |
| `commit_overlay` (검토 워커) | 검토를 통과한 명세로 만든 `overlays/<env>/` |

## 배포 방식

### 카나리 — 절반만 먼저 내보낸다

```
새 이미지 → 50% (복제본이 3개면 새 버전 2개 + 옛 버전 1개)
         → 약 30초 동안 앱 응답 확인 (api-ok, 5초마다 6번)
         → 통과하면 100%, 실패하면 중단하고 되돌림
```

2026-10-10 [PR #45](https://github.com/Crystal-SBHackathon2026/gitops/pull/45)에서 분석을 분리했습니다. AWS 카나리는 `analysis/prometheus`의 `api-ok`·`error-rate`, 로컬 카나리는 `analysis/default`의 `api-ok`를 사용합니다. [PR #48](https://github.com/Crystal-SBHackathon2026/gitops/pull/48)의 GCP 데모 overlay는 블루그린이며 현재 전환 전후 Analysis를 실행하지 않습니다. GCP Application도 `analysis/default`를 배포하지만 템플릿 존재만으로 분석 실행을 검증했다고 판단하지 않습니다.

공통 카나리 단계는 `apps/sample-app/base/rollout.yaml`, 확인 기준은 `analysis/default`·`analysis/prometheus`에 있습니다. 명세의 `rollout.strategy`가 `canary`면 공통 전략을 쓰고, `bluegreen`이면 렌더러가 전략을 바꿉니다. 현재 GCP 데모 overlay는 수동 블루그린 구성입니다.

당시 두 지표를 함께 둔 이유는 각자 못 보는 게 있기 때문입니다.

| | 잡는 것 | 못 잡는 것 |
| --- | --- | --- |
| `api-ok` (앱을 직접 부름) | 응답이 **계속** 틀린 경우 — 잘못된 이미지, 설정 오류 | 일부 요청만 실패하는 경우. Service 가 카나리·안정 파드를 함께 가리켜 요청이 번갈아 가므로 연속 오류가 잘 안 생긴다 |
| `error-rate` (Prometheus) | **부분 에러율** — "새 버전이 10% 요청만 500 을 준다" | 트래픽이 없으면 아무것도 못 본다 |

### 트래픽이 없으면 판정을 못 한다

`error-rate` 는 비율이라 **분모(요청 수)가 없으면 판단할 근거가 없습니다.** 요청이 하나도 없으면 분자 0 · 분모 0 이고, 템플릿의 `clamp_min` 이 분모를 `0.001` 로 바꿔 결과가 0 이 됩니다. 기준 0.05 이하라 **통과**합니다. `clamp_min` 은 반대 사고(트래픽 없는 멀쩡한 배포가 `NaN` 때문에 전부 중단되던 것, [#39](https://github.com/Crystal-SBHackathon2026/gitops/issues/39))를 막으려고 일부러 넣은 것인데, 그 보호 안에 **실패를 못 보는 눈먼 구간**이 같이 들어 있습니다.

2026-10-10 에 같은 장애 주입으로 두 번 재서 확인했습니다. 차이는 설정이 아니라 트래픽뿐이었습니다.

| | 요청 | 측정값 | 결과 |
| --- | --- | --- | --- |
| [sample-app #42](https://github.com/Crystal-SBHackathon2026/sample-app/pull/42) | 없음 | `[0] [0] [0] [0]` | 통과 → **30% 실패 버전이 100% 승격** |
| [sample-app #46](https://github.com/Crystal-SBHackathon2026/sample-app/pull/46) | 0.5초마다 | `[0.24] …` | 2번째 Failed 에서 **자동 중단** |

그래서 분석 창 동안 요청이 끊기지 않도록 부하 장치를 둡니다. 시연 때는 이용자 화면의 자동 새로고침이 그 역할을 하지만, 그 화면이 꺼지거나 탭이 백그라운드로 넘어가면 안전장치가 통째로 안 돕니다. 사람 손에 걸어 둘 일이 아닙니다.

| | 어디서 도나 | 언제 쓰나 |
| --- | --- | --- |
| `apps/loadgen/aws/` | 클러스터 안 (Deployment 1개, 약 5 요청/초) | 항상. 전용 Application 이 관리하므로 지우면 바로 꺼진다 |
| `scripts/loadgen.sh` | 노트북 | 리허설·시험. 1초마다 현재 에러율을 찍어 줘서 중단되는 순간이 눈에 보인다 |

🔴 `overlays/` 안에 두지 않았습니다. overlay 는 렌더러가 배포마다 다시 만드는 생성물이라 손으로 넣은 것이 지워집니다.

`error-rate` 는 `rollouts_pod_template_hash` 로 **카나리 파드만** 골라서 잽니다. 카나리 중에는 새 파드와 옛 파드가 같은 Service 뒤에 함께 있어서, 이 라벨이 없으면 지표가 섞여 "새 버전만 에러가 난다" 가 희석됩니다.

#### 에러율 분석의 트래픽 조건 — AWS

`/healthz` 를 일부러 뺐습니다. readiness·liveness 가 5초·10초마다 때리므로 섞으면 사용자 요청의 실패가 묻힙니다. 실측하니 전체 0.87 req/s 가 전부 헬스체크였고 사용자 요청은 0 req/s 였습니다.

**데모에서 부분 실패를 보여주려면 카나리가 도는 동안 요청을 넣어야 합니다.** 위의 부하 장치가 그것을 상시로 합니다. 리허설에서 눈으로 보려면 노트북 쪽을 씁니다.

```bash
./scripts/loadgen.sh          # 서울 (부산은 local)
SECS=90 ./scripts/loadgen.sh  # 90초만 돌리고 요약
```

트래픽이 없을 때는 **배포를 막지 않습니다**(측정값 0 으로 통과). 아무도 안 쓰는 앱의 배포를 세워두는 것보다 낫다고 봤습니다.

#### 에러율 분석의 초기 측정 지연 — AWS

`rate` 는 창 안에 표본이 **2개 이상** 있어야 값을 냅니다. 10초마다 긁으니 갓 뜬 카나리 파드는 **20초**가 지나야 측정이 됩니다. 그 전 측정은 `clamp_min` 덕에 `0` 으로 통과하므로 **실패를 놓칩니다.**

`FAIL_RATE: 0.3` 주입 실험(2026-10-09)에서 그대로 나왔습니다.

```
측정 1 (t=0s)    [0]        ← 버려진 측정
측정 2 (t=10s)   [0]        ← 버려진 측정
측정 3 (t=20s)   [0.236]    ← 여기서부터 실제 값
측정 4 (t=30s)   [0.293]    → 2번째 Failed → 중단
```

PR #41에서 `initialDelay: 20s`를 두고 `count`를 6 → 4로 줄였습니다. 분석 전체 길이는 당시 약 60초 그대로였고(그 길이는 `api-ok`가 정합니다), 초기 측정의 빈 구간을 피하려는 보완이었습니다. PR #42에서 공통 지표를 제거한 뒤 #45에서 AWS 전용 분석으로 복원했습니다. 현재는 [PR #54](https://github.com/Crystal-SBHackathon2026/gitops/pull/54)로 **분석 창이 30초**입니다(`api-ok` 5초×6, `error-rate` 초기 10초 + 5초×4). 긁는 주기를 5초로 내려서 가능해졌습니다 — 재는 간격이 긁는 주기보다 짧으면 같은 값을 두 번 읽습니다.

같은 실험에서 `api-ok` 는 **6회 전부 통과**했습니다. 한 번에 한 요청만 보내므로 30% 확률의 실패로는 중단 조건(3번 연속 Error)에 닿지 않습니다. 지표를 둘 둔 이유가 그것입니다.

#### Prometheus 가 없는 환경의 오류와 조치

공통 `error-rate` 는 Prometheus 접근이 필요합니다. 2026-10-09 GKE Rollouts v1.10.0에서 이 지표만 실행한 결과, `count=6`, `consecutiveErrorLimit=6`이어도 DNS 오류가 7회 누적되어 AnalysisRun이 `Error`로 종료됐습니다. 두 값을 같게 두는 것으로 측정 오류를 무시할 수 없습니다.

성진님이 로컬의 동일 오류와 PR #42 적용 후 abort 해제를 보고했습니다. 현재 #45에서는 AWS에만 Prometheus 지표를 두므로 GCP에 Prometheus를 추가 설치하지 않습니다. GCP 앱 배포·후속 블루그린 전환 성공은 별도로 검증해야 합니다. [GKE 검증 기록](docs/gcp-gke-verification-2026-10-09.md)을 참고하세요. 공통 카나리·블루그린 구현은 성진님의 변경을 재사용합니다.

### 헬스체크 실패 시 자동 롤백

새 버전이 60초(`progressDeadlineSeconds`) 안에 헬스체크(`/healthz`)를 통과하지 못하면 배포를 중단하고 기존 버전을 계속 서비스합니다. 카나리 분석과 별개로 동작하는 더 바깥의 안전장치입니다.

### 명세에 없는 리소스는 지워진다

`commit_overlay`가 갱신하는 `overlays/<env>/`는 **생성물**입니다. 명세로 다시 만들면서, 이전에 있었는데 새 명세에 없는 파일은 지웁니다. 남겨두면 kustomize가 없는 리소스를 참조하기 때문입니다. 현재 GCP 블루그린 데모처럼 수동 구성한 overlay도 있어, 후속 명세의 대상 환경과 렌더러 출력을 확인한 뒤 갱신해야 합니다.

> ⚠️ 2026-10-09에 이것 때문에 장애가 있었습니다. 명세가 없는 PR에서 축소된 명세가 자동 생성·병합되어 `ingress.yaml` 이 지워지고, Argo CD prune → ALB까지 삭제됐습니다. 지금은 **기존 overlay의 Ingress가 사라지는 변경을 `commit_overlay` 가 `blocked` 로 막습니다.**

## 설치

버전과 순서는 [argocd/install/README.md](argocd/install/README.md)를 따릅니다. Argo CD **v3.5.4**, Argo Rollouts **v1.10.0** 으로 고정합니다. `stable`·`latest` 를 쓰면 환경마다 버전이 달라집니다.

배포 결과를 검토 서비스로 보내는 설정은 [argocd/notifications/README.md](argocd/notifications/README.md)에 있습니다.

생성된 도쿄 GKE의 Rollouts·배포 RBAC와 중앙 EKS 등록 절차는 [GKE 연결 문서](argocd/install/gke/README.md)를 따릅니다. 설치 완료와 실제 앱·알림 연결 완료를 구분합니다.

도쿄 active Service의 HTTP 공개 경로, 5050 서버 프록시 연결과 승격 전후·운영 종료 검증은 [GCP 외부 접속 운영 안내](docs/gcp-public-service.md)를 따릅니다.

명세 기반 공개 Service의 기존 renderer 호환성·삭제 보호 검사와 활성화 선행 조건은 [2026-10-11 공개 명세 검증 기록](docs/gcp-public-spec-verification-2026-10-11.md)에 있습니다. 운영 공개 경로 검증과 향후 다중 환경 활성화를 구분합니다.

## Application 목적지

| 파일 | 목적지 | 상태 |
| --- | --- | --- |
| `sample-app-aws.yaml` | `https://kubernetes.default.svc` | 적용됨. Argo CD가 EKS 안에 있어 in-cluster가 맞습니다 |
| `review-service-aws.yaml` | `https://kubernetes.default.svc` | 적용됨 |
| `sample-app-local.yaml` | `name: crystal-busan` | 로컬 자체 Argo CD에 등록해 사용합니다. [로컬 절차](argocd/install/README.md#로컬부산-k3s-환경) |
| `sample-app-gcp.yaml` | `name: tokyo-gke` | 2026-10-11 01:10 KST에 Synced/Healthy·최신 이미지 Pod 2개 Ready와 `http://34.85.123.113`의 health/info HTTP 200·gcp/asia-northeast1·버전 일치를 확인했습니다. 5050 화면·새 preview 승격 전후 전환은 [#66](https://github.com/Crystal-SBHackathon2026/gitops/issues/66)의 공동 검증으로 남아 있습니다 |

**운영 모델에 따라 `local`·`gcp` 의 값이 달라집니다.**

- **EKS의 Argo CD 하나로 세 환경을 관리**하면 → 클러스터를 Argo CD에 등록하고 그 주소(또는 `destination.name` 으로 등록한 이름)를 넣습니다
- **환경마다 Argo CD를 따로 설치**하면 → 그 클러스터 안에서는 `https://kubernetes.default.svc` 가 맞습니다

> ⚠️ 하나로 관리하면서 `local` 에 `kubernetes.default.svc` 를 넣으면 **로컬 설정이 EKS에 배포됩니다.** 네임스페이스가 둘 다 `sample-app` 이라 `aws` overlay와 같은 Rollout·Service·Ingress를 서로 밀어냅니다.

## 로컬(부산) 환경 실행

k3d 클러스터 안에 Argo CD를 따로 설치하는 방식입니다. 이 경우 Application의 목적지는 그 클러스터 자신입니다.

```bash
k3d cluster create crystal-busan --agents 1 -p "127.0.0.1:8081:80@loadbalancer"

kubectl create namespace argocd
kubectl apply -n argocd --server-side \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/install.yaml
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts --server-side \
  -f https://github.com/argoproj/argo-rollouts/releases/download/v1.10.0/install.yaml

# argocd/install/README.md의 로컬 절차로 이 Argo CD에 crystal-busan을 먼저 등록한다.
kubectl apply -f argocd/sample-app-local.yaml
```

접속: http://localhost:8081

포트를 `127.0.0.1:` 로 묶은 이유는, 그냥 `8081:80` 으로 두면 모든 인터페이스에 열려 같은 네트워크의 다른 기기에서도 접속되기 때문입니다. 다른 기기로 시연할 계획이면 이 접두어를 빼야 합니다.

Windows에서 kubectl 연결이 안 되면: `kubectl config set-cluster k3d-crystal-busan --server=https://127.0.0.1:<포트>`

**카나리 분석이 로컬에서도 돌려면** 그 클러스터에 Argo Rollouts가 설치돼 있어야 합니다. `AnalysisTemplate`은 Application의 두 번째 source인 `analysis/default`에서 함께 배포합니다.

로컬은 `api-ok`만 사용하는 `analysis/default`를 선택합니다. Prometheus가 없는 환경에서 AWS의 `analysis/prometheus`를 선택하면 분석이 실패할 수 있습니다.

## 현재 조직의 저장소 연결

Argo CD Application의 repoURL은 `https://github.com/SoftBankHackathon2026/gitops.git`이다. review-service의 intake 대상은 `SoftBankHackathon2026/sample-app`이다. 검토 서비스의 실제 소스는 원본 `Crystal-SBHackathon2026/review-service`에 있다.

기존 GHCR 이미지 태그는 공개 manifest를 확인했다. sample-app이 Docker Hub로
옮기기 전의 기록이다. sample-app 이미지는 이제 Docker Hub 공개 저장소
`docker.io/kty1021/sample-app`의 커밋 전체 SHA 태그다. 첫 태그
`dda34482ed5106e90e7bcce358015e8cda0f7002`는 손으로 게시한 부트스트랩
이미지다. 이후에는 sample-app CI가 새 이미지를 push한 뒤 base Kustomization의
newTag를 갱신한다. 자세한 내용은
[apps/sample-app/README.md](apps/sample-app/README.md)에 있다. review-service
이미지와 독립 loadgen의 고정 이미지는 새 이미지가 확인되기 전까지 유지한다.
과거 PR/이슈 링크는 기록의 실제 위치이므로 일괄 치환하지 않는다.

마이그레이션 데이터 토픽은 공유 브로커 기본값에 맡기지 않는다. Kafka CLI가 설치된 관리 환경에서 아래처럼 작업별로 생성한다. 실제 접속값·인증 파일·복제 계수는 사용하는 브로커에 맞춘다.

```bash
KAFKA_BOOTSTRAP='<reachable-brokers>' TOPIC_PREFIX=forward_001 REPLICATION_FACTOR=1 \
  bash scripts/create-migration-topic.sh
```

MSK 두 브로커 구성이면 요구에 맞는 복제 계수(예: 2)를 지정한다. 인증이 필요하면 `KAFKA_COMMAND_CONFIG`로 클라이언트 속성 파일을 지정한다. 귀환에는 `return_001` 등 새 prefix를 사용한다. 이미 존재하는 토픽의 파티션 수가 1이 아니면 스크립트는 중단한다. 이 스크립트는 connector 자체를 배포하지 않는다.
