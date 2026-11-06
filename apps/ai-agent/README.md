# ai-agent — 온프렘 AI 설정 수정 에이전트

마이그레이션이 APP-01(대상 앱 DB 연결 실패)로 막히면 Codex 가 `DB_HOST`·`DB_PORT` 수정을 제안하고, 정적 검사와
탐침을 통과한 값만 OpenBao 에 쓴 뒤 재시작·재판정해 보고한다. 코드와 흐름은 Hackathon 저장소 `agent/README.md`.

## 선행 조건

1. `apps/sample-app/README.md` 의 "이 overlay 를 main 에 올리기 전에" (OpenBao 값·앱 토큰).
2. Secret `ai-agent-store`(있음)의 토큰이 `hackathon/sample-app/onprem` 을 read·update 할 수 있을 것.
3. Secret `ai-agent-credentials` 수동 생성: `secret.example.yaml` 참고.
4. `limits.cpu` 200m 여유 (이 파드). sample-app 카나리에는 별도로 350m 가 필요하다.
5. GHCR `ghost-agent` 이미지. Hackathon main 머지 뒤 CI 가 만든다. `kustomization.yaml` 의 `newTag` 를 그 SHA 로 고정한다.

## 실행

```sh
export KUBECONFIG=~/.kube/oneport-onprem.yaml   # 현재 컨텍스트가 EKS 일 수 있다
kubectl -n hackathon exec deploy/ai-agent -c agent -- python -m agent run
kubectl -n hackathon exec deploy/ai-agent -c agent -- python -m agent run --no-auto-apply  # 쓰기 전에 멈춘다
kubectl -n hackathon exec deploy/ai-agent -c agent -- python -m agent approve <run_id>
kubectl -n hackathon exec deploy/ai-agent -c agent -- python -m agent status [run_id]
```

종료 코드는 0(복구 완료·고칠 것 없음·승인 대기), 1(설정 오류), 2(사람이 봐야 함)다.

## 알아 둘 것

- 스모크는 `target_only` 다. 대상 앱의 DB 조회만 보며 복제·쓰기는 검증하지 않는다. 보고에도 그렇게 적힌다.
- `target_db_exposure`·`target_location` 은 수집기가 없어 설정에 선언한 값이다 (`source: agent.declared-config`). 실제 관측이 아니다.
- 실행 기록은 emptyDir 에 있어 파드가 재시작되면 사라진다. PVC 를 만들 storage 쿼터가 없다.
