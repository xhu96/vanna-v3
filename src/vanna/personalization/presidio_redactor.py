import logging
import pandas as pd

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False


logger = logging.getLogger(__name__)


class PresidioRedactor:
    """
    Integrates Microsoft Presidio to analyze and anonymize/redact
    Personally Identifiable Information (PII) from DataFrames before
    they are passed to LLMs or displayed to users.
    """

    def __init__(self, entities=None):
        if not PRESIDIO_AVAILABLE:
            raise ImportError(
                "Presidio packages are required. Install with: "
                "`pip install presidio-analyzer presidio-anonymizer`"
            )
        # Default entities to redact if none provided
        self.entities = entities or [
            "CREDIT_CARD",
            "EMAIL_ADDRESS",
            "IBAN_CODE",
            "IP_ADDRESS",
            "PERSON",
            "PHONE_NUMBER",
            "US_SSN",
            "US_BANK_NUMBER",
            "US_PASSPORT"
        ]
        
        # In a real enterprise app, you'd load models lazily or as a singleton
        logger.info("Initializing Presidio Analyzer Engine...")
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()

    def redact_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Scans all string columns in the DataFrame and replaces PII
        entities with redacted markers (e.g., <PERSON>).
        """
        if df.empty:
            return df
            
        redacted_df = df.copy()
        
        for col in redacted_df.columns:
            # We only want to analyze text/string columns
            if pd.api.types.is_string_dtype(redacted_df[col]):
                def anonymize_text(text):
                    if not isinstance(text, str) or not text.strip():
                        return text
                        
                    results = self.analyzer.analyze(
                        text=text, 
                        entities=self.entities, 
                        language='en'
                    )
                    
                    if not results:
                        return text
                        
                    anonymized_result = self.anonymizer.anonymize(
                        text=text,
                        analyzer_results=results
                    )
                    return anonymized_result.text

                redacted_df[col] = redacted_df[col].apply(anonymize_text)
                
        return redacted_df
