from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base, make_engine
from app.db.seed import load_seeds

SEEDS_DIR = Path(__file__).resolve().parents[2] / "data" / "seeds"


def _make_session(tmp_path) -> Session:
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    return Session(eng)


def _counts(s: Session) -> tuple[int, int, int]:
    return (
        s.query(models.Topic).count(),
        s.query(models.Company).count(),
        s.query(models.TopicCompany).count(),
    )


def test_load_seeds_populates_expected_counts(tmp_path):
    with _make_session(tmp_path) as s:
        load_seeds(str(SEEDS_DIR), s)
        s.commit()
        topics, companies, topic_companies = _counts(s)
    # 1 題材、17 檔公司；topic_companies = 上游 9 + 中游 (6+1+4)=11 = 20 筆
    assert topics == 1
    assert companies == 17
    assert topic_companies == 20


def test_load_seeds_is_idempotent(tmp_path):
    with _make_session(tmp_path) as s:
        load_seeds(str(SEEDS_DIR), s)
        s.commit()
        first = _counts(s)
        # 再跑一次不得產生重複列
        load_seeds(str(SEEDS_DIR), s)
        s.commit()
        assert _counts(s) == first
        assert first == (1, 17, 20)


def test_load_seeds_updates_changed_title(tmp_path, monkeypatch):
    with _make_session(tmp_path) as s:
        load_seeds(str(SEEDS_DIR), s)
        s.commit()
        assert s.get(models.Topic, "silicon-photonics").title == "光通訊｜矽光子與 CPO"

        # 以修改過 title 的 YAML 重跑，應更新既有題材而非新增
        raw = yaml.safe_load((SEEDS_DIR / "silicon-photonics.yaml").read_text())
        raw["title"] = "光通訊｜矽光子與 CPO（更新）"
        alt = tmp_path / "seeds"
        alt.mkdir()
        (alt / "silicon-photonics.yaml").write_text(
            yaml.safe_dump(raw, allow_unicode=True)
        )

        load_seeds(str(alt), s)
        s.commit()
        assert s.query(models.Topic).count() == 1
        assert (
            s.get(models.Topic, "silicon-photonics").title
            == "光通訊｜矽光子與 CPO（更新）"
        )


def test_load_seeds_stores_placeholder_categories_in_chain_meta(tmp_path):
    with _make_session(tmp_path) as s:
        load_seeds(str(SEEDS_DIR), s)
        s.commit()
        topic = s.get(models.Topic, "silicon-photonics")
        # placeholder 分類（無公司）僅存在於 chain_meta 骨架，不進 topic_companies
        names = {
            c["name"]
            for level in topic.chain_meta
            for c in level["categories"]
        }
        assert "CPO 整合交換器系統" in names
        assert "AI 算力單元與高效能運算" in names
        placeholder_names = {
            c["name"]
            for level in topic.chain_meta
            for c in level["categories"]
            if c.get("placeholder")
        }
        assert placeholder_names == {"CPO 整合交換器系統", "AI 算力單元與高效能運算"}


def test_load_seeds_is_upsert_only_no_deletion(tmp_path):
    """Known limitation：upsert-only——從 YAML 移除的公司不會從 DB 刪除。

    這是刻意記錄的預期行為（見 seed.py 模組 docstring）；完全重建需
    刪除 DB 後重跑 seed。
    """
    with _make_session(tmp_path) as s:
        load_seeds(str(SEEDS_DIR), s)
        s.commit()
        assert s.get(models.Company, "3289") is not None

        # 從 YAML 移除 3289（公司主檔＋chain 內的歸屬）後重跑
        raw = yaml.safe_load((SEEDS_DIR / "silicon-photonics.yaml").read_text())
        raw["companies"] = [
            c for c in raw["companies"] if str(c["ticker"]) != "3289"
        ]
        for level in raw["chain"]:
            for cat in level["categories"]:
                if "companies" in cat:
                    cat["companies"] = [
                        c for c in cat["companies"] if str(c["ticker"]) != "3289"
                    ]
        alt = tmp_path / "seeds"
        alt.mkdir()
        (alt / "silicon-photonics.yaml").write_text(
            yaml.safe_dump(raw, allow_unicode=True)
        )

        load_seeds(str(alt), s)
        s.commit()
        # 舊列仍在——upsert-only 不做刪除同步，此為預期行為
        assert s.get(models.Company, "3289") is not None
        assert (
            s.query(models.TopicCompany).filter_by(ticker="3289").count() == 1
        )
        assert _counts(s) == (1, 17, 20)


def test_load_seeds_bad_yaml_error_includes_filename(tmp_path):
    bad_dir = tmp_path / "seeds"
    bad_dir.mkdir()
    bad_file = bad_dir / "broken.yaml"
    bad_file.write_text("slug: [unclosed\n  nope: :::")

    with _make_session(tmp_path) as s:
        with pytest.raises(ValueError, match="seed 檔解析失敗") as excinfo:
            load_seeds(str(bad_dir), s)
        assert str(bad_file) in str(excinfo.value)


def test_load_seeds_returns_imported_file_count(tmp_path):
    empty = tmp_path / "empty-seeds"
    empty.mkdir()
    with _make_session(tmp_path) as s:
        assert load_seeds(str(empty), s) == 0
        assert load_seeds(str(SEEDS_DIR), s) == 1
