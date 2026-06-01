"""
Flask Web 应用入口
小红书风格蒸馏系统 — 后端 API
"""

import os
import re
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

from src.crawler import XHSCrawler
from src.style_analyzer import StyleAnalyzer
from src.content_generator import ContentGenerator

load_dotenv()

app = Flask(__name__)
crawler = XHSCrawler()
analyzer = StyleAnalyzer()
generator = ContentGenerator()

# ─── 从环境变量读取 LLM 配置（.env 优先于前端 modal）────────────
def _env_key():    return os.getenv("OPENAI_API_KEY",  "").strip()
def _env_url():    return os.getenv("OPENAI_BASE_URL", "").strip()
def _env_model():  return os.getenv("OPENAI_MODEL",    "").strip()

def _resolve_llm(data: dict):
    """
    优先级：.env 环境变量 > 前端 modal 输入。
    只要 .env 中设了 OPENAI_API_KEY，就用 .env 的值，
    避免前端残留错误 key 干扰。
    """
    env_key   = _env_key()
    env_url   = _env_url()
    env_model = _env_model()

    api_key  = env_key   or data.get("api_key",  "").strip() or None
    base_url = env_url   or data.get("base_url", "").strip() or None
    model    = env_model or data.get("model",    "").strip() or None
    return api_key, base_url, model


# ────────────────────────────────────────────────────────────
# Pages
# ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ────────────────────────────────────────────────────────────
# API — Step 1: 数据采集
# ────────────────────────────────────────────────────────────

@app.route("/api/crawl", methods=["POST"])
def api_crawl():
    """
    获取账号笔记数据
    Body: { mode: "mock"|"real", account_type: str, user_id: str, cookie: str }
    """
    data = request.get_json(force=True)
    mode = data.get("mode", "mock")

    try:
        if mode == "real":
            user_id = data.get("user_id", "").strip()
            cookie = data.get("cookie", "").strip()
            if not user_id:
                return jsonify({"error": "请输入用户 ID"}), 400
            account_data = crawler.get_user_posts(user_id, cookie)
        else:
            account_type = data.get("account_type", "food")
            account_data = crawler.get_mock_posts(account_type)

        # 统计摘要
        posts = account_data.get("posts", [])
        summary = {
            "name": account_data.get("name"),
            "bio": account_data.get("bio"),
            "followers": account_data.get("followers"),
            "avatar": account_data.get("avatar", "📖"),
            "post_count": len(posts),
            "avg_likes": int(sum(p.get("likes", 0) for p in posts) / max(len(posts), 1)),
            "posts": posts,
        }
        return jsonify({"success": True, "data": summary})

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ────────────────────────────────────────────────────────────
# API — Step 2: 风格蒸馏
# ────────────────────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """
    分析账号风格
    Body: { account_data, api_key?, base_url?, model? }
    .env 中的值优先于 body 中传入的值。
    """
    data = request.get_json(force=True)
    account_data = data.get("account_data")
    api_key, base_url, model = _resolve_llm(data)

    if not account_data or not account_data.get("posts"):
        return jsonify({"error": "请先获取账号数据"}), 400

    try:
        profile = analyzer.analyze(account_data, api_key=api_key, base_url=base_url, model=model)
        return jsonify({"success": True, "data": profile})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ────────────────────────────────────────────────────────────
# API — Step 3: 内容生成
# ────────────────────────────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    生成仿风格内容
    Body: { style_profile, topic, sample_posts?, api_key?, base_url?, model? }
    .env 中的值优先于 body 中传入的值。
    """
    data = request.get_json(force=True)
    profile      = data.get("style_profile")
    topic        = data.get("topic", "").strip()
    sample_posts = data.get("sample_posts", [])
    api_key, base_url, model = _resolve_llm(data)

    if not profile:
        return jsonify({"error": "请先完成风格分析"}), 400
    if not topic:
        return jsonify({"error": "请输入要写的话题"}), 400

    try:
        result = generator.generate(profile, topic, sample_posts, api_key=api_key, base_url=base_url, model=model)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500



# ────────────────────────────────────────────────────────────
# API — 测试 LLM 连接
# ────────────────────────────────────────────────────────────

