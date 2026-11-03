"""공개용 데모 페이지 생성: server/app/static/dashboard.html → public-demo/index.html (Firebase Hosting에 올림).

데모 강제(PUBLIC_DEMO=true), 로그인 화면 없음, 서버 요청 없음. 내부 주소/계정 흔적이 없는지 검사한다.
실행: python tools/build_public_demo.py
"""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = (root / "server/app/static/dashboard.html").read_text(encoding="utf-8")
out = src.replace("const PUBLIC_DEMO = false;", "const PUBLIC_DEMO = true;", 1)
assert out != src, "PUBLIC_DEMO 표시를 찾지 못함"
for bad in (r"100\.\d+\.\d+\.\d+", r"192\.168\.", r"tailscale", r"hc-ping", r"https?://"):
    assert not re.search(bad, out, re.I), f"공개 페이지에 내부 정보 흔적: {bad}"
(root / "public-demo").mkdir(exist_ok=True)
(root / "public-demo/index.html").write_text(out, encoding="utf-8")
print("public-demo/index.html 생성")
