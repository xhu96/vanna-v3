import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from vanna.personalization.presidio_redactor import PresidioRedactor

@pytest.fixture
def redactor():
    with patch("vanna.personalization.presidio_redactor.PRESIDIO_AVAILABLE", True):
        # We must explicitly set dummy classes if they weren't imported
        import vanna.personalization.presidio_redactor as pr
        if not hasattr(pr, 'AnalyzerEngine'):
            pr.AnalyzerEngine = MagicMock()
        if not hasattr(pr, 'AnonymizerEngine'):
            pr.AnonymizerEngine = MagicMock()
        return PresidioRedactor()

def test_presidio_redactor_initialization(redactor):
    assert "PERSON" in redactor.entities
    assert "CREDIT_CARD" in redactor.entities

def test_redact_dataframe(redactor):
    # Setup mocks
    mock_analyzer = MagicMock()
    # mock_analyzer_cls.return_value = mock_analyzer
    
    mock_anonymizer = MagicMock()
    # mock_anonymizer_cls.return_value = mock_anonymizer
    
    redactor.analyzer = mock_analyzer
    redactor.anonymizer = mock_anonymizer

    # Mock the analyze method to return True if 'secret' is in text
    def mock_analyze(text, *args, **kwargs):
        if "secret" in text.lower():
            return [MagicMock()] # Mock result
        return []
    
    mock_analyzer.analyze.side_effect = mock_analyze

    # Mock anonymize method
    def mock_anonymize(text, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.text = "<REDACTED>"
        return mock_result
        
    mock_anonymizer.anonymize.side_effect = mock_anonymize

    # Test Data
    df = pd.DataFrame({
        "id": [1, 2],
        "notes": ["This is safe", "This has a secret inside"],
        "amounts": [100.50, 200.75]
    })

    redacted_df = redactor.redact_dataframe(df)

    # numeric columns shouldn't change
    assert redacted_df.iloc[0]["id"] == 1
    assert redacted_df.iloc[1]["amounts"] == 200.75
    
    # string columns should be processed
    assert redacted_df.iloc[0]["notes"] == "This is safe"
    assert redacted_df.iloc[1]["notes"] == "<REDACTED>"

def test_redact_empty_dataframe(redactor):
    df = pd.DataFrame()
    redacted_df = redactor.redact_dataframe(df)
    assert redacted_df.empty
