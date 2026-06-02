import re
from abc import ABC, abstractmethod
from pathlib import Path
import pandas as pd

class BaseAdapter(ABC):
    def __init__(self, workflow_dir: Path, params: dict):
        self.workflow_dir = workflow_dir
        self.params = params

    @abstractmethod
    def can_parse(self, df: pd.DataFrame) -> bool:
        """Determine if this adapter can parse the given DataFrame."""
        pass

    @abstractmethod
    def parse(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse the DataFrame into a standardized format."""
        pass