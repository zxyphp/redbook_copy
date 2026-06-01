"""
内容生成模块

根据风格画像生成符合目标账号表达规律的小红书笔记。

支持两种模式：
  • template  — 基于模板的规则生成（无需 API Key）
  • llm       — 调用 LLM 进行原创生成（需要 API Key）
"""

import os
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
        """规则模板生成：用于没有 API Key 的 Demo 兜底，不追求最终发布质量。"""

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

        freq = profile.get("emoji_frequency", "中频")
        if "高频" in freq:
            emoji_n = 3
        elif "低频" in freq:
            emoji_n = 1
        else:
            emoji_n = 2

        def pick_emojis(n=emoji_n):
            return " ".join(random.sample(emoji_pool, min(n, len(emoji_pool))))

        openings = profile.get("opening_patterns", [])
        if openings:
            opening_base = random.choice(openings)
            for sep in ["！", "：", "，", "。", "!", ":", ","]:
                if sep in opening_base:
                    opening_base = opening_base.split(sep)[0] + sep
                    break
        else:
            opening_base = "今天给大家分享"

        closings = profile.get("closing_patterns", [])
        closing = random.choice(closings) if closings else "欢迎评论区交流～"

        existing_tags = profile.get("topics", [])[:5]
        topic_words = topic.replace("，", ",").replace("、", ",").split(",")
        extra_tags = [w.strip() for w in topic_words if len(w.strip()) >= 2]
        all_tags = list(dict.fromkeys(extra_tags + existing_tags))[:8]
        tag_str = " ".join(f"#{t}" for t in all_tags)

        formality = profile.get("formality", "口语化")
        if "非常随意" in formality or "口语" in formality:
            tone_suffix = "！！"
            tone_filler = "真的很适合收藏"
        elif "正式" in formality:
            tone_suffix = "。"
            tone_filler = "建议重点关注"
        else:
            tone_suffix = "！"
            tone_filler = "可以先记住这几点"

        title_emoji = random.choice(emoji_pool)
        title = f"{topic}｜{tone_filler}{title_emoji}"

        emoji1 = pick_emojis(1)
        emoji2 = pick_emojis(1)
        emoji3 = pick_emojis(1)

        content = f"""{opening_base}{topic}{tone_suffix} {emoji1}

先说结论：不要只看表面，关键是先搞清楚适合谁、怎么做、哪些坑要避开。

{emoji2} 【适合人群】
→ 正在关注「{topic}」但不知道怎么开始的人
→ 想要一份简单清单，先快速判断方向的人
→ 不想被复杂信息绕晕，只想抓重点的人

{emoji3} 【可以先做这3步】
✅ 第一步：先明确自己的真实需求，不要一上来就照搬别人
✅ 第二步：把核心信息拆成“做法 / 注意点 / 不适合情况”
✅ 第三步：执行后记录反馈，再决定是否继续加深

💡 避坑提醒：
如果内容里出现绝对化承诺，或者只讲情绪不讲具体做法，就要谨慎一点。

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

        examples_text = ""
        for i, p in enumerate(sample_posts[:3], 1):
            examples_text += f"\n\n--- 参考笔记{i} ---\n标题：{p.get('title', '')}\n{p.get('content', '')}"

        profile_text = json.dumps(profile, ensure_ascii=False, indent=2)

        prompt = f"""你是一位专业的小红书原创内容创作者。请根据以下风格画像，为主题「{topic}」创作一篇原创小红书笔记。

## 风格画像
{profile_text}

## 参考笔记
{examples_text}

## 创作原则
1. 参考的是结构、节奏、语气、分段习惯、标签策略，不允许复制参考笔记的句子、经历、地点、人设细节。
2. 内容必须围绕「{topic}」重新组织，给出具体信息、适合人群、操作建议或避坑提醒。
3. 不要输出空泛模板句，例如“独特之处”“名不虚传”“收获超过预期”。
4. 不要夸大效果，不要写绝对化承诺；养生/健康类主题必须避免诊断、治疗、根治、排毒等高风险表达。
5. 标题要有小红书感，但优先明确人群、场景、痛点或结果。

## 输出要求
请以 JSON 格式返回：
- title: 标题
- content: 正文，保留换行和 emoji
- tags: 5-8 个标签数组，不带 #

只返回 JSON，不要其他文字。"""

        try:
            resp = client.chat.completions.create(
                model=eff_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是专业的小红书原创内容创作者。"
                            "你学习的是表达规律，不复制参考文本。"
                            "创作内容要真实自然、有信息密度、低 AI 味。只返回 JSON。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )
            result = json.loads(resp.choices[0].message.content)
            result["mode"] = "llm"
            return result

        except Exception as exc:
            print(f"[ContentGenerator] LLM failed: {exc}. Falling back to template.")
            result = self._generate_template(profile, topic, sample_posts)
            result["error"] = str(exc)
            return result
