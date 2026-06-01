"""
Local distillation asset builder.

This module converts the existing StyleAnalyzer output into a reusable asset.
It does not call third-party data APIs. It only works with data already collected
by the current project.
"""

import json
from datetime import datetime
from typing import Any, Dict, List


def build_asset(profile: Dict[str, Any], posts: List[Dict[str, Any]] | None = None, visual: Dict[str, Any] | None = None) -> Dict[str, Any]:
    posts = posts or []
    visual = visual or {}
    title_examples = [p.get("title", "") for p in posts if p.get("title")][:8]
    opening_examples = profile.get("opening_patterns", []) or []
    closing_examples = profile.get("closing_patterns", []) or []

    return {
        "asset_version": "1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "account": {
            "name": profile.get("account_name", "未知账号"),
            "summary": profile.get("account_summary", ""),
            "persona": profile.get("persona", ""),
            "target_audience": profile.get("target_audience", ""),
        },
        "voice": {
            "tone": profile.get("tone", ""),
            "formality": profile.get("formality", ""),
            "emoji_frequency": profile.get("emoji_frequency", ""),
            "common_emojis": profile.get("common_emojis", []),
        },
        "topics": profile.get("topics", []) or [],
        "title_formulas": [
            {
                "name": "场景人群型",
                "pattern": "具体人群/场景 + 明确收益点 + 收藏理由",
                "examples": title_examples[:4],
            },
            {
                "name": "避坑提醒型",
                "pattern": "别急着做某事 + 先看关键判断/步骤",
                "examples": title_examples[4:8],
            },
        ],
        "opening_patterns": opening_examples,
        "closing_patterns": closing_examples,
        "content_formulas": [
            {
                "name": "问题-原因-做法-提醒",
                "steps": ["指出问题", "解释原因", "给出做法", "补充提醒"],
            },
            {
                "name": "场景-清单-总结-互动",
                "steps": ["场景引入", "清单拆解", "关键总结", "互动引导"],
            },
        ],
        "engagement_tactics": profile.get("engagement_tactics", []) or ["收藏备用", "评论区交流"],
        "writing_features": profile.get("writing_features", []) or [],
        "content_structure": profile.get("content_structure", ""),
        "visual_profile": visual,
        "guardrails": [
            "只学习结构、节奏和表达规律，不复制参考内容原句",
            "生成内容必须围绕新主题原创展开",
            "避免绝对化承诺和夸大表达",
            "涉及健康、医疗、养生类主题时保留适用边界",
        ],
        "evidence_notes": posts[:10],
        "raw_profile": profile,
    }


def asset_to_style_profile(asset: Dict[str, Any]) -> Dict[str, Any]:
    """Convert asset back to a profile that ContentGenerator can consume."""
    raw = dict(asset.get("raw_profile") or {})
    account = asset.get("account", {})
    voice = asset.get("voice", {})
    raw.update({
        "account_name": account.get("name"),
        "account_summary": account.get("summary"),
        "persona": account.get("persona"),
        "target_audience": account.get("target_audience"),
        "tone": voice.get("tone"),
        "formality": voice.get("formality"),
        "emoji_frequency": voice.get("emoji_frequency"),
        "common_emojis": voice.get("common_emojis", []),
        "topics": asset.get("topics", []),
        "title_formulas": asset.get("title_formulas", []),
        "content_formulas": asset.get("content_formulas", []),
        "engagement_tactics": asset.get("engagement_tactics", []),
        "forbidden_rules": asset.get("guardrails", []),
        "visual_profile": asset.get("visual_profile", {}),
    })
    return raw


def dumps_asset(asset: Dict[str, Any]) -> str:
    return json.dumps(asset, ensure_ascii=False, indent=2)
