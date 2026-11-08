# argocd/onprem — 온프렘 k3s(oneport-onprem) 의 Argo CD Application 모음

이 디렉터리는 **루트 Application(app-of-apps)이 디렉터리 소스로 읽는다.** kustomization.yaml 이 없고 Application yaml 을 나열만 한다. 여기에 yaml 을 더하면 루트 앱이 자동으로 등록하고, 지우면 prune 한다.

```
루트 Application (팀원이 손으로 한 번 등록)
  project hackathon · source argocd/onprem · destination argocd
  ├─ sample-app.yaml         sample-app-onprem   → apps/sample-app/overlays/onprem + analysis/onprem
  ├─ migration-db-init.yaml  migration-db-init   → apps/migration-db-init   (ConfigMap 만. init Job 은 수동, 2026-11-08)
  ├─ migration-cdc.yaml      migration-cdc       → apps/migration-cdc       (Kafka Connect)
  ├─ migration-policy.yaml   migration-policy    → apps/migration-policy    (OPA 정책 판정)
  └─ db-insert-worker.yaml   db-insert-worker    → apps/db-insert-worker    (INSERT 워커)
```

다섯 Application 모두 `project: hackathon`, `destination: https://kubernetes.default.svc / hackathon`, automated sync(prune·selfHeal), `CreateNamespace=false`. 네임스페이스 스코프 리소스만 쓴다 — AppProject 가 클러스터 스코프를 막는다.

## 선행 조건 (클러스터에서 팀원이 한다)

### 1. Secret `migration-db-credentials`

외부 Secret 관리(ESO)가 없어 직접 만든다. 세 Application 이 모두 이 Secret 을 참조하므로 **루트 앱 등록 전에** 만든다. 없으면 Job 은 CreateContainerConfigError, Deployment 는 파드가 못 뜬다.

```bash
kubectl -n hackathon create secret generic migration-db-credentials \
  --from-literal=app_password='<migration_app 비밀번호>' \
  --from-literal=cdc_password='<migration_cdc 비밀번호>' \
  --from-literal=sink_password='<migration_sink 비밀번호>' \
  --from-literal=verify_password='<migration_verify 비밀번호>'
```

키 목록은 [apps/migration-db-init/secret.example.yaml](../../apps/migration-db-init/secret.example.yaml). 슈퍼유저 자격 `review-db-credentials` 는 이미 있다.

### 2. AppProject `hackathon` 의 destination

2026-11-03 확인 기준 AppProject `hackathon` 의 destination 은 `hackathon` 네임스페이스 하나다. 루트 Application 은 `argocd` 네임스페이스에 자식 Application 을 만들므로, **루트 앱만은 destination `argocd` 가 허용돼야 한다.** 두 가지 중 하나다.

- AppProject `hackathon` 의 `spec.destinations` 에 `{server: https://kubernetes.default.svc, namespace: argocd}` 를 더한다 (Argo CD 관리자 권한 필요), 또는
- 루트 앱만 `project: default` 로 등록한다. 자식 Application 은 그대로 `project: hackathon` 이라 격리는 유지된다.

이 저장소는 둘 중 어느 쪽도 결정하지 않는다. 어느 쪽이든 자식 네 개의 파일은 바뀌지 않는다.

> 2026-11-03: 관리자가 첫 번째 방법(destination `argocd` 추가)으로 처리했고, 루트 앱은 `hackathon-root` 이름으로 등록돼 있다.

### 3. 루트 Application 등록

```bash
kubectl -n argocd apply -f - <<'ROOT'
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: onprem-root
  namespace: argocd
spec:
  project: hackathon            # 위 2번에 따라 default 일 수 있다
  source:
    repoURL: https://github.com/SoftBankHackathon2026/gitops.git
    targetRevision: main
    path: argocd/onprem
    directory:
      recurse: false
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
ROOT
```

위 예시는 이 디렉터리에 두지 않았다. 루트 앱이 자기 자신을 관리하면 삭제가 꼬인다.

### 4. 손으로 등록한 `hackathon-sample-app` 정리

> 2026-11-03 완료. cascade 없이 지웠고, 그 앱에만 있던 알림 annotation 은 `sample-app.yaml` 로 옮겼다.

`sample-app-onprem` 이 Synced·Healthy 가 된 것을 확인한 뒤 옛 Application 을 지운다. 둘이 같은 Rollout·Service 를 관리하면 SharedResourceWarning 이 나고 selfHeal 이 서로를 되돌린다.

```bash
kubectl -n argocd get application sample-app-onprem
# 🔴 cascade 를 끈다. 리소스는 sample-app-onprem 이 이어받는다 — 지우면 안 된다.
kubectl -n argocd patch application hackathon-sample-app --type json \
  -p '[{"op":"remove","path":"/metadata/finalizers"}]' 2>/dev/null || true
kubectl -n argocd delete application hackathon-sample-app
```

## 적용 순서

Application 끼리 순서를 강제하지 않는다. 동시에 올라가도 결국 수렴하지만, 처음에는 이 순서가 조용하다.

1. Secret 생성 (위 1번)
2. 루트 앱 등록 → 네 Application 이 생긴다
3. `migration-db-init` Synced 확인 — `kubectl -n hackathon logs job/migration-db-init`
4. `migration-cdc`, `db-insert-worker` Healthy 확인
5. 데이터 토픽 생성 — [scripts/create-migration-topic.sh](../../scripts/create-migration-topic.sh)
6. 커넥터 등록·seed 는 도구(`migration.cdc`, `migration.seed`)가 한다. 이 저장소 밖이다.

## 리소스 합계 (ResourceQuota `hackathon-quota` 와 비교)

| | requests.cpu | requests.memory | limits.memory | storage | PVC |
| --- | --- | --- | --- | --- | --- |
| migration-db-init (실행 중일 때만) | 50m | 64Mi | 256Mi | – | – |
| migration-cdc | 100m | 768Mi | 1.5Gi | – | – |
| db-insert-worker | 50m | 64Mi | 256Mi | 1Gi | 1 |
| migration-policy (×2) | 50m | 128Mi | 512Mi | – | – |
| 합계 | 250m | 1Gi | ~2.5Gi | 1Gi | 1 |
| 2026-11-03 여유 | 1.7 | 2.2Gi | ~4.9Gi | 5Gi | 7 |

sample-app 은 이미 올라가 있던 것이라 더 쓰지 않는다.

## 미확정 값 (다른 저장소·팀원과 맞춘다)

| 값 | 어디 | 지금 |
| --- | --- | --- |
| 이미지 태그 | `apps/*/kustomization.yaml` `images[].newTag` | `main` 자리표시자. CI 가 SHA 로 바꾸거나 사람이 고정 |
| AWS DB 호스트 | `apps/db-insert-worker/configmap.yaml`, `apps/migration-db-init/configmap.yaml` | `REPLACE_WITH_AWS_DB_HOST` |
| `config.yaml` 키 구조 | 같은 두 파일 | 이 저장소 쪽 제안. `migration/` 구현이 읽는 키에 맞춘다 |
| 워커 명령 | `apps/db-insert-worker/deployment.yaml` `args` | `migration.loadgen` 으로 가정 |
| 워커·Job 실행 UID | `runAsUser: 1000` | 이미지가 다른 UID 를 전제하면 맞춘다 |
