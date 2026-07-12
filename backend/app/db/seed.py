"""YAML seed 匯入：讀取 seeds 目錄下所有 *.yaml，冪等 upsert 至 DB。

真理來源是 `data/seeds/*.yaml`。每次 `load_seeds` 都以主鍵查存在→更新、否則新增，
因此可安全重跑（idempotent）。匯入順序遵守 FK：先 companies / topics，再 topic_companies。

**Known limitation（upsert-only）**：本匯入僅 insert/update，不做刪除同步——
從 YAML 移除的公司、分類或題材不會從 DB 移除。若需完全重建，請先刪除 DB 檔
再重跑 seed。
"""

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.db import models


def _upsert_topic(s: Session, doc: dict) -> None:
    slug = doc["slug"]
    # 只保留分類骨架（level → categories 的 name/desc/placeholder 與排序），
    # 公司歸屬另存 topic_companies；placeholder 分類無公司，只能靠此骨架保留。
    chain_meta = [
        {
            "level": level["level"],
            "categories": [
                {
                    "name": cat["name"],
                    "desc": cat.get("desc"),
                    "placeholder": bool(cat.get("placeholder", False)),
                }
                for cat in level.get("categories", [])
            ],
        }
        for level in doc.get("chain", [])
    ]

    topic = s.get(models.Topic, slug)
    if topic is None:
        topic = models.Topic(slug=slug)
        s.add(topic)
    topic.title = doc["title"]
    topic.description = doc.get("description")
    topic.market_tab = doc.get("market_tab", "tw")
    topic.metrics = doc.get("metrics")
    topic.verified_at = doc.get("verified_at")
    topic.chain_meta = chain_meta


def _upsert_company(s: Session, entry: dict) -> None:
    """部分更新（partial update）：只覆寫 entry 有提供的欄位，避免跨 seed 互相 clobber。

    同一公司常出現在多個 seed，且各 seed 未必都帶齊欄位。若某 seed 省略 ``has_futures``／
    ``name``，不得把另一 seed 已設好的值蓋掉——因此缺鍵時保留既有值。新公司則採預設
    （``has_futures=False``），並要求首次出現時必須帶 ``name``。
    """
    ticker = str(entry["ticker"])
    company = s.get(models.Company, ticker)
    is_new = company is None
    if is_new:
        company = models.Company(ticker=ticker, has_futures=False)
        s.add(company)

    # name：有值才更新（新公司必須有 name）。
    if "name" in entry:
        company.name = entry["name"]
    elif is_new:
        raise ValueError(f"新公司 {ticker} 缺少必要欄位 name")

    # market：預設 TW；新公司缺鍵時套預設，既有公司缺鍵時保留原值。
    if "market" in entry:
        company.market = entry["market"]
    elif is_new:
        company.market = "TW"

    # has_futures：缺鍵時不覆寫既有值（防跨 seed clobber）；新公司已預設 False。
    if "has_futures" in entry:
        company.has_futures = bool(entry["has_futures"])


def _upsert_topic_company(
    s: Session,
    topic_slug: str,
    chain_level: str,
    category_name: str,
    category_desc: str | None,
    entry: dict,
) -> None:
    ticker = str(entry["ticker"])
    key = (topic_slug, ticker, category_name)
    tc = s.get(models.TopicCompany, key)
    if tc is None:
        tc = models.TopicCompany(
            topic_slug=topic_slug, ticker=ticker, category=category_name
        )
        s.add(tc)
    tc.chain_level = chain_level
    tc.category_desc = category_desc
    tc.role = entry.get("role")
    tc.relevance = entry.get("relevance")


def load_seed_doc(doc: dict, s: Session) -> None:
    """匯入單一 YAML 文件的內容（不 commit，由呼叫端負責）。"""
    # 先 topics + companies（被 FK 參照的父表），flush 後再寫 topic_companies。
    _upsert_topic(s, doc)
    for entry in doc.get("companies", []):
        _upsert_company(s, entry)
    s.flush()

    for level in doc.get("chain", []):
        chain_level = level["level"]
        for cat in level.get("categories", []):
            for entry in cat.get("companies", []):
                _upsert_topic_company(
                    s,
                    topic_slug=doc["slug"],
                    chain_level=chain_level,
                    category_name=cat["name"],
                    category_desc=cat.get("desc"),
                    entry=entry,
                )
    s.flush()


def load_seeds(seeds_dir: str, s: Session) -> int:
    """讀取 ``seeds_dir`` 下所有 *.yaml，冪等 upsert 至資料庫（不 commit）。

    回傳實際匯入的檔案數（空目錄回傳 0）。upsert-only：不會刪除 DB 中
    已不存在於 YAML 的資料，詳見模組 docstring。
    """
    directory = Path(seeds_dir)
    imported = 0
    for path in sorted(directory.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            raise ValueError(f"seed 檔解析失敗: {path}: {exc}") from exc
        if doc:
            try:
                load_seed_doc(doc, s)
            except (KeyError, ValueError) as exc:
                # 內容錯誤（缺 ticker/name 等）一律帶檔名脈絡，與 YAML 解析錯誤一致。
                raise ValueError(f"seed 內容錯誤: {path}: {exc}") from exc
            imported += 1
    return imported
