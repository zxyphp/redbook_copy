"""
小红书真实数据爬取模块（Playwright 方案）

核心原理：
  XHS 每次 API 请求都需要 X-s / X-t 签名头，这个签名由页面内的 JS 动态生成。
  直接用 requests 伪造签名极其复杂（混淆算法随时更新）。

  ✅ 最稳定的方案：用 Playwright 驱动真实 Chromium 浏览器，
     让浏览器 JS 自动完成签名，我们只负责拦截（intercept）API 响应数据。

支持两种用法：
  1. 单篇笔记 URL  → fetch_note_by_url()
  2. 用户主页 URL  → fetch_user_by_profile_url()
  3. 多个笔记 URLs → fetch_notes_by_urls()

⚠️  仅供学习研究，遵守小红书用户协议，合理控制请求频率。
"""

import asyncio
import json
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs
import time


# ────────────────────────────────────────────────────────────
# URL / 数据解析工具
# ────────────────────────────────────────────────────────────

def parse_note_url(url: str) -> Tuple[str, str, str]:
    """
    解析笔记 URL，返回 (note_id, xsec_token, xsec_source)

    支持的格式：
      https://www.xiaohongshu.com/explore/{note_id}?xsec_token=...
      https://www.xiaohongshu.com/discovery/item/{note_id}?...
      https://xhslink.com/xxxxx  (短链，需要浏览器跳转)
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # 提取 note_id
    note_id = ""
    m = re.search(r"/explore/([a-f0-9]{24})", url)
    if not m:
        m = re.search(r"/discovery/item/([a-f0-9]{24})", url)
    if m:
        note_id = m.group(1)

    xsec_token = params.get("xsec_token", [""])[0]
    xsec_source = params.get("xsec_source", ["pc_feed"])[0]
    return note_id, xsec_token, xsec_source


def parse_profile_url(url: str) -> str:
    """
    从用户主页 URL 中提取 user_id

    https://www.xiaohongshu.com/user/profile/{user_id}
    """
    m = re.search(r"/user/profile/([a-zA-Z0-9]+)", url)
    return m.group(1) if m else ""


def cookie_str_to_list(cookie_str: str, domain: str = ".xiaohongshu.com") -> List[Dict]:
    """Cookie 字符串 → Playwright add_cookies 格式"""
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": domain,
                "path": "/",
                "sameSite": "Lax",
            })
    return cookies


def parse_note_card(raw: Dict) -> Dict:
    """
    将 XHS API 返回的笔记卡片数据规范化

    XHS API 数据结构（两种主要变体）：
      变体 A（feed 接口）: raw["note_card"] 含 title/desc/tag_list/interact_info
      变体 B（user_posted 接口）: raw 直接含 display_title/interact_info
    """
    # 尝试 note_card 子对象
    card = raw.get("note_card", raw)

    title = (
        card.get("title")
        or card.get("display_title")
        or raw.get("title")
        or raw.get("display_title")
        or ""
    )
    desc = (
        card.get("desc")
        or raw.get("desc")
        or ""
    )

    interact = card.get("interact_info") or raw.get("interact_info") or {}
    if isinstance(interact, str):
        interact = {}

    def safe_int(v):
        try:
            return int(str(v).replace(",", "").replace("万", "0000"))
        except Exception:
            return 0

    tag_list = card.get("tag_list") or raw.get("tag_list") or []
    tags = [t.get("name", "") for t in tag_list if t.get("name")]

    # ── 提取图片 URL ──────────────────────────────────────
    image_list = card.get("image_list") or raw.get("image_list") or []
    images = []
    for img in image_list:
        if isinstance(img, dict):
            url = (
                img.get("url")
                or img.get("url_default")
                or img.get("url_pre")
                or ""
            )
            if url and url.startswith("http"):
                # 去掉 ! 后的缩略参数，获取原图
                clean = url.split("!")[0].split("?")[0]
                images.append(clean)

    return {
        "title": title.strip(),
        "content": desc.strip(),
        "likes": safe_int(interact.get("liked_count", 0)),
        "comments": safe_int(interact.get("comment_count", 0)),
        "collected": safe_int(interact.get("collected_count", 0)),
        "tags": tags,
        "images": images[:9],  # XHS 单篇最多 9 张
    }


# ────────────────────────────────────────────────────────────
# 浏览器上下文构建
# ────────────────────────────────────────────────────────────

async def _build_context(playwright, cookie_str: str = "", headless: bool = True):
    """创建浏览器上下文，注入 Cookie"""
    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )

    if cookie_str.strip():
        try:
            cookies = cookie_str_to_list(cookie_str)
            await context.add_cookies(cookies)
        except Exception as e:
            print(f"[XHSRealCrawler] Cookie 注入失败: {e}")

    return browser, context


# ────────────────────────────────────────────────────────────
# 单篇笔记爬取
# ────────────────────────────────────────────────────────────

async def fetch_note_by_url(url: str, cookie_str: str = "", headless: bool = True) -> Dict:
    """
    通过笔记 URL 获取笔记详细内容。

    降级链：API 拦截 → __INITIAL_STATE__ → 页面 HTML script → DOM（含图片）
    """
    from playwright.async_api import async_playwright

    note_id, xsec_token, xsec_source = parse_note_url(url)
    captured: Dict = {}
    all_xhs_apis: List[str] = []

    NOTE_API_PATTERNS = [
        "/api/sns/web/v1/feed",
        "/api/sns/web/v2/feed",
        "/api/sns/web/v3/feed",
        "/api/sns/web/v4/note/feed",
        "/api/sns/web/v1/note/detail",
        "/api/sns/web/v2/note/detail",
        "/api/sns/v3/page/notes",
        "/sns/web/v1/feed",
        "/api/redteam/note/",
    ]

    async def on_response(response):
        nonlocal captured
        resp_url = response.url
        # 调试：记录所有 XHS API
        if "xiaohongshu.com/api/" in resp_url and response.status == 200:
            short = resp_url.split("?")[0].replace("https://www.xiaohongshu.com", "")
            if short not in all_xhs_apis:
                all_xhs_apis.append(short)
                print(f"[debug] XHS API: {short}")

        if captured:
            return
        if not any(p in resp_url for p in NOTE_API_PATTERNS):
            return
        try:
            if response.status != 200:
                return
            body = await response.json()
            print(f"[fetch_note] 命中 API: {resp_url.split('?')[0]} | success={body.get('success')}")
            if not body.get("success"):
                return
            data = body.get("data", {})
            items = (
                data.get("items")
                or data.get("notes")
                or data.get("note_list")
                or ([data] if data.get("title") or data.get("desc") else [])
            )
            if items:
                captured = parse_note_card(items[0])
                card = items[0].get("note_card", items[0])
                user = card.get("user", {})
                captured["author_name"] = user.get("nickname", "")
                captured["author_id"] = user.get("userid", "")
                captured["note_id"] = note_id or card.get("id", "")
        except Exception as e:
            print(f"[fetch_note] 响应解析失败: {e}")

    async with async_playwright() as pw:
        browser, ctx = await _build_context(pw, cookie_str, headless)
        page = await ctx.new_page()
        page.on("response", on_response)

        try:
            print(f"[fetch_note] 正在打开: {url}")
            await page.goto(url, wait_until="load", timeout=40_000)

            # 等待 API 响应（最多 15 秒）
            for _ in range(30):
                if captured:
                    break
                await asyncio.sleep(0.5)

            if not captured:
                print(f"[fetch_note] API 未捕获，共记录 {len(all_xhs_apis)} 个 API: {all_xhs_apis[:8]}")
                captured = await _extract_from_initial_state(page, note_id)

            if not captured:
                print("[fetch_note] 尝试从 HTML script 标签提取...")
                captured = await _extract_from_html_script(page, note_id)

            if not captured:
                print("[fetch_note] 尝试 DOM 提取...")
                captured = await _extract_from_dom(page)
                captured["note_id"] = note_id

            # 无论哪种来源，如果没有图片则补充提取
            if not captured.get("images"):
                captured["images"] = await _extract_images_from_page(page)

        except Exception as e:
            print(f"[fetch_note] 导航错误: {e}")
        finally:
            await browser.close()

    return captured


async def fetch_user_by_profile_url(
    profile_url: str,
    cookie_str: str = "",
    max_posts: int = 15,
    headless: bool = True,
) -> Dict:
    """
    通过用户主页 URL 获取该用户的所有笔记

    原理：
      打开用户主页 → 拦截 /api/sns/web/v1/user_posted 响应 →
      下滑页面触发分页加载 → 汇总所有笔记
    """
    from playwright.async_api import async_playwright

    user_id = parse_profile_url(profile_url)
    if not user_id:
        raise ValueError(f"无法从 URL 解析 user_id: {profile_url}")

    posts: List[Dict] = []
    user_info: Dict = {}

    async def on_response(response):
        nonlocal posts, user_info
        resp_url = response.url

        # 拦截笔记列表
        if "/api/sns/web/v1/user_posted" in resp_url:
            try:
                body = await response.json()
                if body.get("success"):
                    notes = body.get("data", {}).get("notes", [])
                    for n in notes:
                        parsed = parse_note_card(n)
                        if parsed.get("title") or parsed.get("content"):
                            posts.append(parsed)
            except Exception as e:
                print(f"[fetch_user] 笔记列表解析失败: {e}")

        # 拦截用户信息
        if (
            "/api/sns/web/v1/user/otherinfo" in resp_url
            or "/api/sns/web/v1/user/selfinfo" in resp_url
        ):
            try:
                body = await response.json()
                if body.get("success"):
                    basic = body.get("data", {}).get("basic_info", {})
                    user_info.update(
                        {
                            "name": basic.get("nickname", ""),
                            "bio": basic.get("desc", ""),
                            "followers": str(basic.get("fans", 0)),
                        }
                    )
            except Exception as e:
                print(f"[fetch_user] 用户信息解析失败: {e}")

    async with async_playwright() as pw:
        browser, ctx = await _build_context(pw, cookie_str, headless)
        page = await ctx.new_page()
        page.on("response", on_response)

        try:
            print(f"[fetch_user] 正在打开主页: {profile_url}")
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)

            # 滚动加载更多
            scroll_times = max(3, max_posts // 5)
            for i in range(scroll_times):
                if len(posts) >= max_posts:
                    break
                await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                await asyncio.sleep(2)
                print(f"[fetch_user] 已加载 {len(posts)} 篇笔记...")

        except Exception as e:
            print(f"[fetch_user] 导航错误: {e}")
        finally:
            await browser.close()

    return {
        "name": user_info.get("name") or f"用户_{user_id[:8]}",
        "bio": user_info.get("bio", ""),
        "followers": user_info.get("followers", ""),
        "avatar": "🔴",
        "posts": posts[:max_posts],
    }


# ────────────────────────────────────────────────────────────
# 多个笔记 URL 批量爬取
# ────────────────────────────────────────────────────────────

async def fetch_notes_by_urls(
    urls: List[str],
    cookie_str: str = "",
    headless: bool = True,
    delay: float = 2.0,
) -> List[Dict]:
    """
    批量获取多个笔记 URL 的内容

    urls: 笔记 URL 列表
    delay: 每次请求间隔秒数（避免频率过高）
    """
    results = []
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        print(f"[批量爬取] {i+1}/{len(urls)}: {url[:60]}...")
        try:
            note = await fetch_note_by_url(url, cookie_str, headless)
            if note.get("title") or note.get("content"):
                results.append(note)
        except Exception as e:
            print(f"[批量爬取] 失败: {e}")
        if i < len(urls) - 1:
            await asyncio.sleep(delay)
    return results


# ────────────────────────────────────────────────────────────
# 备用数据提取（降级链）
# ────────────────────────────────────────────────────────────

async def _extract_from_initial_state(page, note_id: str = "") -> Dict:
    """从 window.__INITIAL_STATE__ 提取笔记数据（XHS SSR 数据）"""
    try:
        state = await page.evaluate("() => window.__INITIAL_STATE__")
        if not state or not isinstance(state, dict):
            return {}

        print(f"[fetch_note] __INITIAL_STATE__ 顶层 keys: {list(state.keys())[:12]}")

        note_data = None

        # 路径 1: noteCache / noteDetailMap
        for cache_key in ("noteCache", "note", "noteDetail"):
            cache = state.get(cache_key)
            if not isinstance(cache, dict):
                continue
            for map_key in ("noteDetailMap", "noteCache", "detailMap"):
                detail_map = cache.get(map_key, {})
                if not isinstance(detail_map, dict):
                    continue
                if note_id and note_id in detail_map:
                    note_data = detail_map[note_id]
                    break
                elif detail_map:
                    note_data = next(iter(detail_map.values()), None)
                    break
            if note_data:
                break

        # 路径 2: feed / items
        if not note_data:
            for feed_key in ("feed", "homeFeed", "explore"):
                feed = state.get(feed_key)
                if not isinstance(feed, dict):
                    continue
                items = feed.get("items") or feed.get("notes") or []
                if items:
                    note_data = items[0]
                    break

        # 路径 3: 递归搜索有 title+desc 的字典
        if not note_data:
            def _find_note(obj, depth=0):
                if depth > 4 or not isinstance(obj, dict):
                    return None
                if (obj.get("title") or obj.get("desc")) and obj.get("interact_info"):
                    return obj
                for v in obj.values():
                    found = _find_note(v, depth + 1)
                    if found:
                        return found
                return None
            note_data = _find_note(state)

        if not note_data:
            print("[fetch_note] __INITIAL_STATE__ 中未找到笔记数据")
            return {}

        result = parse_note_card(note_data)
        result["note_id"] = note_id
        result["source"] = "initial_state"
        card = note_data.get("note_card", note_data)
        user = card.get("user", {})
        result["author_name"] = user.get("nickname", "")
        return result

    except Exception as e:
        print(f"[fetch_note] __INITIAL_STATE__ 提取失败: {e}")
        return {}


async def _extract_from_html_script(page, note_id: str = "") -> Dict:
    """
    从页面 HTML 的 <script> 标签中查找嵌入的 JSON 数据。
    XHS 部分版本把数据以 JSON 字符串形式嵌在 script 中。
    """
    try:
        html = await page.content()
        # 匹配常见模式: window.__INITIAL_STATE__={"..."}
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\})(?=\s*;?\s*</script>)',
            r'"noteDetail"\s*:\s*(\{.+?"interact_info".+?\})',
            r'"desc"\s*:\s*"[^"]{10,}".{0,500}"title"\s*:\s*"[^"]{2,}"',
        ]
        import re as _re
        for pat in patterns:
            m = _re.search(pat, html, _re.DOTALL)
            if m:
                try:
                    raw = json.loads(m.group(1))
                    result = parse_note_card(raw)
                    if result.get("title") or result.get("content"):
                        result["note_id"] = note_id
                        result["source"] = "html_script"
                        print(f"[fetch_note] HTML script 提取成功: title={result.get('title', '')[:30]}")
                        return result
                except Exception:
                    pass
    except Exception as e:
        print(f"[fetch_note] HTML script 提取失败: {e}")
    return {}


async def _extract_images_from_page(page) -> List[str]:
    """从页面 img 标签提取小红书 CDN 图片 URL"""
    images = []
    try:
        img_els = await page.query_selector_all(
            "img[src*='xhscdn'], img[src*='xiaohongshu'], "
            "img[src*='sns-img'], img[src*='ci.xiaohongshu']"
        )
        for el in img_els[:9]:
            src = await el.get_attribute("src")
            if src and src.startswith("http"):
                # 去掉缩略参数
                clean = src.split("!")[0].split("?")[0]
                # 过滤掉太小的图（头像等）
                if clean not in images:
                    images.append(clean)
        if images:
            print(f"[fetch_note] 从页面 img 标签提取到 {len(images)} 张图片")
    except Exception as e:
        print(f"[fetch_note] 图片提取失败: {e}")
    return images


async def _extract_from_dom(page) -> Dict:
    """
    最后降级：从页面 DOM 文字提取内容。
    （选择器随 XHS 版本变化，可能不稳定）
    """
    title = ""
    content = ""
    tags = []

    for sel in ["#detail-title", ".note-content .title", ".title", "[class*='title']", "h1"]:
        try:
            el = await page.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                if t and len(t) > 2:
                    title = t
                    break
        except Exception:
            pass

    for sel in ["#detail-desc", ".note-content .desc", ".desc", "[class*='desc']", "[class*='content']"]:
        try:
            el = await page.query_selector(sel)
            if el:
                c = (await el.inner_text()).strip()
                if c and len(c) > 5:
                    content = c
                    break
        except Exception:
            pass

    try:
        tag_els = await page.query_selector_all("a[class*='tag'], [class*='tag-item'], [class*='hashtag']")
        for el in tag_els[:10]:
            t = (await el.inner_text()).strip().lstrip("#")
            if t and len(t) < 20:
                tags.append(t)
    except Exception:
        pass

    return {
        "title": title,
        "content": content,
        "likes": 0,
        "comments": 0,
        "tags": tags,
        "images": [],
        "source": "dom",
    }



# ────────────────────────────────────────────────────────────
# 同步包装（供 Flask 调用）
# ────────────────────────────────────────────────────────────

def sync_fetch_note(url: str, cookie_str: str = "") -> Dict:
    """同步版本，供 Flask 路由直接调用"""
    return asyncio.run(fetch_note_by_url(url, cookie_str))


def sync_fetch_user(profile_url: str, cookie_str: str = "", max_posts: int = 15) -> Dict:
    """同步版本，供 Flask 路由直接调用"""
    return asyncio.run(fetch_user_by_profile_url(profile_url, cookie_str, max_posts))


def sync_fetch_notes(urls: List[str], cookie_str: str = "") -> List[Dict]:
    """同步版本，供 Flask 路由直接调用"""
    return asyncio.run(fetch_notes_by_urls(urls, cookie_str))
