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
# 2) unseal (파드가 다시 뜰 때마다 필요 — 자동 unseal 은 KMS 가 없어 없음)
kubectl -n hackathon exec openbao-0 -- bao operator unseal "$(kubectl -n hackathon get secret openbao-init -o jsonpath='{.data.init\.json}' | base64 -d | python3 -c 'import sys,json; print(json.load(sys.stdin)["unseal_keys_b64"][0])')"
# 3) KV v2 마운트 secret, 에이전트 정책(hackathon/sample-app/onprem 만 read/update), 토큰 → Secret ai-agent-store
```

봉인 상태 확인: `kubectl -n hackathon exec openbao-0 -- bao status` (`Sealed false` 면 정상).
