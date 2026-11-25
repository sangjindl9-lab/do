"""Google Play 공개 스토어 페이지에서 앱 이름·아이콘·설명을 읽어온다.
공개된 앱만 조회된다. 비공개 테스트 단계라 스토어 페이지가 없는 앱은 찾지 못하며, 그 경우 고객이 이름을 직접 입력한다."""
import html
import re

import httpx

STORE_URL = "https://play.google.com/store/apps/details"
ICON_HOSTS = ("play-lh.googleusercontent.com", "lh3.googleusercontent.com")
SUFFIX_RE = re.compile(r"\s+[-–]\s+(Apps on Google Play|Google Play\s*앱|Google Play のアプリ|Google Play)\s*$")


def _meta(page: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', page) or \
        re.search(rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"', page)
    return html.unescape(m.group(1)).strip() if m else ""


def parse_listing(page: str, package: str) -> dict:
    title = SUFFIX_RE.sub("", _meta(page, "og:title"))
    if not title:
        return {"found": False}
    icon = _meta(page, "og:image")
    if not any(icon.startswith(f"https://{h}/") for h in ICON_HOSTS):
        icon = ""
    return {"found": True, "name": title[:160], "icon": icon, "description": _meta(page, "og:description")[:2000],
            "play_url": f"{STORE_URL}?id={package}"}


def fetch_listing(package: str, locale: str = "ko", client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": locale})
    try:
        res = client.get(STORE_URL, params={"id": package, "hl": locale})
        if res.status_code != 200:
            return {"found": False}
        return parse_listing(res.text, package)
    except httpx.HTTPError:
        return {"found": False, "error": "network"}
    finally:
        if own:
            client.close()


def fetch_icon(url: str, client: httpx.Client | None = None) -> bytes | None:
    """아이콘 내려받기(허용된 Google 이미지 호스트만, 2MB 이하, PNG/JPEG/WEBP)."""
    if not any(url.startswith(f"https://{h}/") for h in ICON_HOSTS):
        return None
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False)
    try:
        res = client.get(url)
        data = res.content
        ok = res.status_code == 200 and len(data) <= 2 * 1024 * 1024 and (
            data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8") or data[8:12] == b"WEBP")
        return data if ok else None
    except httpx.HTTPError:
        return None
    finally:
        if own:
            client.close()