@app.route("/api/test_llm", methods=["POST"])
def api_test_llm():
    """
    快速测试 API Key / Base URL / Model 是否可用
    Body: { api_key?, base_url?, model? }  —— .env 优先
    """
    from openai import OpenAI

    data = request.get_json(force=True)
    api_key, base_url, model = _resolve_llm(data)
    base_url = base_url or "https://api.openai.com/v1"
    model    = model    or "gpt-4o-mini"

    if not api_key:
        return jsonify({"error": "请先在 .env 中配置 OPENAI_API_KEY 或在弹窗中输入 API Key"}), 400

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复数字1"}],
            max_tokens=5,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip()
        return jsonify({"success": True, "reply": reply, "model": model})
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "invalid_api_key" in msg or "Incorrect API key" in msg:
            hint = "❌ API Key 错误：请核对是否从正确的控制台复制（百炼：bailian.console.aliyun.com）"
        elif "404" in msg or "model_not_found" in msg or "does not exist" in msg:
            hint = f"❌ 模型 [{model}] 不存在，请检查模型名称"
        elif "connection" in msg.lower() or "timeout" in msg.lower():
            hint = "❌ 连接超时，请检查网络或 Base URL 是否正确"
        else:
            hint = f"❌ {msg[:200]}"
        return jsonify({"error": hint}), 400


# ────────────────────────────────────────────────────────────
# API — 环境配置状态
# ────────────────────────────────────────────────────────────

@app.route("/api/env_config", methods=["GET"])
def api_env_config():
    """返回 .env 中的配置（.env 优先；不暴露完整 Key）"""
    raw_key   = _env_key()
    raw_url   = _env_url()
    raw_model = _env_model()
    return jsonify({
        "has_api_key": bool(raw_key),
        "api_key_hint": f"{raw_key[:6]}...{raw_key[-4:]}" if len(raw_key) >= 10 else ("***" if raw_key else ""),
        "base_url":  raw_url   or "https://api.openai.com/v1",
        "model":     raw_model or "gpt-4o-mini",
        "env_active": bool(raw_key),   # 告诉前端是否在用 env 配置
    })



# ────────────────────────────────────────────────────────────
# API — 图片代理（解决 XHS CDN 403 问题）
# ────────────────────────────────────────────────────────────

