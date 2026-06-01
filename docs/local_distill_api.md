# 本地蒸馏工作流接入说明

本分支不接 TikHub，也不依赖第三方数据 API。所有能力都基于当前项目已经采集到的 `account_data.posts`。

## 已新增模块

```text
src/asset_builder.py          # StyleAnalyzer 输出 -> 标准蒸馏资产
src/skill_exporter.py         # 蒸馏资产 -> SKILL.md / report.html
src/local_distill_service.py  # 一站式工作流：分析、建资产、导出、生成候选、评分优选
```

## 最小使用方式

```python
from src.local_distill_service import LocalDistillService

service = LocalDistillService()
result = service.distill_account(
    account_data=account_data,
    api_key=api_key,
    base_url=base_url,
    model=model,
    persist=True,
)

asset = result["asset"]
skill_md = result["skill_md"]
report_html = result["report_html"]
files = result.get("files")
```

## 生成并评分优选

```python
ranked = service.generate_ranked(
    asset=asset,
    topic="熬夜后怎么调理",
    candidate_count=3,
    api_key=api_key,
    base_url=base_url,
    model=model,
)

best_note = ranked["best"]["note"]
best_score = ranked["best"]["evaluation"]
```

## 建议加入 app.py 的接口

在 `app.py` 顶部加入：

```python
from src.local_distill_service import LocalDistillService

distill_service = LocalDistillService()
```

增加本地蒸馏接口：

```python
@app.route("/api/distill/local", methods=["POST"])
def api_distill_local():
    data = request.get_json(force=True)
    account_data = data.get("account_data")
    visual_profile = data.get("visual_profile") or {}
    persist = bool(data.get("persist", False))
    api_key, base_url, model = _resolve_llm(data)

    if not account_data or not account_data.get("posts"):
        return jsonify({"error": "请先获取账号数据"}), 400

    try:
        result = distill_service.distill_account(
            account_data=account_data,
            visual_profile=visual_profile,
            api_key=api_key,
            base_url=base_url,
            model=model,
            persist=persist,
        )
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
```

增加基于蒸馏资产的生成优选接口：

```python
@app.route("/api/distill/generate_ranked", methods=["POST"])
def api_distill_generate_ranked():
    data = request.get_json(force=True)
    asset = data.get("asset")
    topic = data.get("topic", "").strip()
    candidate_count = int(data.get("candidate_count", 3))
    api_key, base_url, model = _resolve_llm(data)

    if not asset:
        return jsonify({"error": "缺少蒸馏资产 asset"}), 400
    if not topic:
        return jsonify({"error": "请输入要写的话题"}), 400

    try:
        result = distill_service.generate_ranked(
            asset=asset,
            topic=topic,
            candidate_count=candidate_count,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
```

## 产出物

当 `persist=True` 时，会写入：

```text
data/distilled/{账号名}/asset.json
数据/distilled/{账号名}/SKILL.md
数据/distilled/{账号名}/report.html
```

其中：

- `asset.json`：机器可读资产，后续生成/评分/改写使用。
- `SKILL.md`：给 AI 助手读取的创作指南。
- `report.html`：给人看的账号蒸馏报告。

## 推荐前端流程

```text
获取账号数据
  ↓
/api/analyze 生成基础画像
  ↓
/api/distill/local 生成 asset + SKILL + report
  ↓
用户输入新主题
  ↓
/api/distill/generate_ranked 生成 3-5 篇候选并评分
  ↓
展示 best.note + best.evaluation
```
