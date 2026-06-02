from pathlib import Path
import pandas as pd
from openms_insight.analysis.parsers.tmt_adapter import TMTAdapter
from openms_insight.analysis.parsers.lfq_adapter import LFQAdapter

class ExpressionDataParser:
    def __init__(self, workspace_path: str | Path, params: dict):
        self.workflow_dir = Path(workspace_path)
        self.params = params
        self.adapters = [
            TMTAdapter(self.workflow_dir, self.params),
            LFQAdapter(self.workflow_dir, self.params),
        ]

    def parse(self, file_path: str | Path) -> tuple[pd.DataFrame, dict] | None:
        try:
            df = pd.read_csv(file_path, sep=None, comment="#", engine="python")
        except Exception:
            return None

        if df.empty:
            return None

        for adapter in self.adapters:
            if adapter.can_parse(df):
                return adapter.parse(df)

        raise ValueError("❌ 지원하지 않는 포맷입니다.")