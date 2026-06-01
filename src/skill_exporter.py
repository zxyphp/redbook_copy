"""
Export local distillation assets to SKILL.md and HTML report.

No external data source is used here. The exporter only consumes the asset built
from the current project's collected notes and style analysis output.
"""

import html
from typing import Any, Dict, Iterable, List


def _lines(items: Iterable[Any], prefix: str = "- ") -> str:
    result: List[str] = []
    for item in items or []:
        if isinstance(item, dict):
            text = item.get("name") or item.get("pattern") or str(item)
        else:
            text = str(item)
        if text:
            result.append(f"{prefix}{text}")
    return "\n".join(result) if result else f"{prefix}暂无"


def export_skill_md(asset: Dict[str, Any]) -> str:
    account = asset.get("account", {})
    voice = asset.get("voice", {})
    title_formulas = asset.get("title_formulas", [])
    content_formulas = asset.get("content_formulas", [])

    title_blocks = []
    for formula in title_formulas:
        examples = formula.get("examples", []) or []
        title_blocks.append(
            f"### {formula.get('name', '标题公式')}\n"
            f"- 公式：{formula.get('pattern', '')}\n"
            f"- 示例：{'; '.join(examples[:3]) if examples else '暂无'}"
        )

    content_blocks = []
    for formula in content_formulas:
        steps = formula.get("steps", []) or []
        content_blocks.append(
            f"### {formula.get('name', '内容结构')}\n"
            f"{_lines(steps)}"
        )

    return f"""# {account.get('name', '账号')} 创作指南

> 本 Skill 由 redbook_copy 基于本地采集笔记和风格分析结果生成。它用于学习结构、节奏和表达规律，不用于复制原文。

## 使用方式

当用户要求按照该账号风格创作时，先读取本指南，再生成原创内容。必须遵守创作禁区。

## 一、账号定位

- 账号名称：{account.get('name', '未知账号')}
- 账号摘要：{account.get('summary', '')}
- 人设：{account.get('persona', '')}
- 目标受众：{account.get('target_audience', '')}

## 二、表达风格

- 语气：{voice.get('tone', '')}
- 正式程度：{voice.get('formality', '')}
- Emoji 使用：{voice.get('emoji_frequency', '')}
- 常用 Emoji：{' '.join(voice.get('common_emojis', []) or [])}

## 三、核心话题

{_lines(asset.get('topics', []))}

## 四、标题公式

{chr(10).join(title_blocks) if title_blocks else '- 暂无'}

## 五、开头方式

{_lines(asset.get('opening_patterns', []))}

## 六、内容结构

{chr(10).join(content_blocks) if content_blocks else '- 暂无'}

## 七、结尾与互动

{_lines(asset.get('engagement_tactics', []))}

## 八、写作特征

{_lines(asset.get('writing_features', []))}

## 九、创作禁区

{_lines(asset.get('guardrails', []))}

## 十、生成检查清单

- 是否围绕新主题原创展开？
- 是否只学习结构和节奏，而不是复制原文？
- 标题是否有明确人群、场景、痛点或收益点？
- 正文是否有具体信息，而不是空泛模板？
- 是否避免绝对化和高风险表达？
""".strip()


def export_report_html(asset: Dict[str, Any]) -> str:
    account = asset.get("account", {})
    voice = asset.get("voice", {})

    def li(items):
        return "".join(f"<li>{html.escape(str(x))}</li>" for x in (items or [])) or "<li>暂无</li>"

    def formula_cards(items):
        cards = []
        for item in items or []:
            name = html.escape(str(item.get("name", "未命名")))
            pattern = html.escape(str(item.get("pattern", "")))
            examples = item.get("examples", []) or []
            cards.append(
                f"<div class='card'><h3>{name}</h3><p>{pattern}</p><small>{html.escape(' / '.join(examples[:3]))}</small></div>"
            )
        return "".join(cards) or "<p>暂无</p>"

    evidence = asset.get("evidence_notes", []) or []
    evidence_rows = "".join(
        f"<tr><td>{idx+1}</td><td>{html.escape(str(n.get('title', '')))}</td>"
        f"<td>{html.escape(str(n.get('likes', 0)))}</td><td>{html.escape(str(n.get('comments', 0)))}</td></tr>"
        for idx, n in enumerate(evidence[:10])
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{html.escape(account.get('name', '账号'))} 蒸馏报告</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f6f7f9; color:#202124; margin:0; }}
.container {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px; }}
.hero {{ background: linear-gradient(135deg, #111827, #374151); color:white; padding:32px; border-radius:24px; }}
.grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:16px; margin-top:20px; }}
.card, section {{ background:white; border-radius:18px; padding:20px; box-shadow:0 8px 24px rgba(0,0,0,.06); }}
section {{ margin-top:20px; }}
h1,h2,h3 {{ margin-top:0; }}
ul {{ padding-left:20px; }}
table {{ width:100%; border-collapse: collapse; }}
th,td {{ text-align:left; border-bottom:1px solid #eee; padding:10px; }}
.badge {{ display:inline-block; background:#eef2ff; padding:6px 10px; border-radius:999px; margin:4px; }}
</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <h1>{html.escape(account.get('name', '账号'))} 蒸馏报告</h1>
    <p>{html.escape(account.get('summary', ''))}</p>
    <p>人设：{html.escape(account.get('persona', ''))}</p>
  </div>

  <div class="grid">
    <div class="card"><h3>语气</h3><p>{html.escape(voice.get('tone', ''))}</p></div>
    <div class="card"><h3>正式程度</h3><p>{html.escape(voice.get('formality', ''))}</p></div>
    <div class="card"><h3>Emoji</h3><p>{html.escape(' '.join(voice.get('common_emojis', []) or []))}</p></div>
  </div>

  <section><h2>核心话题</h2>{''.join(f"<span class='badge'>{html.escape(str(t))}</span>" for t in asset.get('topics', []))}</section>
  <section><h2>标题公式</h2><div class="grid">{formula_cards(asset.get('title_formulas', []))}</div></section>
  <section><h2>开头方式</h2><ul>{li(asset.get('opening_patterns', []))}</ul></section>
  <section><h2>内容结构</h2><ul>{li([f.get('name', '') + '：' + ' → '.join(f.get('steps', [])) for f in asset.get('content_formulas', [])])}</ul></section>
  <section><h2>互动策略</h2><ul>{li(asset.get('engagement_tactics', []))}</ul></section>
  <section><h2>创作禁区</h2><ul>{li(asset.get('guardrails', []))}</ul></section>
  <section><h2>证据笔记</h2><table><thead><tr><th>#</th><th>标题</th><th>赞</th><th>评</th></tr></thead><tbody>{evidence_rows}</tbody></table></section>
</div>
</body>
</html>"""
