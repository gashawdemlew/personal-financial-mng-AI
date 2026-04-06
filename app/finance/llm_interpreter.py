import json
import re
from datetime import date, datetime
from typing import Dict, List, Optional

import requests

from app.config import VLLM_MODEL_NAME, VLLM_URL


SUPPORTED_INTENTS = [
    "category_expense",
    "safe_spend_today",
    "explain_reversal",
    "income_vs_expense",
    "fixed_vs_variable",
    "financial_health_score",
    "savings_recommendation",
    "budget_intelligence",
    "historical_trend",
    "summary",
]


def _extract_json(text: str) -> Dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except Exception:
        return {}


class FinanceLLMInterpreter:
    def __init__(self, model_name: str = VLLM_MODEL_NAME, url: str = VLLM_URL):
        self.model_name = model_name
        self.url = url

    def _call_json(self, system_prompt: str, user_prompt: str, timeout: int = 30) -> Dict:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
        }
        try:
            r = requests.post(self.url, json=payload, timeout=timeout)
            if r.status_code != 200:
                return {}
            content = r.json()["choices"][0]["message"]["content"]
            return _extract_json(content)
        except Exception:
            return {}

    def classify_intent(self, question: str) -> Dict:
        system_prompt = (
            "You classify finance user questions into a single intent. "
            "Return only JSON with keys: intent, confidence, reason. "
            f"intent must be one of: {', '.join(SUPPORTED_INTENTS)}."
        )
        user_prompt = f"Question: {question}"
        return self._call_json(system_prompt, user_prompt)

    def classify_scope(self, question: str) -> Dict:
        system_prompt = (
            "You determine whether a user question is in scope for a personal financial management assistant. "
            "In-scope questions are about personal transactions, balances, spending, income, savings, budgeting, reversals, "
            "categories, or financial behavior. "
            "Return only JSON with keys: is_financial, confidence, reason."
        )
        user_prompt = f"Question: {question}"
        return self._call_json(system_prompt, user_prompt)

    def extract_period(self, question: str, today: Optional[date] = None) -> Dict:
        today = today or date.today()
        system_prompt = (
            "Extract a time period from a finance question. "
            "Return only JSON with keys: kind, label, start_date, end_date, months. "
            "Allowed kind: this_week, this_month, last_month, last_n_months, explicit_range, none. "
            "Dates must be YYYY-MM-DD. If unknown use kind='none'."
        )
        user_prompt = (
            f"Today is {today.isoformat()}.\n"
            f"Question: {question}\n"
            "Infer period safely."
        )
        return self._call_json(system_prompt, user_prompt)

    def extract_entities(self, question: str, known_categories: List[str]) -> Dict:
        system_prompt = (
            "Extract finance entities from user question. "
            "Return only JSON with keys: category, goal_amount, target_months."
            "category should be lower-case string or empty."
            "goal_amount and target_months should be numbers or null."
        )
        user_prompt = (
            f"Known categories: {known_categories}\n"
            f"Question: {question}"
        )
        return self._call_json(system_prompt, user_prompt)

    def render_answer(self, question: str, deterministic_data: Dict, deterministic_answer: str) -> str:
        system_prompt = (
            "You are a finance assistant response formatter. "
            "Do not change numeric values. "
            "Use the deterministic answer and data to produce a concise user-facing answer. "
            "Return only JSON: {\"answer\": \"...\"}."
        )
        user_prompt = (
            f"Question: {question}\n"
            f"Deterministic answer: {deterministic_answer}\n"
            f"Data: {json.dumps(deterministic_data, ensure_ascii=True)}"
        )
        parsed = self._call_json(system_prompt, user_prompt)
        answer = parsed.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return deterministic_answer


finance_llm_interpreter = FinanceLLMInterpreter()
