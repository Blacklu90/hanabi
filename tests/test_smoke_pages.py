import pytest

PAGES = ["/dashboard", "/learn/hiragana", "/learn/katakana", "/learn/hiragana/1", "/learn/katakana/27", "/learn/katakana/32",
         "/vocab/hiragana", "/vocab/katakana", "/kanji", "/kanji/日", "/kanji/謎", "/review", "/quiz", "/write",
         "/write?track=katakana", "/write?track=kanji&item=学", "/match", "/progress", "/achievements", "/settings",
         "/profile", "/about", "/hooks", "/hooks?script=katakana"]


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(user, path):
    r = user.c.get(path)
    assert r.status_code == 200, (path, r.text[-2000:])
    assert "<title>" in r.text
    assert "Content-Security-Policy" in r.headers


@pytest.mark.parametrize("path", ["/", "/login", "/register", "/forgot", "/about"])
def test_public_pages(client, path):
    r = client.get(path)
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/dashboard", "/kanji", "/review", "/settings"])
def test_private_pages_redirect(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_404s(user):
    assert user.c.get("/kanji/A").status_code == 404
    assert user.c.get("/learn/hiragana/99").status_code == 404
    assert user.c.get("/learn/cyrillic").status_code == 404
    assert user.c.get("/quiz/doesnotexist").status_code == 404


def test_static_assets_versioned_by_path(user):
    import re
    html = user.c.get("/vocab/katakana").text
    srcs = re.findall(r'src="(/static/[^"]+\.js)"', html)
    assert srcs and all(re.match(r"^/static/b[0-9a-f]{10}/js/", s) for s in srcs) and all("?" not in s for s in srcs)
    r = user.c.get(srcs[0])
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    # relative imports in page modules resolve to the same versioned URL as the <script> tag
    page_js = user.c.get(srcs[-1]).text
    assert "from './app.js'" in page_js
    assert user.c.get("/static/js/app.js").headers["cache-control"] == "public, max-age=3600"
