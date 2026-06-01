"""
小红书图片 URL 提取工具

用于解决笔记图片抓不到的问题：
  1. API 返回结构经常变化，图片可能出现在 image_list/images/image_info/url_list 等字段。
  2. 页面 DOM 中图片可能在 src/currentSrc/srcset/data-src/data-original/meta og:image/background-image 中。
  3. 小红书 CDN 图片常带 ! 或 query 缩略参数，需要统一规范化。

本模块只做 URL 解析和规范化，不负责绕过访问控制。
"""

import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


IMAGE_HOST_KEYWORDS = (
    "xhscdn.com",
    "xiaohongshu.com",
    "sns-img",
    "ci.xiaohongshu.com",
)

IMAGE_KEYS = {
    "url",
    "url_default",
    "url_pre",
    "url_size_large",
    "url_size_origin",
    "url_size_medium",
    "original",
    "origin",
    "src",
    "href",
    "image_url",
    "cover",
    "cover_url",
    "thumbnail",
    "trace_id",
    "file_id",
}

IMAGE_LIST_KEYS = {
    "image_list",
    "images",
    "image",
    "image_info",
    "cover",
    "cover_image",
    "url_list",
    "info_list",
    "stream",
}


def is_xhs_image_url(value: str) -> bool:
    """判断是否像小红书图片 URL。"""
    if not value or not isinstance(value, str):
        return False
    if not value.startswith(("http://", "https://")):
        return False
    host = (urlparse(value).hostname or "").lower()
    return any(key in host for key in IMAGE_HOST_KEYWORDS)


def normalize_image_url(url: str) -> str:
    """去掉常见缩略参数，尽量保留原图 URL。"""
    if not url:
        return ""
    url = url.strip()
    # srcset 中可能是 "url 2x" 或 "url 640w"
    url = url.split()[0]
    # 小红书 CDN 常用 ! 后缀表达裁剪/压缩参数
    if "!" in url:
        url = url.split("!", 1)[0]
    # 对 xhscdn 图片，query 多数是格式/尺寸参数；保留主路径更利于复用代理接口
    if "?" in url and any(key in url for key in IMAGE_HOST_KEYWORDS):
        url = url.split("?", 1)[0]
    return url


def _add_url(images: List[str], value: str, limit: int) -> None:
    if not isinstance(value, str):
        return
    url = normalize_image_url(value)
    if is_xhs_image_url(url) and url not in images and len(images) < limit:
        images.append(url)


def _iter_possible_urls(value: Any) -> Iterable[str]:
    """从字符串/列表/字典中递归枚举可能的图片 URL。"""
    if isinstance(value, str):
        yield value
        return

    if isinstance(value, list):
        for item in value:
            yield from _iter_possible_urls(item)
        return

    if isinstance(value, dict):
        for key, item in value.items():
            if key in IMAGE_KEYS or key in IMAGE_LIST_KEYS or isinstance(item, (dict, list, str)):
                yield from _iter_possible_urls(item)


def extract_images_from_api(raw: Dict, limit: int = 9) -> List[str]:
    """
    从 XHS API 原始结构中提取图片 URL。

    支持：
      - raw.note_card.image_list
      - raw.image_list
      - raw.images
      - image_info.url_list
      - cover/cover_image
      - 递归扫描常见图片字段
    """
    images: List[str] = []
    if not isinstance(raw, dict):
        return images

    card = raw.get("note_card", raw)
    candidates = [card, raw]

    # 优先从常见结构提取，保持顺序
    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        for key in IMAGE_LIST_KEYS:
            if key in obj:
                for url in _iter_possible_urls(obj.get(key)):
                    _add_url(images, url, limit)
        for key in IMAGE_KEYS:
            if key in obj:
                for url in _iter_possible_urls(obj.get(key)):
                    _add_url(images, url, limit)

    # 兜底递归扫描
    for url in _iter_possible_urls(card):
        _add_url(images, url, limit)
    for url in _iter_possible_urls(raw):
        _add_url(images, url, limit)

    return images[:limit]


def extract_urls_from_srcset(srcset: str) -> List[str]:
    """解析 img srcset。"""
    urls: List[str] = []
    if not srcset:
        return urls
    for part in srcset.split(","):
        url = part.strip().split()[0] if part.strip() else ""
        if url:
            urls.append(url)
    return urls


async def extract_images_from_dom(page, limit: int = 9) -> List[str]:
    """
    从页面 DOM 提取图片 URL。

    覆盖：
      - img src/currentSrc/srcset/data-src/data-original
      - source srcset
      - meta[property='og:image']
      - style background-image
    """
    images: List[str] = []

    async def add(value: str):
        _add_url(images, value, limit)

    try:
        # 1. img/source 标签属性
        elements = await page.query_selector_all("img, source")
        for el in elements:
            if len(images) >= limit:
                break
            for attr in ("src", "currentSrc", "data-src", "data-original", "data-lazy", "data-url"):
                value = await el.get_attribute(attr)
                if value:
                    await add(value)
            srcset = await el.get_attribute("srcset")
            for url in extract_urls_from_srcset(srcset or ""):
                await add(url)

        # 2. meta og:image / twitter:image
        metas = await page.query_selector_all("meta[property='og:image'], meta[name='twitter:image']")
        for meta in metas:
            if len(images) >= limit:
                break
            value = await meta.get_attribute("content")
            if value:
                await add(value)

        # 3. background-image
        bg_urls = await page.evaluate(
            """
            () => Array.from(document.querySelectorAll('*'))
              .map(el => getComputedStyle(el).backgroundImage)
              .filter(Boolean)
              .flatMap(bg => Array.from(bg.matchAll(/url\\(["']?(.*?)["']?\\)/g)).map(m => m[1]))
            """
        )
        for url in bg_urls or []:
            if len(images) >= limit:
                break
            await add(url)

    except Exception as exc:
        print(f"[xhs_image_extractor] DOM 图片提取失败: {exc}")

    return images[:limit]
