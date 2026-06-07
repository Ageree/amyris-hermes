import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "skills/saved-content/scripts"))
from resolve import classify

def test_classify_sources():
    assert classify("https://www.instagram.com/reel/DEF123/") == "instagram"
    assert classify("https://www.instagram.com/p/ABC/?img_index=2") == "instagram"
    assert classify("https://vm.tiktok.com/ZM123/") == "tiktok"
    assert classify("https://www.tiktok.com/@u/video/7301") == "tiktok"
    assert classify("https://x.com/elonmusk/status/123") == "x"
    assert classify("https://twitter.com/a/status/9") == "x"
    assert classify("https://mobile.twitter.com/a/status/9") == "x"
    assert classify("https://mobile.x.com/a/status/9") == "x"
    assert classify("https://youtu.be/dQw4w9WgXcQ") == "youtube"
    assert classify("https://www.youtube.com/shorts/abc") == "youtube"
    assert classify("https://example.com/some-article") == "article"

import json, resolve

def test_resolve_x_uses_fxtwitter(monkeypatch):
    fixture = {"tweet": {"text": "Pull backlinks for any domain free",
                         "media": {"photos": [{"url": "https://pbs.img/1.jpg"}]}}}
    class R:
        status_code = 200
        def json(self): return fixture
    monkeypatch.setattr(resolve.requests, "get", lambda url, timeout: R())
    out = resolve.resolve("https://x.com/a/status/123", "/tmp/out")
    assert out["ok"] and out["source"] == "x"
    assert "backlinks" in out["text"]
    assert out["media_urls"] == ["https://pbs.img/1.jpg"]

def test_resolve_video_invokes_ytdlp(monkeypatch, tmp_path):
    calls = {}
    def fake_run(cmd, capture_output, text, timeout):
        calls["cmd"] = cmd
        (tmp_path / "video.mp4").write_bytes(b"x")
        (tmp_path / "video.info.json").write_text(json.dumps({"description": "vibe coding 101"}))
        class P: returncode = 0; stderr = ""
        return P()
    monkeypatch.setattr(resolve.subprocess, "run", fake_run)
    out = resolve.resolve("https://www.tiktok.com/@u/video/7301", str(tmp_path))
    assert out["ok"] and out["source"] == "tiktok"
    assert "yt-dlp" in calls["cmd"][0]
    assert out["text"] == "vibe coding 101"
    assert out["media"][0].endswith("video.mp4")
    assert not any("info.json" in p for p in out["media"])

def test_resolve_failure_is_honest(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output, text, timeout):
        class P: returncode = 1; stderr = "login required"
        return P()
    monkeypatch.setattr(resolve.subprocess, "run", fake_run)
    out = resolve.resolve("https://www.instagram.com/reel/PRIVATE/", str(tmp_path))
    assert out["ok"] is False and "login required" in out["error"]

def test_resolve_article_uses_jina(monkeypatch, tmp_path):
    class R:
        status_code = 200
        text = "# Title\n\nClean article text"
    monkeypatch.setattr(resolve.requests, "get", lambda url, timeout, headers=None: R())
    out = resolve.resolve("https://example.com/post", str(tmp_path))
    assert out["ok"] and "Clean article" in out["text"]

def test_fxtwitter_rewrites_mobile_x_host(monkeypatch):
    seen = {}
    fixture = {"tweet": {"text": "hi", "media": {"photos": []}}}
    class R:
        status_code = 200
        def json(self): return fixture
    def fake_get(url, timeout):
        seen["url"] = url
        return R()
    monkeypatch.setattr(resolve.requests, "get", fake_get)
    out = resolve.resolve("https://mobile.x.com/a/status/9", "/tmp/out")
    assert out["ok"] and out["source"] == "x"
    assert seen["url"].startswith("https://api.fxtwitter.com")
