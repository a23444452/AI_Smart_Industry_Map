"""命令列入口：`python -m cli seed|fetch`。"""

import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base, make_engine
from app.db.seed import load_seeds
from app.pipeline.jobs import fetch_tw_quotes
from app.pipeline.runner import run_job


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法：python -m cli seed|fetch")
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
    else:
        raise SystemExit(f"未知指令：{cmd}")


if __name__ == "__main__":
    main()
