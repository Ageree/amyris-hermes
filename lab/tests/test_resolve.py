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
    assert classify("https://youtu.be/dQw4w9WgXcQ") == "youtube"
    assert classify("https://www.youtube.com/shorts/abc") == "youtube"
    assert classify("https://example.com/some-article") == "article"
