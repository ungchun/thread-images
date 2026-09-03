"""답글 구조 확인용 일회성 프로브."""
import json, os, urllib.error, urllib.parse, urllib.request
from run import creds
G = "https://graph.threads.net/v1.0"
F = "id,text,username,timestamp,permalink,replied_to,root_post,is_reply,has_replies,hide_status"

def get(path, tok, **p):
    p["access_token"] = tok
    try:
        with urllib.request.urlopen(f"{G}/{path}?{urllib.parse.urlencode(p)}") as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"ERROR": e.code, "body": e.read().decode()[:300]}

tok, uid = creds("ashgrey._02")
me = get("me", tok, fields="id,username")
print("계정:", me)
posts = get(f"{uid}/threads", tok, fields="id,text,timestamp", limit=3).get("data", [])
top = posts[0]
print("\n대상 글:", top["id"], top["timestamp"])

for ep in ("replies", "conversation"):
    d = get(f"{top['id']}/{ep}", tok, fields=F, limit=10)
    rows = d.get("data", [])
    print(f"\n--- {ep}: {len(rows)}건 (paging={'있음' if d.get('paging',{}).get('next') else '없음'})")
    for r in rows[:10]:
        print(f"  @{r.get('username'):<18} has_replies={str(r.get('has_replies')):<5} "
              f"replied_to={r.get('replied_to',{}).get('id')} | {(r.get('text') or '')[:40]}")
