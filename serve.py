#!/usr/bin/env python3
"""대시보드용 로컬 서버. 캐시를 완전히 막는다.

기본 http.server는 Last-Modified/ETag를 보내서 브라우저가 304로 옛 파일을 재사용한다.
HTML을 고쳐도 화면이 그대로여서 한참 헤맸다. 헤더 세 개를 다 걷어낸다.

  python3 serve.py        # http://localhost:8899/dashboard.html
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 8899
DROP = {"last-modified", "etag"}   # 있으면 브라우저가 304로 옛것을 쓴다


class NoCache(SimpleHTTPRequestHandler):
    def send_header(self, key, value):
        if key.lower() in DROP:
            return
        super().send_header(key, value)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *a):
        pass                       # 요청 로그는 필요 없다


if __name__ == "__main__":
    print(f"http://localhost:{PORT}/dashboard.html")
    ThreadingHTTPServer(("127.0.0.1", PORT), NoCache).serve_forever()
