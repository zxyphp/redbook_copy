"""
风格蒸馏分析模块

支持两种模式：
  • rule_based  — 纯规则分析，无需 API Key，秒出结果
  • llm         — 调用 LLM 做深度语义分析，需要配置 API Key
"""

import os
import re
import json
from collections import Counter
from typing import Dict, List, Optional


# ────────────────────────────────────────────────────────────
# Emoji 提取
# ────────────────────────────────────────────────────────────

def extract_emojis(text: str) -> List[str]:
    pattern = re.compile(
        "[\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "]+",
        flags=re.UNICODE,
    )
    return pattern.findall(text)


# ────────────────────────────────────────────────────────────
# StyleAnalyzer
# ────────────────────────────────────────────────────────────

class StyleAnalyzer:
    def __init__(self):
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # ── Public entry ──────────────────────────────────────────
    def analyze(self, account_data: Dict, api_key: Optional[str] = None,
               base_url: Optional[str] = None, model: Optional[str] = None) -> Dict:
        """
        分析账号风格，返回结构化风格画像。

        api_key 为空时自动使用规则分析；有 Key 时使用 LLM 深度分析。
        base_url / model 优先使用传入值，覆盖环境变量默认值。
        """
        posts = account_data.get("posts", [])
        if not posts:
            return {"error": "没有找到任何笔记数据"}

        if api_key:
            eff_url = base_url or self.base_url
            eff_model = model or self.model
            return self._analyze_with_llm(account_data, posts, api_key, eff_url, eff_model)
        return self._analyze_rule_based(account_data, posts)

    # ── Rule-based ────────────────────────────────────────────
    def _analyze_rule_based(self, account_data: Dict, posts: List[Dict]) -> Dict:
        all_text = "\n".join(
            p.get("title", "") + "\n" + p.get("content", "") for p in posts
        )

        # ── Emoji 统计
        all_emoji_groups = extract_emojis(all_text)
        all_emojis: List[str] = []
        for g in all_emoji_groups:
            all_emojis.extend(list(g))
        emoji_counter = Counter(all_emojis)
        total_chars = max(len(all_text.replace("\n", "")), 1)
        emoji_density = len(all_emojis) / total_chars * 100

        # ── 标点统计
        exclamation = all_text.count("！") + all_text.count("!")
        question = all_text.count("？") + all_text.count("?")
        tilde = all_text.count("～") + all_text.count("~")
        period = all_text.count("。")

        # ── 字数统计
        avg_words = sum(len(p.get("content", "")) for p in posts) / len(posts)

        # ── 标签统计
        all_tags = [t for p in posts for t in p.get("tags", [])]
        avg_tags = len(all_tags) / len(posts)

        # ── 开头 / 结尾句式
        openings, closings = [], []
        for p in posts:
            lines = [l.strip() for l in p.get("content", "").split("\n") if l.strip()]
            if lines:
                openings.append(lines[0][:45])
            if len(lines) > 1:
                closings.append(lines[-1][:45])

        # ── Emoji 频率描述
        if emoji_density > 3:
            emoji_freq = "高频（每百字 3 个以上）"
        elif emoji_density > 1:
            emoji_freq = "中频（每百字 1-3 个）"
        else:
            emoji_freq = "低频（每百字 1 个以下）"

        # ── 语气
        if exclamation > (question + period) * 0.8:
            tone = "热情活泼，大量感叹号"
        elif question > exclamation:
            tone = "互动性强，善用反问与提问"
        elif period > exclamation * 2:
            tone = "稳重理性，语气客观沉稳"
        else:
            tone = "轻松自然，语气灵活多变"

        # ── 正式程度
        formal_words = ["建议", "分析", "总结", "结论", "框架", "逻辑", "策略", "方法论", "核心", "本质"]
        casual_words = ["姐妹", "宝子", "OMG", "绝了", "超级", "太好了", "啊啊", "好吃", "好看", "种草"]
        formal_cnt = sum(all_text.count(w) for w in formal_words)
        casual_cnt = sum(all_text.count(w) for w in casual_words)
        if formal_cnt > casual_cnt:
            formality = "偏专业正式"
        elif casual_cnt > formal_cnt * 3:
            formality = "非常随意口语化"
        else:
            formality = "口语化但不失条理"

        # ── 写作特点
        features = []
        if emoji_density > 2:
            features.append("大量 emoji 增强视觉感染力")
        if exclamation > 10:
            features.append("频繁使用感叹号传达热情")
        if question > 3:
            features.append("善用问句引发互动")
        if avg_words > 400:
            features.append(f"内容详尽（平均 {int(avg_words)} 字）")
        elif avg_words < 200:
            features.append(f"简洁精炼（平均 {int(avg_words)} 字）")
        else:
            features.append(f"字数适中（平均 {int(avg_words)} 字）")
        if avg_tags > 4:
            features.append(f"话题标签丰富（平均 {int(avg_tags)} 个）")
        if tilde > 5:
            features.append("波浪号营造亲切感")

        # ── 内容结构元素
        struct_els = []
        if re.search(r"[【📍⭐✅❌🔥💡⏰💰①②③④⑤]", all_text):
            struct_els.append("分节符号标题")
        if re.search(r"[①②③④⑤1-9][\.、．]", all_text):
            struct_els.append("数字有序列表")
        if re.search(r"[→➡️]", all_text):
            struct_els.append("箭头引导")
        if re.search(r"【[^】]+】", all_text):
            struct_els.append("【方括号】段落标题")

        # ── 互动引导
        engage_words = ["评论", "留言", "私信", "关注", "收藏", "点赞", "快去", "记得"]
        engage = [f"呼吁{w}" for w in engage_words if all_text.count(w) > 0]

        # ── 人设猜测
        persona = _guess_persona(casual_cnt, formal_cnt, account_data)

        return {
            "mode": "rule_based",
            "account_name": account_data.get("name", "未知账号"),
            "account_summary": f"分析了 {len(posts)} 篇笔记，平均 {int(avg_words)} 字/篇",
            "persona": persona,
            "tone": tone,
            "formality": formality,
            "emoji_frequency": emoji_freq,
            "common_emojis": [e for e, _ in emoji_counter.most_common(10) if e.strip()],
            "avg_word_count": int(avg_words),
            "hashtag_count": int(avg_tags),
            "opening_patterns": openings[:3],
            "closing_patterns": closings[:3],
            "topics": list(dict.fromkeys(all_tags))[:10],
            "engagement_tactics": engage[:5] or ["评论区互动引导"],
            "writing_features": features[:5] or ["自然流畅的叙述风格"],
            "content_structure": "、".join(struct_els) if struct_els else "自由散文结构",
            "sentence_stats": {
                "感叹号": exclamation,
                "问号": question,
                "波浪号": tilde,
                "句号": period,
            },
        }

    # ── LLM-based ─────────────────────────────────────────────
    def _analyze_with_llm(self, account_data: Dict, posts: List[Dict], api_key: str,
                          base_url: Optional[str] = None, model: Optional[str] = None) -> Dict:
        try:
            from openai import OpenAI
        except ImportError:
            return {**self._analyze_rule_based(account_data, posts), "error": "openai 包未安装"}

        eff_url = base_url or self.base_url
        eff_model = model or self.model
        print(f"[StyleAnalyzer] LLM | base_url={eff_url} | model={eff_model}")
        client = OpenAI(api_key=api_key, base_url=eff_url)

        posts_text = ""
        for i, p in enumerate(posts[:5], 1):
            posts_text += (
                f"\n\n【笔记{i}】标题：{p.get('title', '')}\n"
                f"{p.get('content', '')}\n"
                f"点赞：{p.get('likes', 0)} | 标签：{', '.join(p.get('tags', []))}"
            )

        prompt = f"""你是一位专业的小红书账号风格分析师。请深度分析以下账号的笔记风格，提取完整的风格画像。

账号名：{account_data.get('name', '未知')}
简介：{account_data.get('bio', '')}
{posts_text}

请以 JSON 格式返回分析结果，字段如下（所有字段必须有值）：
- account_summary: 账号整体定位（一句话描述）
- persona: 账号人设（如：邻家探店小姐姐、专业职场老司机）
- target_audience: 目标受众描述
- tone: 语气特点（详细描述，50字左右）
- formality: 正式程度（从以下选择：非常随意 / 较随意 / 适中 / 较正式 / 非常正式）
- emoji_frequency: emoji 使用频率及规律描述
- common_emojis: 常用 emoji 列表（5-10个）
- avg_word_count: 估计平均字数（数字）
- hashtag_count: 估计平均标签数（数字）
- hashtag_style: 标签风格描述（如：地域+品类组合，热门词+垂直词搭配）
- opening_patterns: 开头惯用句式，列举3个典型例子（数组）
- closing_patterns: 结尾惯用句式，列举3个典型例子（数组）
- content_structure: 内容结构模板（如：场景引入→详情介绍→体验感受→互动引导）
- topics: 主要内容话题列表（8-10个）
- engagement_tactics: 互动引导策略，3-5条（数组）
- writing_features: 写作风格特点，4-6条具体特征（数组）
- unique_style_elements: 让这个账号区别于他人的独特风格标识（2-3条）
- replication_guide: 模仿该风格的关键要点，3-5条具体建议（数组）

只返回 JSON，不要有多余文字。"""

        try:
            create_kwargs = dict(
                model=eff_model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是专业的小红书内容分析师，擅长提取账号风格特征。只返回 JSON 格式结果。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            # response_format=json_object 并非所有平台支持，先尝试加上
            try:
                resp = client.chat.completions.create(
                    **create_kwargs, response_format={"type": "json_object"}
                )
            except Exception:
                resp = client.chat.completions.create(**create_kwargs)
            result = json.loads(resp.choices[0].message.content)
            result["mode"] = "llm"
            result["account_name"] = account_data.get("name", "未知账号")
            return result

        except Exception as exc:
            print(f"[StyleAnalyzer] LLM failed: {exc}. Falling back to rule-based.")
            result = self._analyze_rule_based(account_data, posts)
            result["error"] = str(exc)
            return result


# ── Helpers ───────────────────────────────────────────────────

def _guess_persona(casual_cnt: int, formal_cnt: int, account_data: Dict) -> str:
    name = account_data.get("name", "") + account_data.get("bio", "")
    if any(k in name for k in ["职场", "干货", "老司机", "Leo", "coach", "导师"]):
        return "专业知识分享者"
    if any(k in name for k in ["吃货", "探店", "美食", "食"]):
        return "生活化探店博主"
    if any(k in name for k in ["旅行", "旅游", "游记", "环球"]):
        return "旅行内容创作者"
    if any(k in name for k in ["穿搭", "时尚", "搭配", "Mia", "fashion"]):
        return "时尚穿搭达人"
    if casual_cnt > formal_cnt:
        return "亲切生活化博主"
    return "专业领域创作者"
