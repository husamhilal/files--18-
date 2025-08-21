import os
import logging
import re
from typing import Dict, List, Any
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.exceptions import AzureError

logger = logging.getLogger(__name__)

class DocumentIntelligenceService:
    def __init__(self, credential):
        endpoint = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT')
        if not endpoint:
            raise ValueError("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not set")
        self.client = DocumentAnalysisClient(endpoint=endpoint, credential=credential)
        logger.info("DocumentAnalysisClient initialized")

    def analyze_document(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, "rb") as f:
                poller = self.client.begin_analyze_document("prebuilt-document", document=f)
            result = poller.result()

            key_values = []
            confidences = []

            if getattr(result, 'key_value_pairs', None):
                for kv in result.key_value_pairs:
                    key = kv.key.content if kv.key else ""
                    val = kv.value.content if kv.value else ""
                    conf = (kv.confidence or 0.0)
                    key_values.append({'key': key, 'value': val, 'confidence': conf})
                    confidences.append(conf)

            paragraphs = []
            if getattr(result, 'paragraphs', None):
                for p in result.paragraphs:
                    paragraphs.append(p.content)
            text_blob = "\n".join(paragraphs)

            banking_info = {
                'account_numbers': self._extract_account_numbers(text_blob),
                'amounts': self._extract_amounts(text_blob),
                'dates': self._extract_dates(text_blob),
                'names': self._extract_names(key_values),
                'addresses': self._extract_addresses(key_values)
            }

            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

            return {
                'banking_info': banking_info,
                'key_value_pairs': key_values,
                'tables': self._extract_tables(result),
                'confidence_scores': {'average': avg_conf}
            }
        except AzureError as e:
            logger.error(f"Azure DI error: {e}")
            raise
        except Exception as e:
            logger.error(f"Document analysis error: {e}")
            raise

    def _extract_account_numbers(self, text: str) -> List[str]:
        patterns = [r'\b\d{9}\b', r'\b\d{8,20}\b', r'\b[0-9]{4}[-\s][0-9]{4}[-\s][0-9]{4,8}\b']
        found = set()
        for pat in patterns:
            for m in re.findall(pat, text):
                found.add(m)
        return list(found)[:10]

    def _extract_amounts(self, text: str) -> List[str]:
        pat = r'(?:(?:USD|US\$|\$)\s?)?-?\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b'
        vals = re.findall(pat, text)
        vals = [v.strip() for v in vals if '.' in v or ',' in v or '$' in v or 'USD' in v.upper()]
        return list(dict.fromkeys(vals))[:10]

    def _extract_dates(self, text: str) -> List[str]:
        patterns = [
            r'\b\d{4}-\d{2}-\d{2}\b',
            r'\b\d{2}/\d{2}/\d{4}\b',
            r'\b\d{2}-\d{2}-\d{4}\b',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b'
        ]
        found = set()
        for pat in patterns:
            for m in re.findall(pat, text, flags=re.IGNORECASE):
                found.add(m)
        return list(found)[:10]

    def _extract_names(self, kv_pairs: List[Dict[str, Any]]) -> List[str]:
        names = []
        for kv in kv_pairs:
            k = (kv.get('key') or '').lower()
            if any(x in k for x in ['account name', 'name', 'account holder', 'payee']):
                v = kv.get('value') or ''
                if v and v not in names:
                    names.append(v)
        return names[:5]

    def _extract_addresses(self, kv_pairs: List[Dict[str, Any]]) -> List[str]:
        addrs = []
        for kv in kv_pairs:
            k = (kv.get('key') or '').lower()
            if 'address' in k:
                v = kv.get('value') or ''
                if v and v not in addrs:
                    addrs.append(v)
        return addrs[:5]

    def _extract_tables(self, result) -> List[Dict[str, Any]]:
        tables_out = []
        if getattr(result, 'tables', None):
            for t in result.tables[:3]:
                tables_out.append({'row_count': t.row_count, 'column_count': t.column_count})
        return tables_out