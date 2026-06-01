"""
图片视觉风格分析模块

流程：
  1. 从笔记数据中提取图片 URL
  2. 下载图片 → base64 编码
  3. 调用 Vision LLM，按指定 prompt 提取 5 个维度标签
  4. 多图聚合 → 输出视觉风格画像 + AI 绘图提示词

要求：API Key 对应的模型必须支持视觉能力（gpt-4o / gpt-4o-mini / claude-3.5 等）
"""

import os
import json
import base64
from collections import Counter
from typing import Dict, List, Optional


# ── Prompt ────────────────────────────────────────────────────────────────────

VISUAL_ANALYSIS_PROMPT = """\
# Role
你是一位顶级的小红书视觉总监兼资深 AI 绘画提示词工程师。你拥有极致的审美，擅长解构爆款图文笔记的视觉密码。

# Task
请仔细分析用户上传的参考图片，将其核心视觉特征精准拆解为 5 个指定维度，并提取出具有"小红书高端网感"的中文短语标签。

# Guidelines & Constraints
1. **词汇风格要求：** 提取的标签必须是简短、精炼的名词或动宾短语（建议 3-6 个字）。拒绝长句描述。必须带有强烈的"小红书美学"色彩（例如：用"丁达尔光"代替"有光束"，用"极简工位"代替"普通的桌子"，用"慵懒家居服"代替"穿着睡衣"）。
2. **提取维度规范：**
   - **主体 (subject)：** 画面核心人物的身份、气质、穿搭，或核心静物的形态特写（如：气质白领、局部手部特写、浓郁膏体）。提取 2-3 个标签。
   - **动作 (action)：** 人物的行为姿态，或产品的使用状态（如：伏案办公、随手撕开、优雅捏取）。提取 2-3 个标签。若为纯静物无动作，可输出"静物展示"。
   - **光影 (lighting)：** 画面的光线来源、色调氛围、明暗质感（如：治愈奶油光、百叶窗投影、局部聚光）。提取 2-3 个标签。
   - **环境 (environment)：** 画面背景、核心道具、空间氛围（如：原木茶几、高颜值保温杯、亚麻地毯）。提取 2-4 个标签。
   - **构图 (composition)：** 镜头的视角、景深、排版方式（如：微距特写、俯视平铺、三分法留白）。提取 2-3 个标签。
3. **输出格式强制要求：** 必须且只能输出一个合法的 JSON 对象，不要包含任何额外的 markdown 标记（如 ```json ）、解释性文字或换行符。前端将直接解析该 JSON。
4. 从以下 6 个场景库中，推断这张图片最符合哪一个场景，并返回对应的 Scene_ID。

Scene_ID 枚举表（只能选择一个）：
OFFICE=办公职场, HOME=居家生活, LIFESTYLE_SEEDING=生活化种草, PARENT_CHILD=温馨亲子, SCIENCE=干货科普, GIFT=送礼攻略

# JSON Output Format
{"Scene_ID":"OFFICE","Scene_Name":"办公职场","主体":["标签1","标签2"],"动作":["标签1","标签2"],"光影":["标签1","标签2"],"环境":["标签1","标签2","标签3"],"构图":["标签1","标签2"]}"""


SCENE_MAP = {
    "OFFICE": "办公职场",
    "HOME": "居家生活",
    "LIFESTYLE_SEEDING": "生活化种草",
    "PARENT_CHILD": "温馨亲子",
    "SCIENCE": "干货科普",
    "GIFT": "送礼攻略",
}

SCENE_EMOJI = {
    "OFFICE": "💼",
    "HOME": "🏠",
    "LIFESTYLE_SEEDING": "✨",
    "PARENT_CHILD": "👶",
    "SCIENCE": "🔬",
    "GIFT": "🎁",
}

# ── Image Download ────────────────────────────────────────────────────────────

def _download_as_base64(url: str) -> Optional[str]:
    """
    下载图片并转为 base64 data URI。
    XHS CDN 图片需要 Referer 头，否则返回 403。
    """
    try:
        import httpx
        headers = {
            "Referer": "https://www.xiaohongshu.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()

        ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if "webp" in ct:
            mime = "image/webp"
        elif "png" in ct:
            mime = "image/png"
        else:
            mime = "image/jpeg"

        b64 = base64.b64encode(resp.content).decode()
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"[ImageAnalyzer] 下载失败 {url[:60]}: {e}")
        return None


def normalize_xhs_image_url(raw_url: str) -> str:
    """
    规范化小红书图片 URL。
    XHS CDN URL 常见格式：
      http://sns-img-hw.xhscdn.com/{file_id}!nd_dft_wgth_webp_3
    去掉 ! 之后的处理参数，获得原始图片。
    """
    if "!" in raw_url:
        return raw_url.split("!")[0]
    # 去掉 query string 的 format/size 参数
    if "?" in raw_url:
        base = raw_url.split("?")[0]
        # 保留 xhscdn URL
        if "xhscdn" in base or "xhslink" in base:
            return base
    return raw_url


# ── ImageAnalyzer ─────────────────────────────────────────────────────────────

