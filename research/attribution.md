# Threads 답글 링크 귀속(App Store 캠페인 링크)

작성 2026-10-22. 스펙 §2 최종 지표(게시물 링크 클릭 수, 대상 국가 설치 수)를 계정 단위로 보려면 답글 링크에 캠페인 토큰이 붙어 있어야 한다.

## 현재 상태 — 적용됨 (2026-10-22)

- provider token `pt=126570331` (Corca, Inc. 팀). App Store Connect → Trace → 분석 → 캠페인 → 캠페인 링크 생성 화면에서 확인했다. 팀마다 하나로 고정이다.
- 유지·휴식 19개 계정의 `accounts/<계정>/reply.txt` 링크를 아래 ct 규칙으로 바꿨다. 중단 계정은 발행하지 않으니 그대로 둔다.
- 캠페인 화면은 서로 다른 사용자가 최소 5명 이상이어야 숫자가 보인다(생성 창 안내). 계정 단위 설치는 작게 잡히거나 안 보일 수 있어, 나라 단위로 묶어 읽는다.
- `watch.json`의 경쟁 앱 Catlendar 링크에 있는 `pt=`는 남의 토큰이다. 절대 쓰지 않는다.

## 오너가 App Store Connect에서 받아올 것

1. App Analytics를 볼 수 있는 역할(Account Holder·Admin·Marketing 등)로 App Store Connect 로그인
2. App Analytics → Trace 선택 → 획득(Acquisition) → 캠페인(Campaigns) → **캠페인 링크 생성(Generate Campaign Link)**
3. 아무 캠페인 이름(예: `test`)으로 링크를 하나 만든다. 생성된 URL의 `pt=` 뒤 숫자가 provider token이다. 개발자 계정(팀)마다 하나로 고정이라 한 번만 받으면 된다.
4. 그 숫자만 전달한다(비밀값은 아니지만 이 문서에는 받은 뒤 적는다).

## ct 규칙

```
https://apps.apple.com/app/apple-store/id6503812022?pt=<PT>&ct=th_<나라>_<계정>&mt=8
```

- `ct` = `th_` + 나라 소문자 2자 + `_` + 계정 아이디. App Store 상한 40자, 가장 긴 것이 21자라 여유가 있다.
- `th_`는 Threads. 나중에 인스타 프로필 링크를 붙이면 `ig_`, 크리에이터는 `cr_<나라>_<핸들>`, 공식 계정은 `of_jp`·`of_tw`, 광고 부스트는 `ad_<나라>_<게시물날짜>`로 같은 체계를 쓴다.
- `mt=8`은 앱 링크 표준 매개변수. `apple-store` 슬러그는 캠페인 링크 생성기가 내주는 형태 그대로다.

| 상태 | 계정 | 나라 | ct |
|---|---|---|---|
| active | pim.pm_02 | TH | th_th_pim.pm_02 |
| active | fah.pk_03 | TH | th_th_fah.pk_03 |
| active | ashgrey._02 | VN | th_vn_ashgrey._02 |
| active | linh.ngx_02 | VN | th_vn_linh.ngx_02 |
| active | mint.le_06 | VN | th_vn_mint.le_06 |
| active | daily.life_gram | TW | th_tw_daily.life_gram |
| active | yuting._066 | TW | th_tw_yuting._066 |
| active | haru._81a | JP | th_jp_haru._81a |
| active | mio._k27 | JP | th_jp_mio._k27 |
| active | rara.2k_ | ID | th_id_rara.2k_ |
| active | nur.aina_04 | MY | th_my_nur.aina_04 |
| rest | aoi_1124_gram | JP | th_jp_aoi_1124_gram |
| rest | shu.lin_03 | TW | th_tw_shu.lin_03 |
| rest | inkling01 | TW | th_tw_inkling01 |
| rest | daily03dew | TW | th_tw_daily03dew |
| rest | aisyah.zr_05 | MY | th_my_aisyah.zr_05 |
| rest | appfinds_my | MY | th_my_appfinds_my |
| rest | nadia.ps_04 | ID | th_id_nadia.ps_04 |
| rest | appfinds_id | ID | th_id_appfinds_id |

## pt를 받은 뒤 할 일

1. 위 19개 계정의 `accounts/<계정>/reply.txt` 두 번째 줄을 표의 URL로 바꾼다(첫 줄 현지어 문구는 그대로). `reply_ig.txt`는 링크가 안 눌리므로 건드리지 않는다.
2. 본문 파일 `---` 아래에 링크를 직접 쓰는 라운드는 같은 규칙으로 쓴다. 인라인 답글이 `reply.txt`보다 우선한다(run.py `fixed_reply`).
3. 1주 뒤 App Analytics → 캠페인에서 ct별 노출(App Store 페이지 조회)·설치(App Units)를 본다. 대시보드 클릭 수와 나란히 놓으면 게시물 → 클릭 → 설치 퍼널이 계정 단위로 나온다.

## 한계

- 캠페인 집계는 Apple 쪽 사용자 동의 조건에 따라 일부만 잡히는 것으로 알려져 있다(정확한 조건은 App Store Connect 도움말로 확인 필요). 절대 수치가 아니라 계정·나라 간 비교용이다.
- Threads 앱 안 브라우저에서 App Store로 넘어갈 때 매개변수가 유지되는지는 pt를 받은 뒤 한 계정으로 먼저 확인한다(테스트 클릭 → 다음 날 캠페인에 잡히는지).
- R15(10/21)처럼 답글에 링크 대신 앱스토어 캡처만 단 회차는 귀속이 안 된다.
