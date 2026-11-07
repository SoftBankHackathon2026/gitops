# 퇴역한 DB INSERT 워커의 공유 리소스

2026-11-08부터 직접 DB 쓰기는 중단한다. 트래픽은 별도 `traffic-bot`이 앱 경로로 생성한다.
Argo CD Application은 `migration-config` ConfigMap과 `db-insert-worker-state` PVC만 관리한다.
Deployment와 Service는 GitOps prune으로 제거한다. **Application과 PVC는 삭제하지 않는다.**

PVC에는 요청 장부와 전환 작업 기록이 있으며 `live-db-cutover`, `policy-roundtrip`,
`demo-traffic-agent`가 사용한다. 이 파드들은 제거된 워커가 아니라 PV의 nodeAffinity로 배치된다.
상태 프록시의 `/worker/status`는 410 Gone을 반환한다.

현재 배포된 구버전 `migration.cutover`는 워커 API를 요구하므로 그 경로는 워커 제거 후
그대로 실행할 수 없다. 앱/트래픽봇 중심 전환 경로로 바꾸기 전까지 새 실행을 시작하지 않는다.
기존 DB 데이터, 공유 장부, 트래픽봇 Deployment는 이번 변경에서 삭제하지 않는다.

확인: `kubectl -n hackathon get deploy,pod,svc`에서 db-insert-worker가 없고,
`kubectl -n hackathon get pvc db-insert-worker-state`는 Bound여야 한다.
복원은 이 제거 커밋을 Git에서 revert한 뒤 Argo CD가 동기화하도록 한다.