@app.route("/api/proxy/image")
def api_proxy_image():
    """
    代理访问 XHS CDN 图片，自动添加 Referer 头。
    浏览器直接加载 xhscdn.com 图片会 403，通过此接口中转。
    用法: /api/proxy/image?url=<encoded_xhs_cdn_url>
    """
    from flask import Response
    url = request.args.get("url", "").strip()
    if not url:
        return "missing url", 400
    # 白名单：只代理 XHS 相关域名
    allowed = ("xhscdn.com", "xiaohongshu.com", "xhslink.com", "ci.xiaohongshu.com")
    if not any(d in url for d in allowed):
        return "forbidden", 403
    try:
        import httpx
        headers = {
            "Referer": "https://www.xiaohongshu.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        ct = resp.headers.get("content-type", "image/jpeg")
        return Response(resp.content, content_type=ct,
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        print(f"[proxy/image] 失败: {e}")
        return str(e), 502


# ────────────────────────────────────────────────────────────
# API — 其他
# ────────────────────────────────────────────────────────────

@app.route("/api/mock_types", methods=["GET"])
def api_mock_types():
    types = {
        "food": {"label": "🍜 美食探店博主", "desc": "探店打卡、性价比美食"},
        "travel": {"label": "🌍 旅行攻略博主", "desc": "攻略干货、目的地推荐"},
        "career": {"label": "💼 职场干货博主", "desc": "职场技巧、成长建议"},
        "fashion": {"label": "👗 穿搭分享博主", "desc": "穿搭公式、单品推荐"},
    }
    return jsonify(types)


# ────────────────────────────────────────────────────────────
# API — 真实爬取（Playwright）
# ────────────────────────────────────────────────────────────

@app.route("/api/crawl/real", methods=["POST"])
def api_crawl_real():
    """
    真实爬取小红书数据（Playwright 方案）

    Body 格式（三选一）：
      单篇笔记: { mode: "note",    url: "https://www.xiaohongshu.com/explore/...", cookie: "..." }
      用户主页: { mode: "profile", url: "https://www.xiaohongshu.com/user/profile/...", cookie: "..." }
      批量笔记: { mode: "batch",   urls: ["url1","url2",...], cookie: "..." }
    """
    try:
        from src.real_crawler import sync_fetch_note, sync_fetch_user, sync_fetch_notes
    except ImportError as e:
        return jsonify({"error": f"Playwright 未安装: {e}，请运行 uv run playwright install chromium"}), 500

    data = request.get_json(force=True)
    mode = data.get("mode", "note")
    cookie = data.get("cookie", "").strip()

    try:
        if mode == "note":
            # ── 单篇笔记
            url = data.get("url", "").strip()
            if not url:
                return jsonify({"error": "请输入笔记 URL"}), 400
            note = sync_fetch_note(url, cookie)
            if not note or (not note.get("title") and not note.get("content")):
                return jsonify({"error": "未能获取笔记内容，请检查 URL 或 Cookie 是否有效"}), 400
            # 将单篇笔记包装为账号数据格式
            account_data = {
                "name": note.get("author_name") or "真实账号",
                "bio": "",
                "followers": "",
                "avatar": "🔴",
                "post_count": 1,
                "avg_likes": note.get("likes", 0),
                "posts": [note],
            }
            return jsonify({"success": True, "data": account_data})

        elif mode == "profile":
            # ── 用户主页
            url = data.get("url", "").strip()
            max_posts = int(data.get("max_posts", 15))
            if not url:
                return jsonify({"error": "请输入用户主页 URL"}), 400
            account_data = sync_fetch_user(url, cookie, max_posts)
            posts = account_data.get("posts", [])
            if not posts:
                return jsonify({"error": "未能获取任何笔记，请检查 URL 或登录状态"}), 400
            account_data["post_count"] = len(posts)
            account_data["avg_likes"] = int(
                sum(p.get("likes", 0) for p in posts) / max(len(posts), 1)
            )
            return jsonify({"success": True, "data": account_data})

        elif mode == "batch":
            # ── 批量笔记 URLs
            urls = data.get("urls", [])
            if isinstance(urls, str):
                urls = [u.strip() for u in urls.split("\n") if u.strip()]
            if not urls:
                return jsonify({"error": "请输入至少一个笔记 URL"}), 400
            notes = sync_fetch_notes(urls, cookie)
            if not notes:
                return jsonify({"error": "所有 URL 均获取失败"}), 400
            account_data = {
                "name": "批量笔记集合",
                "bio": f"共 {len(notes)} 篇笔记",
                "followers": "",
                "avatar": "📚",
                "post_count": len(notes),
                "avg_likes": int(sum(n.get("likes", 0) for n in notes) / max(len(notes), 1)),
                "posts": notes,
            }
            return jsonify({"success": True, "data": account_data})

        else:
            return jsonify({"error": f"未知 mode: {mode}"}), 400

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500



# ────────────────────────────────────────────────────────────
# API — 图片视觉风格分析
# ────────────────────────────────────────────────────────────

@app.route("/api/analyze/visual", methods=["POST"])
def api_analyze_visual():
    """
    分析笔记图片的视觉风格（Vision LLM）

    Body:
      {
        image_urls: ["url1", "url2", ...],   # 要分析的图片 URL 列表
        api_key: "sk-...",                    # 必须，需支持视觉能力的模型
        model: "gpt-4o-mini",                 # 可选
        max_images: 6,                        # 可选，最多分析几张
        topic: "咖啡日记"                     # 可选，用于生成绘图提示词
      }
    """
    from src.image_analyzer import ImageAnalyzer, extract_images_from_posts

    data = request.get_json(force=True)
    api_key, base_url, model = _resolve_llm(data)
    model = model or "gpt-4o-mini"
    max_images = int(data.get("max_images", 6))
    topic = data.get("topic", "").strip()

    if not api_key:
        return jsonify({"error": "图片分析需要配置 API Key（需支持视觉能力，如 gpt-4o-mini、qwen-vl-plus 等）"}), 400

    image_urls = data.get("image_urls") or []
    if not image_urls:
        posts = data.get("posts") or []
        image_urls = extract_images_from_posts(posts, max_per_post=3)

    if not image_urls:
        return jsonify({"error": "没有可分析的图片，请先获取真实笔记数据（Mock 数据无图片）"}), 400

    try:
        img_analyzer = ImageAnalyzer()
        img_analyzer.base_url = base_url or img_analyzer.base_url

        visual_profile = img_analyzer.analyze_batch(
            image_urls, api_key, model=model, max_images=max_images
        )

        if "error" in visual_profile:
            return jsonify({"error": visual_profile["error"]}), 400

        # 追加绘图提示词
        draw_prompt = ImageAnalyzer.build_draw_prompt(visual_profile, topic)
        visual_profile["draw_prompt"] = draw_prompt

        return jsonify({"success": True, "data": visual_profile})

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    print(f"\n🚀  小红书风格蒸馏系统启动成功！")
    print(f"🌐  访问地址: http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=debug)
