import json, os
b = os.environ.get("THREADS_ACCOUNTS")
print("secret 존재:", bool(b), "길이:", len(b or ""))
try:
    d = json.loads(b)
except Exception as e:
    print("JSON 파싱 실패:", e); raise SystemExit
print("계정 키:", list(d))
for k, v in d.items():
    t = str(v.get("token", "")); u = str(v.get("user_id", ""))
    print(f"[{k!r}] 필드={list(v)} token: 길이={len(t)} 앞4={t[:4]!r} 끝2={t[-2:]!r} 공백포함={any(c.isspace() for c in t)} / user_id={u!r} 숫자만={u.isdigit()}")
