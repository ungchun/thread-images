# M3 발행 경로와 API (2026-10-25)

출처: developers.facebook.com/docs/threads (changelog, insights, overview, publishing) + run.py·replies.py·dashboard.py 대조. 실호출 없음.

## 결론

- API 발행이 도달에서 불리하다는 근거는 공식·비공식 모두 못 찾음. "게시 앱" 표시도 근거 없음. 우리 W39 실험도 앱 단위 스로틀을 지지 안 함(m4_our_history.md).
- For You vs 팔로워 노출 비율은 API로 알 수 없음. 앱 안 인사이트 화면은 미확인.

## 써볼 만한데 안 쓰는 것

| 기능 | 파라미터 | 쓰임 |
|---|---|---|
| 토픽 태그(2025-07) | `topic_tag` 글당 1개 | 배포 영향은 문서에 없음 → A/B 필요. 지금 0/138 |
| 팔로워 수·국적 | `followers_count`, `follower_demographics` (팔로워 100+) | 나라별 계정의 실제 팔로워 국적 검증 |
| 쿼터 | `threads_publishing_limit` | 이상 감지 |
| 프로필 조회수 | 계정 단위 `views` | 글 → 프로필 유입 비율 |
| 투표(2025-04) | `poll_attachment` (텍스트 글만) | 답글·참여 유도 소재 |
| 답글 제어·승인 | `reply_control`, `enable_reply_approvals` | |
| 국가 제한 공개 | `allowlisted_country_codes` | 나라 밖 노출 차단 실험 가능성(효과 미확인) |

## 운영 주의

- 링크 미리보기는 텍스트 답글에서만 자동. 답글에 미디어 붙이면 사라짐.
- 상태 확인 간격 문서 권장 1분(우리는 5초×20).
- 포럼 보고: code 1 / subcode 2207051 "action is blocked" = 계정 제한 신호, 오류여도 실제 게시된 경우 있음 → 재시도 전 게시 여부 조회.
- 한도: 게시 250/24h, 답글 1,000, 삭제 100. 고유 링크 5개 초과 오류(2025-12).
