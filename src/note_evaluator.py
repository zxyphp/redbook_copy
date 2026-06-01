"""
小红书笔记质量评分模块

目标：
  1. 给生成结果做可解释评分，避免只生成不筛选。
  2. 支持无 API Key 的规则评分，也支持 LLM 深度评审。
  3. 输出固定 JSON，便于前端展示、后续数据落盘、DPO/偏好样本构造。
"""

import json
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


RISK_WORDS = [
    "根治", "治愈", "包治", "保证有效", "立刻见效", "百分百", "100%有效",
    "排毒", "清除毒素", "逆转疾病", "替代药物", "不用看医生",
]

HOOK_WORDS = [
    "别", "不要", "一定", "千万", "原来", "终于", "建议收藏", "收藏",
    "避坑", "误区", "后悔", "真相", "普通人", "新手", "打工人",
]

USEFULNESS_WORDS = [
    "步骤", "方法", "建议", "清单", "攻略", "避坑", "注意", "适合", "不适合",
    "原因", "做法", "模板", "公式", "总结", "重点", "建议收藏",
]

STRUCTURE_MARKERS = ["1.", "2.", "3.", "①", "②", "③", "✅", "❌", "👉", "→", "【", "##"]


class NoteEvaluator:
    def __init__(self):
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def evaluate(
        self,
        note: Dict,
        topic: str = "",
        style_profile: Optional[Dict] = None,
        reference_posts: Optional[List[Dict]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict:
        """返回笔记评分。api_key 存在时优先 LLM 评审，失败则回退规则评分。"""
        style_profile = style_profile or {}
        reference_posts = reference_posts or []

        if api_key:
            result = self._evaluate_with_llm(
                note=note,
                topic=topic,
                style_profile=style_profile,
                reference_posts=reference_posts,
                api_key=api_key,
                base_url=base_url or self.base_url,
                model=model or self.model,
            )
            if result:
                return result

        return self._evaluate_rule_based(note, topic, style_profile, reference_posts)

    def _evaluate_rule_based(
        self,
        note: Dict,
        topic: str,
        style_profile: Dict,
        reference_posts: List[Dict],
    ) -> Dict:
        title = str(note.get("title", "")).strip()
        content = str(note.get("content", "")).strip()
        tags = note.get("tags", []) or []
        full_text = f"{title}\n{content}"

        scores = {
            "topic_relevance": self._score_topic_relevance(full_text, topic, tags),
            "title_hook": self._score_title_hook(title),
            "xiaohongshu_style": self._score_xhs_style(title, content, tags, style_profile),
            "usefulness": self._score_usefulness(content),
            "originality": self._score_originality(full_text, reference_posts),
            "trustworthiness": self._score_trustworthiness(content),
            "compliance_risk": self._score_compliance_risk(full_text),
            "ai_flavor": self._score_ai_flavor(content),
        }

        # compliance_risk / ai_flavor 越低越好，overall 做反向扣分。
        overall = (
            scores["topic_relevance"] * 0.18
            + scores["title_hook"] * 0.16
            + scores["xiaohongshu_style"] * 0.16
            + scores["usefulness"] * 0.18
            + scores["originality"] * 0.14
            + scores["trustworthiness"] * 0.10
            + (10 - scores["compliance_risk"]) * 0.05
            + (10 - scores["ai_flavor"]) * 0.03
        )

        problems, revision_plan = self._build_suggestions(scores, title, content, tags)

        return {
            "mode": "rule_based",
            **scores,
            "overall": round(overall, 1),
            "problems": problems,
            "revision_plan": revision_plan,
        }

    def _evaluate_with_llm(
        self,
        note: Dict,
        topic: str,
        style_profile: Dict,
        reference_posts: List[Dict],
        api_key: str,
        base_url: str,
        model: str,
    ) -> Optional[Dict]:
        try:
            from openai import OpenAI
        except ImportError:
            return None

        ref_text = ""
        for i, p in enumerate(reference_posts[:3], 1):
            ref_text += f"\n【参考笔记{i}】标题：{p.get('title', '')}\n{p.get('content', '')[:800]}\n"

        prompt = f"""你是小红书内容质检与增长评审专家。请评估下面这篇生成笔记。

# 主题
{topic or '未提供'}

# 风格画像
{json.dumps(style_profile, ensure_ascii=False)[:2500]}

# 参考笔记（只用于判断是否过度相似，不允许鼓励复制）
{ref_text}

# 待评估笔记
标题：{note.get('title', '')}
正文：
{note.get('content', '')}
标签：{note.get('tags', [])}

请只返回合法 JSON，不要 markdown。字段固定如下：
{{
  "topic_relevance": 1-10,
  "title_hook": 1-10,
  "xiaohongshu_style": 1-10,
  "usefulness": 1-10,
  "originality": 1-10,
  "trustworthiness": 1-10,
  "compliance_risk": 1-10,
  "ai_flavor": 1-10,
  "overall": 1-10,
  "problems": ["问题1", "问题2"],
  "revision_plan": ["修改建议1", "修改建议2"]
}}

评分标准：compliance_risk 和 ai_flavor 是风险分，越高越差；其他分数越高越好。重点判断是否空泛、是否像 AI 模板、是否复制参考笔记、是否有违规医疗/夸大表达。"""

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是严格的小红书内容评审专家，只返回 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            result["mode"] = "llm"
            return result
        except Exception as exc:
            print(f"[NoteEvaluator] LLM failed: {exc}. Falling back to rule-based.")
            return None

    @staticmethod
    def _score_topic_relevance(text: str, topic: str, tags: List[str]) -> int:
        if not topic:
            return 7
        topic_words = [w for w in re.split(r"[\s,，、/|]+", topic) if len(w) >= 2]
        if not topic_words:
            topic_words = [topic]
        hit = sum(1 for w in topic_words if w in text or w in " ".join(tags))
        return min(10, max(3, 5 + hit * 2))

    @staticmethod
    def _score_title_hook(title: str) -> int:
        if not title:
            return 1
        score = 4
        if 8 <= len(title) <= 32:
            score += 2
        if any(w in title for w in HOOK_WORDS):
            score += 2
        if re.search(r"\d|[①②③④⑤]", title):
            score += 1
        if any(ch in title for ch in "！？!?"):
            score += 1
        return min(10, score)

    @staticmethod
    def _score_xhs_style(title: str, content: str, tags: List[str], style_profile: Dict) -> int:
        score = 4
        if tags and 3 <= len(tags) <= 10:
            score += 2
        if any(m in content for m in STRUCTURE_MARKERS):
            score += 2
        common_emojis = style_profile.get("common_emojis", []) or []
        if common_emojis and any(e in f"{title}{content}" for e in common_emojis):
            score += 1
        if len(content.splitlines()) >= 4:
            score += 1
        return min(10, score)

    @staticmethod
    def _score_usefulness(content: str) -> int:
        score = 3
        score += min(3, sum(1 for w in USEFULNESS_WORDS if w in content))
        if len(content) >= 300:
            score += 2
        elif len(content) >= 150:
            score += 1
        if re.search(r"(第一|第二|第三|1\.|2\.|3\.|①|②|③|✅)", content):
            score += 2
        return min(10, score)

    @staticmethod
    def _score_originality(text: str, reference_posts: List[Dict]) -> int:
        if not reference_posts:
            return 8
        worst = 0.0
        for p in reference_posts[:5]:
            ref = f"{p.get('title', '')}\n{p.get('content', '')}"[:2000]
            if not ref.strip():
                continue
            worst = max(worst, SequenceMatcher(None, text[:2000], ref).ratio())
        if worst > 0.55:
            return 3
        if worst > 0.38:
            return 5
        if worst > 0.25:
            return 7
        return 9

    @staticmethod
    def _score_trustworthiness(content: str) -> int:
        score = 5
        if any(w in content for w in ["可能", "建议", "因人而异", "注意", "不适合", "参考"]):
            score += 2
        if any(w in content for w in ["亲测", "数据", "经验", "案例", "原因"]):
            score += 1
        if any(w in content for w in ["保证", "一定有效", "立刻"]):
            score -= 2
        return min(10, max(1, score))

    @staticmethod
    def _score_compliance_risk(text: str) -> int:
        hits = [w for w in RISK_WORDS if w in text]
        return min(10, len(hits) * 2)

    @staticmethod
    def _score_ai_flavor(content: str) -> int:
        vague_patterns = [
            "独特之处", "值得深入了解", "收获超过预期", "非常推荐的是",
            "核心亮点", "实用信息", "名不虚传", "完全值得花时间",
        ]
        score = min(8, sum(2 for p in vague_patterns if p in content))
        if len(set(re.findall(r"[\u4e00-\u9fa5]{2,}", content))) < 20 and len(content) > 120:
            score += 2
        return min(10, score)

    @staticmethod
    def _build_suggestions(scores: Dict[str, int], title: str, content: str, tags: List[str]) -> Tuple[List[str], List[str]]:
        problems: List[str] = []
        plans: List[str] = []

        if scores["title_hook"] < 7:
            problems.append("标题钩子不足，缺少明确人群、冲突点或收益点")
            plans.append("标题加入具体场景、数字或反常识表达，例如“别急着X，先做这3步”")
        if scores["usefulness"] < 7:
            problems.append("正文实用信息偏少，容易显得空泛")
            plans.append("补充可执行步骤、避坑提醒、适用/不适用人群")
        if scores["originality"] < 7:
            problems.append("与参考笔记相似度偏高，有洗稿风险")
            plans.append("保留结构，替换案例、措辞、场景和表达顺序")
        if scores["compliance_risk"] >= 4:
            problems.append("存在夸大或高风险表达")
            plans.append("删除绝对化、医疗化、承诺疗效类词汇")
        if scores["ai_flavor"] >= 5:
            problems.append("AI 模板味偏重，缺少具体细节")
            plans.append("加入真实场景、具体对象、限制条件和自然口语表达")
        if not tags or len(tags) < 3:
            problems.append("标签数量偏少，不利于内容分发")
            plans.append("补充大词、垂类词、场景词组合的 5-8 个标签")

        return problems[:5], plans[:5]
