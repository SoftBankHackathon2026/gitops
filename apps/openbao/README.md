# openbao — 온프렘 설정 저장소 (OpenBao, Vault 호환)

[08 문서 §6](../../../업무-아젠다/08-AI-에이전트와-샌드박스.md) 의 "온프렘 Vault" 자리. AI 에이전트의 `VaultKvStore`(KV v2) 가 읽고 쓰는 설정 저장소다.

- 단일 노드 StatefulSet(`openbao-0`), raft 통합 스토리지(1 노드) PVC 1Gi(local-path), Service `openbao:8200`(ClusterIP, HTTP).
- TLS 없음: 클러스터 밖 노출이 없고 `default-deny-ingress` + `allow-same-namespace` 로 같은 ns 만 접근. 파드 egress 는 DNS 만.
- 이미지 `quay.io/openbao/openbao` 2.7.2 를 digest 로 고정. `disable_mlock=true`(IPC_LOCK 없이 실행).

## 처음 한 번 (수동 · 비밀값은 k8s Secret 에만)

```sh
# 1) init: key-shares 1 로. 결과는 파일/채팅에 남기지 않고 Secret 으로만 옮긴다
kubectl -n hackathon exec openbao-0 -- bao operator init -key-shares=1 -key-threshold=1 -format=json \
  | kubectl -n hackathon create secret generic openbao-init --from-file=init.json=/dev/stdin
# 2) 자동 unseal(static seal). 아래 "자동 unseal" 절차를 따른다. 그 뒤로는 파드가 다시 떠도 unseal 이 필요 없다
# 3) KV v2 마운트 secret, 에이전트 정책(hackathon/sample-app/onprem 만 read/update), 토큰 → Secret ai-agent-store
```

봉인 상태 확인: `kubectl -n hackathon exec openbao-0 -- bao status` (`Sealed false` 면 정상).

## 자동 unseal (static seal)

파드가 다시 뜰 때마다 잠기던 Shamir 방식 대신, 32바이트 키 파일로 스스로 여는 OpenBao static seal 을 쓴다.
키는 Secret `openbao-static-seal` 에만 있고 Git 에는 없다. 기존 unseal 키도 같은 클러스터 Secret(`openbao-init`)에 있었으므로 보안 경계는 같다.

### 처음 한 번: Shamir → static 이전

순서가 중요하다. **Secret 을 먼저 만들고** 이 변경을 반영한다. Secret 이 없으면 파드가 키 볼륨을 못 붙여 뜨지 않는다.

```sh
# 1) 키 Secret 만들기 (값은 화면·파일에 남기지 않는다)
head -c 32 /dev/urandom | kubectl -n hackathon create secret generic openbao-static-seal --from-file=static.key=/dev/stdin

# 2) 이 변경을 머지하고 Argo 동기화 → openbao-0 이 static seal 설정으로 다시 뜬다 (아직 잠김, 이전 대기)
kubectl -n hackathon exec openbao-0 -- bao status   # Seal Type static, Sealed true, Seal Migration in Progress true

# 3) 기존 Shamir 키로 한 번만 이전한다
kubectl -n hackathon exec openbao-0 -- bao operator unseal -migrate "$(kubectl -n hackathon get secret openbao-init -o jsonpath='{.data.init\.json}' | base64 -d | python3 -c 'import sys,json; print(json.load(sys.stdin)["unseal_keys_b64"][0])')"

# 4) 확인: Sealed false. 파드를 지웠다 다시 띄워도 Sealed false 여야 한다
kubectl -n hackathon exec openbao-0 -- bao status
kubectl -n hackathon delete pod openbao-0 && kubectl -n hackathon wait --for=condition=Ready pod/openbao-0 --timeout=120s
kubectl -n hackathon exec openbao-0 -- bao status
```

- 이전 뒤 `openbao-init` 의 unseal 키는 **복구 키(recovery key)** 가 된다. root 토큰 재발급 같은 복구 작업에 필요하므로 지우지 않는다.
- `openbao-static-seal` 을 잃으면 데이터를 열 수 없다. 클러스터 밖 안전한 곳에 따로 백업한다.
- 같은 이미지(2.7.2)로 로컬에서 Shamir 초기화 → static 이전 → 재시작 후 자동 unseal · 기존 KV 값 유지까지 확인했다(2026-11-08).

