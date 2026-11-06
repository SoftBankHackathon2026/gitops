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

## 2026-11-06 이미지 복구 준비

GHCR 패키지 화면에서 `migration-policy`가 Private이고 `main`/`abdc867a000fe5ea3a4c8268d7a76f1072dba233`
태그가 존재함을 확인했다. [CI run 41820600281](https://github.com/SoftBankHackathon2026/Hackathon/actions/runs/41820600281)은
`sha256:66f6dccbd2affea585126a0daa7f89f9756216e9d1074098b47b6e30cbb68a10` 게시 성공을 기록한다.
이 digest로 고정해 이후 main 이동으로 정책이 바뀌는 것을 방지한다. **인증 장애 복구 자체는 아니다.**

선행 조건: Harbor의 GHCR upstream에 이 패키지 읽기 권한을 가진 자격증명을 운영자가 안전하게
등록하고 pull을 확인한다. GHCR 이미지 공개 전환은 별도 결정이며 이 변경에 포함하지 않는다.
토큰/비밀번호는 이 저장소에 넣지 않는다. 클러스터 직접 patch/restart 없이 Argo CD가 Git 변경을 적용한다.

적용: 인증 준비 → 이 변경 머지 → Argo CD 동기화 → replicas 2/2 및 endpoint 확인 →
Hackathon `policies/README.md`의 HTTP smoke 15개 실행. 합성 판정 통과는 실제 DB·앱 이전 검증과 별도다.
롤백은 이 Git 변경을 revert하고 Argo CD 동기화한다. 이전 main도 인증이 필요하므로 인증 장애를
해결하지 못한다. 정책 서비스가 준비되지 않으면 이전 실행은 계속 차단한다.
