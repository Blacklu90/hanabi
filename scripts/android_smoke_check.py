"""Talk to Shuinkan running inside the Android emulator (port-forwarded to the host)."""
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request

base = f"http://127.0.0.1:{sys.argv[1]}"
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(path):
    with op.open(base + path, timeout=30) as r:
        return r.status, r.read().decode("utf-8")


def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    with op.open(urllib.request.Request(base + path, data=body, headers={"Origin": base}), timeout=60) as r:
        return r.status, r.read().decode("utf-8")


_, page = get("/register")
tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
post("/register", {"username": "android", "email": "android@example.com", "password": "a long password", "csrf": tok})
for p in ["/dashboard", "/learn/hiragana/1", "/kanji/%E5%AD%A6", "/decks", "/hooks", "/settings"]:
    status, html = get(p)
    print(p, status, len(html))
    assert status == 200 and "<title>" in html, p
status, body = get("/api/dictionary/search?q=cat")
first = json.loads(body)["results"][0]["headword"]
print("dictionary 'cat' ->", first)
status, body = get("/api/dictionary/search?q=neko")
print("dictionary 'neko' ->", json.loads(body)["results"][0]["headword"])
assert first == "猫"
print("Android smoke test passed ✓")
