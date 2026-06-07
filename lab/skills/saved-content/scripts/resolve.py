#!/usr/bin/env python3
"""Resolve a shared URL into text + media files on disk for the agent to analyze."""
import argparse, json, os, re, subprocess
import requests

def classify(url):
    host = re.sub(r"^www\.", "", re.match(r"https?://([^/]+)", url).group(1).lower())
    if "instagram.com" in host: return "instagram"
    if "tiktok.com" in host: return "tiktok"
    if host in ("x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"): return "x"
    if "youtube.com" in host or host == "youtu.be": return "youtube"
    return "article"

def _ytdlp(url, out_dir):
    cmd = ["yt-dlp", "--no-playlist", "--write-info-json",
           "--write-auto-subs", "--sub-langs", "en,ru", "--max-filesize", "200M",
           "-o", os.path.join(out_dir, "video.%(ext)s"), url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        return {"ok": False, "error": p.stderr[-500:]}
    info_path = os.path.join(out_dir, "video.info.json")
    text = ""
    if os.path.exists(info_path):
        with open(info_path) as f:
            text = json.load(f).get("description", "")
    media = [os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
             if n.startswith("video.") and not n.endswith((".info.json", ".part"))]
    return {"ok": True, "text": text, "media": media}

def _fxtwitter(url):
    api = re.sub(r"https?://(?:www\.|mobile\.)?(x|twitter|mobile\.twitter)\.com", "https://api.fxtwitter.com", url)
    r = requests.get(api, timeout=30)
    if r.status_code != 200:
        return {"ok": False, "error": f"fxtwitter HTTP {r.status_code}"}
    t = r.json().get("tweet", {})
    photos = [m["url"] for m in t.get("media", {}).get("photos", [])]
    return {"ok": True, "text": t.get("text", ""), "media_urls": photos}

def _jina(url):
    r = requests.get("https://r.jina.ai/" + url, timeout=60,
                     headers={"X-Return-Format": "markdown"})
    if r.status_code != 200:
        return {"ok": False, "error": f"jina HTTP {r.status_code}"}
    return {"ok": True, "text": r.text[:20000]}

def resolve(url, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    source = classify(url)
    fn = {"instagram": _ytdlp, "tiktok": _ytdlp, "youtube": _ytdlp}.get(source)
    try:
        res = fn(url, out_dir) if fn else (_fxtwitter(url) if source == "x" else _jina(url))
    except Exception as e:                      # network timeouts etc. — honest failure
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"source": source, "ok": res.get("ok", False),
            "text": res.get("text", ""), "media": res.get("media", []),
            "media_urls": res.get("media_urls", []), "error": res.get("error")}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--out", default="/tmp/saved-content")
    a = p.parse_args()
    print(json.dumps(resolve(a.url, a.out), ensure_ascii=False))

if __name__ == "__main__":
    main()
