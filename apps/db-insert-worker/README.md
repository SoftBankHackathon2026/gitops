# db-insert-worker

초당 1건을 현재 활성 DB 에 INSERT 하는 워커 1개. 전환 시연에서 "앱 쓰기" 역할을 한다. 온프렘 k3s `hackathon` 네임스페이스 전용이며 Argo CD Application 은 [argocd/onprem/db-insert-worker.yaml](../../argocd/onprem/db-insert-worker.yaml).

```
configmap.yaml    migration-config — config.yaml (onprem/aws 대상, 작업 이름, Kafka·Connect 주소)
pvc.yaml          요청 기록 1Gi (local-path). DB 에 보내기 전에 먼저 적는 영속 대기열
deployment.yaml   Deployment 1개, Recreate. migration.loadgen
service.yaml      HTTP 8080 — /healthz /status /metrics
```

## 선행 조건

1. Secret `migration-db-credentials` 의 `app_password` — 만드는 법은 [migration-db-init/README.md](../migration-db-init/README.md).
2. `migration-db-init` 이 `migration_demo` 와 `migration_app` 역할을 만들어 둔 상태. 없으면 readiness 가 계속 실패한다.

## 환경변수 (Hackathon 저장소 `migration/` 과 맞춘 값)

| 변수 | 값 | 어디서 |
| --- | --- | --- |
| `PGHOST PGPORT PGDATABASE PGUSER PGSSLMODE` | `postgres 5432 migration_demo migration_app require` | deployment.yaml |
| `MIGRATION_APP_PASSWORD` | Secret `migration-db-credentials` / `app_password` (접속 호스트·사용자는 config.yaml) | deployment.yaml |
| `WORKER_RATE` | `1` | deployment.yaml |
| `WORKER_RUN_ID` / `WORKER_PHASE` / `WORKER_TARGET` | `forward_001` / `onprem_live` / `onprem` | deployment.yaml (시작값, 도구가 바꾼다) |
| `WORKER_STATE_DIR` | `/var/lib/worker` (PVC) | deployment.yaml |
| `MIGRATION_CONFIG` | `/etc/migration/config.yaml` (ConfigMap) | configmap.yaml |

## 미확정 값

- `config.yaml` 의 `targets.aws.host` 는 새 계정 RDS(`oneaction-review-db.cdb6j7l51obe.ap-northeast-2.rds.amazonaws.com`)다.
- `config.yaml` 의 키 구조는 이 저장소 쪽 제안이다. `migration/` 구현이 다른 키를 읽으면 그쪽에 맞춘다.
- 실행 UID 1000. 이미지가 `/var/lib/worker` 와 `/tmp` 외에 쓰는 곳이 있으면 `readOnlyRootFilesystem` 때문에 실패한다 — 그때는 emptyDir 를 더 붙인다.

## 확인

```bash
kubectl -n hackathon get pod,pvc -l app.kubernetes.io/name=db-insert-worker
kubectl -n hackathon exec deploy/db-insert-worker -- python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/status').read().decode())"
```

멈추려면 `kubectl -n hackathon scale deploy/db-insert-worker --replicas=0`. Argo CD selfHeal 이 1 로 되돌리므로 오래 끌 거면 Application 을 지우거나 이 파일의 replicas 를 바꿔 커밋한다.

## 리허설 (AWS 없이 전체 사이클)

`migration-config` 의 두 번째 키 `config.rehearsal.yaml` 은 같은 Postgres 안의 빈 DB `migration_demo_rehearsal`(target `rehearsal`)을
대상으로 `rehearsal_001` 작업을 정의한다. 워커 파드에 `/etc/migration/config.rehearsal.yaml` 로 마운트되므로 그 파드에서
`python -m migration.init_db|cdc|cutover|verify --config /etc/migration/config.rehearsal.yaml` 을 돌린다(관리자 비밀번호는
실행 시 환경변수로만 준다). 워커가 `rehearsal` target 을 알려면 ConfigMap 반영 뒤 워커 파드를 한 번 재시작한다.
RDS 가 생기면 `config.yaml`(forward_001, 대상 aws)로 같은 절차를 반복한다.

## AWS 실전 (`config.aws.yaml`, 2026-11-05)

리허설 전환(rehearsal_001) 뒤 앱·봇·워커가 모두 `migration_demo_rehearsal` 에 쓰고 있고 `migration_demo` 는
앱 INSERT 가 차단된 상태라, 실제 AWS 전환은 **원본 `rehearsal` → 대상 `aws`(RDS)** 로 돈다
(`job_id: forward_001`, `live_phase_before: rehearsal_live`, `live_phase_after: aws_live`).
`config.yaml`(onprem→aws) 은 `migration_demo` 를 다시 라이브로 되돌릴 때만 쓴다.

```
python -m migration.cutover --config /etc/migration/config.aws.yaml --state-dir /var/lib/worker run
```
