import json, os, urllib.request, urllib.parse, urllib.error
RAW = "https://raw.githubusercontent.com/ungchun/thread-images/main/images/"
d = json.loads(os.environ["THREADS_ACCOUNTS"])
t, u = d["daily03dew"]["token"], d["daily03dew"]["user_id"]

def call(label, params, get=False):
    body = urllib.parse.urlencode({**params, "access_token": t}).encode()
    req = urllib.request.Request(f"https://graph.threads.net/v1.0/{u}/threads", data=body)
    try:
        with urllib.request.urlopen(req) as r:
            print(f"{label}: OK {json.load(r)}")
    except urllib.error.HTTPError as e:
        print(f"{label}: {e.code} {e.read().decode()[:400]}")

# 1) 이미지 없는 텍스트 컨테이너 — 토큰/권한만 검증
call("텍스트", {"media_type": "TEXT", "text": "권한 확인용, 발행 안 함"})
# 2) 단일 이미지 — 일본이 성공했던 형태
call("단일이미지", {"media_type": "IMAGE", "image_url": RAW + "tw-a.jpg"})
# 3) 캐러셀 아이템 — 대만이 쓰는 형태
call("캐러셀아이템", {"media_type": "IMAGE", "image_url": RAW + "tw-a.jpg", "is_carousel_item": "true"})
