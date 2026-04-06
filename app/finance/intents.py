from typing import List


def detect_intent(question: str) -> str:
    q = (question or "").lower()
    if "reverse" in q or "reversal" in q or "refund" in q:
        return "explain_reversal"
    if "safely spend" in q or "safe spend" in q:
        return "safe_spend_today"
    if "health score" in q or "financial health" in q:
        return "financial_health_score"
    if "income vs" in q or ("income" in q and "expense" in q):
        return "income_vs_expense"
    if "fixed" in q and "variable" in q:
        return "fixed_vs_variable"
    if "trend" in q or "pattern" in q or "historical" in q:
        return "historical_trend"
    if "save" in q or "savings" in q or "goal" in q:
        return "savings_recommendation"
    if "budget" in q:
        return "budget_intelligence"
    if "expense" in q or "spent" in q or "spend" in q:
        return "category_expense"
    return "summary"


def guess_category(question: str, known_categories: List[str]) -> str:
    q = (question or "").lower()
    for c in known_categories:
        if c and c.lower() in q:
            return c.lower()
    for common in ["transport", "food", "rent", "shopping", "utilities", "education", "health", "other"]:
        if common in q:
            return common
    return ""