class ImageAnalyzer:
    DIMENSIONS = ["主体", "动作", "光影", "环境", "构图"]
    DIM_LIMITS = {"主体": 4, "动作": 3, "光影": 4, "环境": 6, "构图": 4}

    def __init__(self):
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # ── 单图分析 ─────────────────────────────────────────────────────────────

    def analyze_single(
        self, image_url: str, api_key: str, model: str = "gpt-4o-mini"
    ) -> Optional[Dict]:
        """调用 Vision LLM 分析单张图片"""
        try:
            from openai import OpenAI
        except ImportError:
            return None

        img_data = _download_as_base64(normalize_xhs_image_url(image_url))
        if not img_data:
            return None

        client = OpenAI(api_key=api_key, base_url=self.base_url)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISUAL_ANALYSIS_PROMPT},
                        {"type": "image_url", "image_url": {"url": img_data}},
                    ],
                }],
                temperature=0.1,
                max_tokens=512,
                # 部分模型不支持 response_format，先不强制
            )
            raw = resp.choices[0].message.content.strip()
            # 兼容 ```json ... ``` 包裹
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            result["_source_url"] = image_url
            return result
        except Exception as e:
            print(f"[ImageAnalyzer] Vision API 失败: {e}")
            return None

    # ── 批量分析 ─────────────────────────────────────────────────────────────

    def analyze_batch(
        self,
        image_urls: List[str],
        api_key: str,
        model: str = "gpt-4o-mini",
        max_images: int = 6,
    ) -> Dict:
        """
        批量分析图片（最多 max_images 张），聚合为统一视觉画像。

        max_images 建议 4-6：兼顾准确性和 API 成本。
        """
        results = []
        urls = list(dict.fromkeys(image_urls))[:max_images]  # 去重 + 截取

        for i, url in enumerate(urls):
            print(f"[ImageAnalyzer] 分析图片 {i+1}/{len(urls)}: {url[:60]}...")
            r = self.analyze_single(url, api_key, model)
            if r:
                results.append(r)

        if not results:
            return {"error": "所有图片分析失败，请检查图片 URL 是否可访问，或模型是否支持视觉"}

        return self._aggregate(results)

    # ── 聚合 ─────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[Dict]) -> Dict:
        """多图分析结果聚合 → 统一视觉画像"""
        scene_counter: Counter = Counter()
        tag_counters = {d: Counter() for d in self.DIMENSIONS}

        for r in results:
            scene_counter[r.get("Scene_ID", "LIFESTYLE_SEEDING")] += 1
            for dim in self.DIMENSIONS:
                for tag in r.get(dim, []):
                    if tag and isinstance(tag, str):
                        tag_counters[dim][tag] += 1

        top_scene = scene_counter.most_common(1)[0][0]

        profile: Dict = {
            "Scene_ID": top_scene,
            "Scene_Name": SCENE_MAP.get(top_scene, top_scene),
            "Scene_Emoji": SCENE_EMOJI.get(top_scene, "✨"),
            "scene_distribution": {
                SCENE_MAP.get(k, k): v for k, v in scene_counter.items()
            },
            "analyzed_count": len(results),
            "per_image": results,
        }

        for dim in self.DIMENSIONS:
            limit = self.DIM_LIMITS.get(dim, 4)
            profile[dim] = [tag for tag, _ in tag_counters[dim].most_common(limit)]

        return profile

    # ── 生成 AI 绘图提示词 ────────────────────────────────────────────────────

    @staticmethod
    def build_draw_prompt(visual_profile: Dict, topic: str = "") -> str:
        """
        将视觉画像转化为 AI 绘图提示词
        适配 Midjourney / Stable Diffusion / 即梦 / 可图 等
        """
        scene = visual_profile.get("Scene_Name", "生活化种草")
        parts = {
            "主体": visual_profile.get("主体", []),
            "动作": visual_profile.get("动作", []),
            "光影": visual_profile.get("光影", []),
            "环境": visual_profile.get("环境", []),
            "构图": visual_profile.get("构图", []),
        }

        topic_str = f"主题为【{topic}】，" if topic else ""

        prompt_cn = (
            f"小红书{scene}风格图片，{topic_str}"
            f"画面主体：{'、'.join(parts['主体'])}，"
            f"动作姿态：{'、'.join(parts['动作'])}，"
            f"光线氛围：{'、'.join(parts['光影'])}，"
            f"环境道具：{'、'.join(parts['环境'])}，"
            f"构图方式：{'、'.join(parts['构图'])}，"
            f"高端质感，精致细腻，小红书爆款美学，竖版构图"
        )

        # 同时生成英文 Midjourney 版
        en_tags = []
        for tags in parts.values():
            en_tags.extend(tags)
        prompt_en = (
            f"xiaohongshu {scene} aesthetic style, {topic_str}"
            f"high quality, delicate, trendy Chinese social media style, "
            f"portrait ratio 3:4, --ar 3:4 --style raw --q 2"
        )

        return {"chinese": prompt_cn, "english": prompt_en, "combined": prompt_cn}


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_images_from_posts(posts: List[Dict], max_per_post: int = 3) -> List[str]:
    """从笔记列表中提取所有图片 URL"""
    urls = []
    for p in posts:
        imgs = p.get("images", [])
        urls.extend(imgs[:max_per_post])
    return list(dict.fromkeys(urls))  # 去重
