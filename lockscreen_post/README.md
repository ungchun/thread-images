# 월간 잠금화면 글 공정 (10/27 v1027 → 12월 2612)

운영 글 최소 품질: 캐러셀 3장 — ① 손에 든 폰 생활 사진 ② 실제 Trace 잠금화면(그 나라 생활 일정으로 꽉 찬 달, 상태바·시계·날짜, 아래 구름이) ③ 현지어 헤드라인 확대 슬라이드. 빈 달력 카드 배포 글은 2026-11-17 오너가 기각했다.

1. 시뮬 복제(원본 Promo 시뮬은 건드리지 않는다)·언어 설정. 프리셋은 `Trace_iOS/.claude/presets/wallpaper/{jp-m1201,tw-m1202}.json`(일본은 Zen Maru Gothic — ChironGoRound TC는 대만 자형).
2. 일정: `TRACE_SIM_UDID=… SEED_COUNTRY=jp|tw Trace_iOS/appium/venv/bin/python seed_dec.py` → `launchctl stop com.apple.calaccessd` → Trace 한 번 켰다 끄기. 칸 제목은 일본 3자·대만 4자 이하.
3. 다음 달을 지금 렌더하려면 Trace 시계만 옮긴다(앱 빌드 없음):
   `xcrun --sdk iphonesimulator clang -target arm64-apple-ios17.0-simulator -dynamiclib -O2 -o timeshift.dylib timeshift/timeshift.c && codesign -f -s - timeshift.dylib`
   시뮬 안에서 `launchctl setenv` TIMESHIFT_PROC=Trace, TIMESHIFT_OFFSET=<일수×86400>, DYLD_INSERT_LIBRARIES=<dylib>. 끝나면 시뮬을 종료해 env를 지운다.
4. 배경: 구름이 그림을 `zoom_art.py`/`shrink_scene.py`로 캐릭터가 아래 21% 안에 들게(달력 띠 31~79%).
5. `Trace_iOS/appium/venv/bin/python Trace_iOS/appium/wallpaper_shots.py <udid> <preset> <bg폴더> <out>`
6. 손 사진: `GEMINI_API_KEY=… python3 gen_hand_dec.py jp|tw <회차>` → 폰이 작으면 `crop_hand.py`(화면은 원본으로 덮여서 안 흐려진다).
7. `make_post_dec.py jp|tw` — 시계·날짜(lockscreen_overlay)·상태바 UI·확대 슬라이드·손 합성(compose_hand, numpy 필요해 시스템 python3).

글: 첫 줄 호명 + 효익 + 꽉 찬 실화면, 본문에 앱 이름·만든 사람 문장 없음, 답글에 앱 이름과 ct 링크. 공식 계정은 페르소나 계정과 문장·그림(shared.* 포함)을 공유하지 않는다. `locale_lint.py`·`gate.py` 통과 후 예약.
