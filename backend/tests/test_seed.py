from pathlib import Path

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
