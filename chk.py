import json, os, urllib.request, urllib.parse, urllib.error
d = json.loads(os.environ["THREADS_ACCOUNTS"])
for k, v in d.items():
    t, u = v["token"], str(v["user_id"])
    q = urllib.parse.urlencode({"fields": "id,username", "access_token": t})
    try:
        with urllib.request.urlopen(f"https://graph.threads.net/v1.0/me?{q}") as r:
            me = json.load(r)
        ok = "일치" if me.get("id") == u else f"!!! 불일치 (토큰 주인={me.get('id')})"
        print(f"[{k}] 토큰 주인={me.get('username')!r} / 설정 user_id={u} → {ok}")
    except urllib.error.HTTPError as e:
        print(f"[{k}] 토큰 조회 실패: {e.code} {e.read().decode()[:200]}")
