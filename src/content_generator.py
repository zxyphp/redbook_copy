"""
内容生成模块

根据风格画像生成符合目标账号风格的小红书笔记。

支持两种模式：
  • template  — 基于模板的规则生成（无需 API Key）
  • llm       — 调用 LLM 进行深度仿写（需要 API Key）
"""

import os
import re
import json
import random
from typing import Dict, List, Optional


# ────────────────────────────────────────────────────────────
# 通用 Emoji 集合（按类别）
# ────────────────────────────────────────────────────────────

EMOJI_SETS = {
    "food": ["🍜", "🍰", "🧋", "🍳", "😋", "🔥", "✨", "💕", "📍", "⏰", "💰", "🥺", "😭", "👇"],
    "travel": ["✈️", "🗺️", "📍", "🌅", "🏨", "💰", "🗓️", "⏰", "❤️", "🚗", "🌟", "📸"],
    "career": ["✅", "❌", "💡", "🔍", "⚡", "📊", "💼", "🎯", "📝", "→", "❤️"],
    "fashion": ["👗", "🧥", "👟", "👖", "🧣", "✨", "⭐", "💡", "📐", "⚠️", "🧤"],
    "general": ["✨", "💕", "🌟", "❤️", "👇", "📍", "💡", "🔥", "💰", "✅"],
}


# ────────────────────────────────────────────────────────────
# ContentGenerator
# ────────────────────────────────────────────────────────────

