# migration-db-init

`migration_demo` 데이터베이스·테이블·네 역할(`migration_app`, `migration_cdc`, `migration_sink`, `migration_verify`)을 만드는 일회성 Job. 온프렘 k3s `hackathon` 네임스페이스 전용이며 Argo CD Application 은 [argocd/onprem/migration-db-init.yaml](../../argocd/onprem/migration-db-init.yaml).

```
configmap.yaml        비밀 아닌 설정 (DB·역할·작업 이름, config.yaml). 이게 바뀌면 Job 이 다시 돈다
job.yaml              Argo CD Sync 훅 Job. migration.init_db --target onprem
secret.example.yaml   Secret 키 목록. 값은 넣지 않는다
job-aws.manual.yaml   수동 Job. migration.init_db --target aws (RDS 생긴 뒤 사람이 apply, Argo 는 안 읽음)
```

## 선행 조건 — Secret 을 먼저 만든다

이 클러스터에는 외부 Secret 관리(ESO)가 없다. 아래 명령으로 직접 만든다. 값은 자리표시자다.

```bash
kubectl -n hackathon create secret generic migration-db-credentials \
  --from-literal=app_password='<migration_app 비밀번호>' \
  --from-literal=cdc_password='<migration_cdc 비밀번호>' \
  --from-literal=sink_password='<migration_sink 비밀번호>' \
  --from-literal=verify_password='<migration_verify 비밀번호>'
```

슈퍼유저 자격은 이미 있는 `review-db-credentials`(keys `username`, `password`)를 쓴다. 새로 만들지 않는다.

## 다시 돌리기

```bash
argocd app sync migration-db-init          # 또는 Argo CD UI 의 Sync
kubectl -n hackathon logs job/migration-db-init
```

훅이라 sync 마다 돈다. 도구가 멱등이어야 하는 이유다. 이미지 태그만 바뀐 경우는 훅이 diff 에서 빠져 자동 sync 가 안 일어나므로 위 명령으로 직접 돌린다.

## 다른 저장소와 맞춘 값

| 항목 | 값 |
| --- | --- |
| 이미지 | `ghcr.io/softbankhackathon2026/migration-tools` (Hackathon 저장소 `migration/`), ENTRYPOINT `python -m` |
| 명령 | `migration.init_db --target onprem` |
| 접속 | config.yaml `targets.onprem` (host postgres, admin_dbname postgres, users.admin.user oneaction_admin), `MIGRATION_ADMIN_PASSWORD` ← `review-db-credentials`/`password` |
| 역할 비밀번호 | `MIGRATION_APP_PASSWORD`, `MIGRATION_CDC_PASSWORD`, `MIGRATION_SINK_PASSWORD`, `MIGRATION_VERIFY_PASSWORD` ← `migration-db-credentials` |
| 실행 UID | 1000 (`runAsUser`). 이미지가 어떤 USER 로 빌드되든 이 UID 로 돈다 — 홈 디렉터리 쓰기에 의존하면 안 된다 |

## AWS(RDS) 쪽 초기화 — 수동

RDS 는 VPC·Tailscale 경로가 생긴 뒤에만 닿으므로 Sync 훅으로 두지 않는다. `job-aws.manual.yaml` 머리말의 순서대로
Secret `migration-aws-admin`(key `password`, RDS 마스터 비밀번호)을 만들고 직접 apply 한다. 같은 Secret 이름을
귀환 사전 점검 Job(`apps/migration-return/job-precheck.manual.yaml`)도 쓴다.
