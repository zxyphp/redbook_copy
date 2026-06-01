"""
Local distillation workflow service.

This service keeps the current project approach:
  - use already collected account_data/posts
  - use existing StyleAnalyzer / ContentGenerator / NoteEvaluator
  - no TikHub or external data provider
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.asset_builder import asset_to_style_profile, build_asset, dumps_asset
from src.content_generator import ContentGenerator
from src.note_evaluator import NoteEvaluator
from src.skill_exporter import export_report_html, export_skill_md
from src.style_analyzer import StyleAnalyzer


class LocalDistillService:
    def __init__(self, output_dir: str = "data/distilled"):
        self.output_dir = Path(output_dir)
        self.analyzer = StyleAnalyzer()
        self.generator = ContentGenerator()
        self.evaluator = NoteEvaluator()

    def distill_account(
        self,
        account_data: Dict[str, Any],
        visual_profile: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        persist: bool = False,
    ) -> Dict[str, Any]:
        posts = account_data.get("posts", []) or []
        if not posts:
            raise ValueError("account_data.posts 不能为空")

        profile = self.analyzer.analyze(account_data, api_key=api_key, base_url=base_url, model=model)
        asset = build_asset(profile, posts=posts, visual=visual_profile or {})
        skill_md = export_skill_md(asset)
        report_html = export_report_html(asset)

        result = {
            "profile": profile,
            "asset": asset,
            "skill_md": skill_md,
            "report_html": report_html,
        }

        if persist:
            result["files"] = self.persist_asset(asset, skill_md, report_html)

        return result

    def generate_ranked(
        self,
        asset: Dict[str, Any],
        topic: str,
        sample_posts: Optional[List[Dict[str, Any]]] = None,
        candidate_count: int = 3,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        sample_posts = sample_posts or asset.get("evidence_notes", []) or []
        candidate_count = max(1, min(int(candidate_count or 3), 5))
        profile = asset_to_style_profile(asset)

        candidates = []
        for idx in range(candidate_count):
            note = self.generator.generate(profile, topic, sample_posts, api_key=api_key, base_url=base_url, model=model)
            evaluation = self.evaluator.evaluate(
                note=note,
                topic=topic,
                style_profile=profile,
                reference_posts=sample_posts,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            candidates.append({"index": idx + 1, "note": note, "evaluation": evaluation})

        best = max(candidates, key=lambda item: item["evaluation"].get("overall", 0))
        return {"best": best, "candidates": candidates}

    def persist_asset(self, asset: Dict[str, Any], skill_md: str, report_html: str) -> Dict[str, str]:
        safe_name = self._safe_name(asset.get("account", {}).get("name") or "unknown")
        target = self.output_dir / safe_name
        target.mkdir(parents=True, exist_ok=True)

        asset_path = target / "asset.json"
        skill_path = target / "SKILL.md"
        report_path = target / "report.html"

        asset_path.write_text(dumps_asset(asset), encoding="utf-8")
        skill_path.write_text(skill_md, encoding="utf-8")
        report_path.write_text(report_html, encoding="utf-8")

        return {
            "asset_json": str(asset_path),
            "skill_md": str(skill_path),
            "report_html": str(report_path),
        }

    @staticmethod
    def load_asset(path: str) -> Dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:80] or "unknown"