class ContentGenerator:
    def __init__(self):
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # ── Public entry ──────────────────────────────────────────
    def generate(
        self,
        style_profile: Dict,
        topic: str,
        sample_posts: List[Dict],
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict:
        """
        生成符合风格画像的小红书笔记。
        返回 {title, content, tags, mode}
        """
        if api_key:
            return self._generate_with_llm(style_profile, topic, sample_posts, api_key, base_url or self.base_url, model or self.model)
        return self._generate_template(style_profile, topic, sample_posts)

    # ── Template-based ────────────────────────────────────────
    def _generate_template(self, profile: Dict, topic: str, sample_posts: List[Dict]) -> Dict:
        """规则模板生成"""

        # 确定 emoji 集合
        topics_str = " ".join(profile.get("topics", []))
        if any(k in topics_str for k in ["美食", "探店", "餐厅", "吃", "拉面", "甜品"]):
            emoji_pool = EMOJI_SETS["food"]
        elif any(k in topics_str for k in ["旅游", "旅行", "攻略", "景点"]):
            emoji_pool = EMOJI_SETS["travel"]
        elif any(k in topics_str for k in ["职场", "面试", "工作", "汇报"]):
            emoji_pool = EMOJI_SETS["career"]
        elif any(k in topics_str for k in ["穿搭", "时尚", "单品", "显瘦"]):
            emoji_pool = EMOJI_SETS["fashion"]
        else:
            emoji_pool = EMOJI_SETS["general"]

        # 判断频率
        freq = profile.get("emoji_frequency", "中频")
        if "高频" in freq:
            emoji_n = 3
        elif "低频" in freq:
            emoji_n = 1
        else:
            emoji_n = 2

        def pick_emojis(n=emoji_n):
            return " ".join(random.sample(emoji_pool, min(n, len(emoji_pool))))

        # 开头句式
        openings = profile.get("opening_patterns", [])
        if openings:
            opening_base = random.choice(openings)
            # 替换掉原来的具体内容，留通用前缀
            for sep in ["！", "：", "，", "。", "!", ":", ","]:
                if sep in opening_base:
                    opening_base = opening_base.split(sep)[0] + sep
                    break
        else:
            opening_base = "今天给大家分享"

        # 结尾句式
        closings = profile.get("closing_patterns", [])
        closing = random.choice(closings) if closings else "欢迎评论区交流～"

        # 话题标签
        existing_tags = profile.get("topics", [])[:5]
        topic_words = topic.replace("，", ",").replace("、", ",").split(",")
        extra_tags = [w.strip() for w in topic_words if len(w.strip()) >= 2]
        all_tags = list(dict.fromkeys(extra_tags + existing_tags))[:8]
        tag_str = " ".join(f"#{t}" for t in all_tags)

        # 正式程度对应的语气字
        formality = profile.get("formality", "口语化")
        if "非常随意" in formality or "口语" in formality:
            tone_suffix = "！！"
            tone_filler = "真的超级"
        elif "正式" in formality:
            tone_suffix = "。"
            tone_filler = "值得重点关注的是"
        else:
            tone_suffix = "！"
            tone_filler = "非常推荐的是"

        # 生成标题
        title_emoji = random.choice(emoji_pool)
        title = f"{topic}｜{tone_filler}这个{title_emoji}"

        # 生成正文
        emoji1 = pick_emojis(1)
        emoji2 = pick_emojis(1)
        emoji3 = pick_emojis(1)

        content = f"""{opening_base}{topic}{tone_suffix} {emoji1}

先说结论：{topic}真的值得深入了解！

{emoji2} 【核心亮点】
→ 第一点：{topic}最吸引人的地方在于它的独特之处
→ 第二点：经过亲身体验，确实名不虚传
→ 第三点：性价比方面完全超出预期{tone_suffix}

{emoji3} 【实用信息】
✅ 适合人群：对{topic}感兴趣的朋友
✅ 入门建议：先从基础开始，循序渐进
✅ 避坑提醒：注意这几个容易忽略的细节

💡 个人感受：
体验过之后觉得，{topic}完全值得花时间去深入研究。
{tone_filler}它带来的收获超过预期{tone_suffix}

{closing}

{tag_str}"""

        return {
            "mode": "template",
            "title": title,
            "content": content.strip(),
            "tags": all_tags,
        }

    # ── LLM-based ─────────────────────────────────────────────
    def _generate_with_llm(
        self,
        profile: Dict,
        topic: str,
        sample_posts: List[Dict],
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict:
        try:
            from openai import OpenAI
        except ImportError:
            return {**self._generate_template(profile, topic, sample_posts), "error": "openai 包未安装"}

        eff_url = base_url or self.base_url
        eff_model = model or self.model
        print(f"[ContentGenerator] LLM | base_url={eff_url} | model={eff_model}")
        client = OpenAI(api_key=api_key, base_url=eff_url)

        # 准备范例
        examples_text = ""
        for i, p in enumerate(sample_posts[:3], 1):
            examples_text += f"\n\n--- 参考笔记{i} ---\n标题：{p.get('title', '')}\n{p.get('content', '')}"

        profile_text = json.dumps(profile, ensure_ascii=False, indent=2)

        prompt = f"""你是一位专业的小红书内容创作者。请根据以下风格画像，模仿该账号的风格创作一篇关于「{topic}」的小红书笔记。

## 风格画像
{profile_text}

## 参考笔记（仅参考风格，不要直接复制内容）
{examples_text}

## 创作要求
1. 标题：吸引眼球，符合该账号的标题风格（可带emoji、数字、符号）
2. 正文：
   - 严格模仿该账号的语气、口吻、用词习惯
   - 使用相似频率的 emoji
   - 采用相似的内容结构（开头方式、分段习惯、列表格式等）
   - 使用相似的结尾互动引导
3. 标签：生成 5-8 个相关话题标签（不带#号）
4. 内容围绕「{topic}」展开，要有实质性内容，不能太空泛

请以 JSON 格式返回，字段：title（标题）、content（正文，保留换行和emoji）、tags（标签数组，不带#）

只返回 JSON，不要其他文字。"""

        try:
            resp = client.chat.completions.create(
                model=eff_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是专业的小红书内容创作者，擅长模仿不同账号的写作风格。"
                            "创作内容要真实自然，有实质内容，不能只有空洞的模板。只返回 JSON。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                # 注意: response_format 部分平台不支持，已移除
            )
            result = json.loads(resp.choices[0].message.content)
            result["mode"] = "llm"
            return result

        except Exception as exc:
            print(f"[ContentGenerator] LLM failed: {exc}. Falling back to template.")
            result = self._generate_template(profile, topic, sample_posts)
            result["error"] = str(exc)
            return result
