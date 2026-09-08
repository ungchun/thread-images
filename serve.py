#!/usr/bin/env python3
"""대시보드용 로컬 서버. 캐시를 막는다 — 기본 서버는 Last-Modified로 옛 화면을 재사용해서
HTML을 고쳐도 브라우저가 예전 것을 계속 쓴다.

  python3 serve.py        # http://localhost:8899/dashboard.html
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def send_header(self, key, value):
        if key.lower() == "last-modified":   # 이게 있으면 브라우저가 304로 옛것을 쓴다
            return
        super().send_header(key, value)


if __name__ == "__main__":
    print("http://localhost:8899/dashboard.html")
    ThreadingHTTPServer(("127.0.0.1", 8899), NoCache).serve_forever()
