"""Security regression tests for legacy chart execution defaults."""

from typing import List

import pandas as pd

from vanna.legacy.base.base import VannaBase


class LegacyTestVanna(VannaBase):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.run_sql_is_set = True
        self.run_sql = lambda sql: pd.DataFrame([{"value": 1}])

    def generate_embedding(self, data: str, **kwargs) -> List[float]:
        return [0.0]

    def get_similar_question_sql(self, question: str, **kwargs) -> list:
        return []

    def get_related_ddl(self, question: str, **kwargs) -> list:
        return []

    def get_related_documentation(self, question: str, **kwargs) -> list:
        return []

    def add_question_sql(self, question: str, sql: str, **kwargs) -> str:
        return "id"

    def add_ddl(self, ddl: str, **kwargs) -> str:
        return "id"

    def add_documentation(self, documentation: str, **kwargs) -> str:
        return "id"

    def get_training_data(self, **kwargs) -> pd.DataFrame:
        return pd.DataFrame()

    def remove_training_data(self, id: str, **kwargs) -> bool:
        return True

    def system_message(self, message: str) -> any:
        return {"role": "system", "content": message}

    def user_message(self, message: str) -> any:
        return {"role": "user", "content": message}

    def assistant_message(self, message: str) -> any:
        return {"role": "assistant", "content": message}

    def submit_prompt(self, prompt, **kwargs) -> str:
        return "fig = px.bar(df, x='value', y='value')"

    def generate_sql(self, question: str, allow_llm_to_see_data=False, **kwargs) -> str:
        return "SELECT 1 AS value"


def test_legacy_ask_skips_llm_python_chart_execution_by_default():
    vn = LegacyTestVanna(config={})
    sql, df, fig = vn.ask(question="test", print_results=False, visualize=True)
    assert sql is not None
    assert df is not None
    assert fig is None
