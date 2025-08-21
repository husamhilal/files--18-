import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"

class OpenAIChatService:
    """
    Azure OpenAI chat wrapper with:
    - gpt-5-mini constraints (no top_p, temperature forced to 1.0)
    - Adaptive max_tokens vs max_completion_tokens parameter handling
    """
    def __init__(self, credential):
        self.endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT')
        self.api_version = os.environ.get('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
        self.deployment_name = os.environ.get('AZURE_OPENAI_CHAT_DEPLOYMENT')
        self.max_tokens_default = int(os.environ.get('AZURE_OPENAI_MAX_TOKENS', '1500'))
        self.temperature = float(os.environ.get('AZURE_OPENAI_TEMPERATURE', '0.7'))

        if not self.endpoint or not self.deployment_name:
            raise ValueError("Azure OpenAI endpoint and deployment must be configured")

        # gpt-5-mini constraints
        model_lower = (self.deployment_name or "").lower()
        self._supports_top_p = False if "gpt-5" in model_lower else True
        self._force_temperature_one = True if "gpt-5" in model_lower else False

        # Token parameter selector (auto-switches based on 400 error hints)
        self._use_max_completion_tokens = False

        def token_provider():
            token = credential.get_token(COGNITIVE_SCOPE).token
            return token

        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            azure_ad_token_provider=token_provider,
            timeout=30.0,
            max_retries=2
        )
        logger.info("Azure OpenAI client initialized")

    def get_system_prompt(self, document_data: Optional[Dict] = None) -> str:
        base = "You are a professional banking assistant. Be precise, clear, and privacy-conscious.\n"
        if document_data:
            banking = document_data.get('banking_info', {})
            kv = document_data.get('key_value_pairs', [])
            conf = document_data.get('confidence_scores', {})
            kv_sample = "; ".join([f"{(i.get('key') or '')}: {(i.get('value') or '')}" for i in kv[:5]])
            base += (
                "Document context available.\n"
                f"- Accounts: {banking.get('account_numbers', [])}\n"
                f"- Amounts: {banking.get('amounts', [])}\n"
                f"- Dates: {banking.get('dates', [])}\n"
                f"- Names: {banking.get('names', [])}\n"
                f"- Avg Confidence: {conf.get('average', 0):.1%}\n"
                f"- Key-Values (sample): {kv_sample}\n"
            )
        return base

    def _create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ):
        """
        Calls chat.completions.create with model-specific constraints:
        - Auto-switches between max_tokens and max_completion_tokens
        - Omits top_p if the model doesn't support it (e.g., gpt-5-mini)
        - Forces temperature=1 if the model requires it (e.g., gpt-5-mini)
        - Retries once when a 400 error indicates an unsupported parameter
        """
        if max_tokens is None:
            max_tokens = self.max_tokens_default

        # Apply temperature constraints
        eff_temperature = 1.0 if self._force_temperature_one else (self.temperature if temperature is None else temperature)

        def do_call(use_completion_param: bool, include_top_p: bool, temp: Optional[float]):
            kwargs = {
                "model": self.deployment_name,
                "messages": messages,
            }
            # Token param
            if use_completion_param:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens

            # Temperature
            if temp is not None:
                kwargs["temperature"] = float(temp)

            # top_p only if supported
            if include_top_p:
                kwargs["top_p"] = 0.95

            return self.client.chat.completions.create(**kwargs)

        attempts = 0
        use_completion_param = self._use_max_completion_tokens
        include_top_p = self._supports_top_p
        temp_val = eff_temperature

        while attempts < 2:
            try:
                return do_call(use_completion_param, include_top_p, temp_val)
            except Exception as e:
                msg = str(e)
                # Flip token parameter if needed
                if "Unsupported parameter: 'max_tokens'" in msg and "max_completion_tokens" in msg:
                    use_completion_param = True
                    self._use_max_completion_tokens = True
                    attempts += 1
                    continue
                if "Unsupported parameter: 'max_completion_tokens'" in msg and "max_tokens" in msg:
                    use_completion_param = False
                    self._use_max_completion_tokens = False
                    attempts += 1
                    continue
                # Remove top_p if not supported
                if ("Unsupported parameter" in msg or "not supported" in msg) and "top_p" in msg:
                    include_top_p = False
                    self._supports_top_p = False
                    attempts += 1
                    continue
                # Force temperature=1 if required
                low = msg.lower()
                if "temperature" in low and ("must be 1" in low or "only supports" in low or "supported values" in low):
                    temp_val = 1.0
                    self._force_temperature_one = True
                    attempts += 1
                    continue
                # Unknown error, re-raise
                raise

        # Final attempt with last known-good settings
        return do_call(use_completion_param, include_top_p, temp_val)

    async def chat(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        try:
            resp = self._create_chat_completion(messages=messages)
            content = resp.choices[0].message.content
            tokens = getattr(resp, 'usage', None).total_tokens if getattr(resp, 'usage', None) else 0
            return {
                'success': True,
                'message': content,
                'tokens_used': tokens,
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'timestamp': datetime.utcnow().isoformat()}

    async def respond_with_context(self, user_message: str, document_data: Optional[Dict] = None, history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        messages = [{"role": "system", "content": self.get_system_prompt(document_data)}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})
        return await self.chat(messages)

    def summarize(self, document_data: Dict) -> Dict[str, Any]:
        try:
            messages = [
                {"role": "system", "content": self.get_system_prompt(document_data)},
                {"role": "user", "content": "Summarize the key points of this banking document in a short paragraph."}
            ]
            resp = self._create_chat_completion(messages=messages, max_tokens=300, temperature=0.3)
            return {'success': True, 'summary': resp.choices[0].message.content, 'timestamp': datetime.utcnow().isoformat()}
        except Exception as e:
            return {'success': False, 'error': str(e), 'timestamp': datetime.utcnow().isoformat()}

    def test_connection(self) -> Dict[str, Any]:
        try:
            resp = self._create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say OK."}
                ],
                max_tokens=5,
                temperature=0.0
            )
            return {'success': True, 'response': resp.choices[0].message.content}
        except Exception as e:
            return {'success': False, 'error': str(e)}