"""命令列入口：`python -m cli seed|fetch|backfill`。"""

import sys
from functools import partial
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base, make_engine
from app.db.seed import load_seeds
from app.pipeline.jobs import fetch_tw_quotes
from app.pipeline.jobs_backfill import (
    backfill_institutional,
    backfill_market_stats,
    backfill_per,
    backfill_quotes,
)
from app.pipeline.runner import run_job


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法：python -m cli seed|fetch|backfill")
    cmd = sys.argv[1]

    # 確保 DB 檔的父目錄存在（首次執行時 backend/data/ 可能尚未建立）。
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)

    eng = make_engine(settings.db_path)
    Base.metadata.create_all(eng)

    if cmd == "seed":
        # seeds 路徑來自 config（以 __file__ 推導 repo root），不寫死相對路徑，
        # 從 backend/ 或 repo root 執行皆可正確定位。
        with Session(eng) as s:
            imported = load_seeds(settings.seeds_dir, s)
            s.commit()
        print(f"seed 完成：{imported} 檔（{settings.seeds_dir} → {settings.db_path}）")
    elif cmd == "fetch":
        # runner 擁有交易邊界並記錄 PipelineRun；失敗時回傳 status="failed"
        # （不 re-raise），由 CLI 依 status 決定結束碼。
        run = run_job(eng, "fetch_tw_quotes", fetch_tw_quotes)
        if run.status == "success":
            print(f"fetch 完成：status={run.status}（{settings.db_path}）")
        else:
            print(f"fetch 失敗：status={run.status}，error={run.error}")
            raise SystemExit(1)
    elif cmd == "backfill":
        # 依序回填歷史行情與法人資料；每個 job 各自透過 runner 記 PipelineRun。
        # partial 包住 days 參數以符合 run_job 的 fn(session) 契約。任一 job
        # failed → 印狀態後以 exit 1 收場（CI/Make 可據此判斷）。
        jobs = (
            # days 目標設高於 6 個月的交易日數（約 120），使 _collect_ticker_history
            # 不會提早 break，而是走滿 _MAX_MONTHS=6 個月上限——K 線圖需 ≥100 交易日。
            ("backfill_quotes", partial(backfill_quotes, days=130)),
            ("backfill_institutional", partial(backfill_institutional, days=14)),
            ("backfill_market_stats", partial(backfill_market_stats, days=30)),
            ("backfill_per", partial(backfill_per, months=3)),
        )
        failed = False
        for name, fn in jobs:
            run = run_job(eng, name, fn)
            print(f"{name}：status={run.status}", end="")
            print("" if run.status == "success" else f"，error={run.error}")
            failed = failed or run.status != "success"
        if failed:
            raise SystemExit(1)
        print(f"backfill 完成（{settings.db_path}）")
    else:
        raise SystemExit(f"未知指令：{cmd}")


if __name__ == "__main__":
    main()
