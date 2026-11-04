# migration-policy

OPA 서버 2개(무상태). 이전 실행 제어기(`migration.cutover`)와 관리 API 가 단계 직전에
`POST http://migration-policy:8181/v1/data/ghost/migration/decision` 으로 판정을 묻는다.
정책 본문·입력 계약·예시는 Hackathon 저장소 `policies/`, 호출 쪽은 `migration/migration/policy_client.py`.

```
deployment.yaml   OPA run --server. 정책은 이미지(ghcr.io/softbankhackathon2026/migration-policy)에 들어 있다
service.yaml      8181 (ClusterIP)
```

## 운영 규칙

- **fail-closed.** OPA 가 없거나 응답이 이상하면 제어기는 `error` 로 기록하고 실행하지 않는다. OPA 를 지운다고 이전이 "풀리지" 않는다.
- 정책 변경 = 이미지 태그 교체(`kustomization.yaml` `images[].newTag`). 파드 안의 파일을 고치지 않는다.
- 판정 기록은 OPA 가 아니라 호출자의 `policy.sqlite3`(워커 PVC) 에 남는다. OPA 의 console decision log 는 보조다.

## 확인

```bash
kubectl -n hackathon get pod -l app.kubernetes.io/name=migration-policy
kubectl -n hackathon exec deploy/db-insert-worker -- python -c "import urllib.request;print(urllib.request.urlopen('http://migration-policy:8181/v1/data/ghost/migration/policy_version').read())"
```

`{"result":"migration-policy-v1"}` 이 나와야 한다.
