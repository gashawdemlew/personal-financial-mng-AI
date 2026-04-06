from typing import Dict, List

from app.finance import engine
from app.finance.intents import detect_intent, guess_category
from app.finance.llm_interpreter import SUPPORTED_INTENTS, finance_llm_interpreter
from app.finance.periods import parse_period, period_from_llm
from app.finance.repository import distinct_categories, list_all_transactions_extended


def _should_include_archive(question: str, period: Dict) -> bool:
    text = str(question or "").strip().lower()
    if any(token in text for token in ["annual", "yearly", "this year", "last year", "past year", "12 month", "12-month"]):
        return True
    if period and period.get("start") and period.get("end"):
        if (period["end"] - period["start"]).days > 183:
            return True
    months = period.get("months") if period else None
    if isinstance(months, int) and months > 6:
        return True
    return False


def answer_finance_question(
    usecase_id: str,
    user_id: str,
    question: str,
    linked_account_id: str | None = None,
) -> Dict:
    out_of_context_answer = "It's out of context, I am here to help you with Personal Financial Managment"

    scope = finance_llm_interpreter.classify_scope(question)
    scope_flag = scope.get("is_financial")
    if isinstance(scope_flag, str):
        scope_flag = scope_flag.strip().lower() in {"true", "1", "yes"}
    if scope_flag is False:
        return {
            "success": True,
            "usecase_id": usecase_id,
            "user_id": user_id,
            "intent": "out_of_scope",
            "answer": out_of_context_answer,
            "llm_interpretation": {
                "scope": scope,
                "intent": {},
                "period": {},
                "entities": {},
            },
            "data": {"answer": out_of_context_answer, "out_of_scope": True},
        }

    llm_intent = finance_llm_interpreter.classify_intent(question)
    intent = llm_intent.get("intent")
    if intent not in SUPPORTED_INTENTS:
        intent = detect_intent(question)
    if intent not in SUPPORTED_INTENTS:
        return {
            "success": True,
            "usecase_id": usecase_id,
            "user_id": user_id,
            "intent": "out_of_scope",
            "answer": out_of_context_answer,
            "llm_interpretation": {
                "scope": scope,
                "intent": llm_intent,
                "period": {},
                "entities": {},
            },
            "data": {"answer": out_of_context_answer, "out_of_scope": True},
        }

    llm_period = finance_llm_interpreter.extract_period(question)
    period = period_from_llm(llm_period) or parse_period(question)
    include_archive = _should_include_archive(question, period or {})
    rows = list_all_transactions_extended(
        usecase_id=usecase_id,
        user_id=user_id,
        include_archive=include_archive,
        linked_account_id=linked_account_id,
    )
    categories = distinct_categories(
        usecase_id=usecase_id,
        user_id=user_id,
        include_archive=include_archive,
        linked_account_id=linked_account_id,
    )

    llm_entities = finance_llm_interpreter.extract_entities(question, categories)
    llm_category = str(llm_entities.get("category") or "").strip().lower()
    category = llm_category or guess_category(question, categories)

    if intent == "category_expense":
        data = engine.category_expense(rows, category, period=period)
    elif intent == "safe_spend_today":
        data = engine.safe_spend_today(rows)
    elif intent == "explain_reversal":
        data = engine.explain_reversal(rows)
    elif intent == "income_vs_expense":
        data = engine.income_vs_expense(rows, period=period)
    elif intent == "fixed_vs_variable":
        data = engine.fixed_vs_variable(rows)
    elif intent == "financial_health_score":
        data = engine.financial_health_score(rows, period=period)
    elif intent == "savings_recommendation":
        data = engine.savings_recommendation(rows, period=period)
    elif intent == "budget_intelligence":
        data = engine.budget_intelligence(rows)
    elif intent == "historical_trend":
        data = engine.historical_trend(rows)
    else:
        data = engine.summary(rows)

    deterministic_answer = data.get("answer", "")
    rendered_answer = finance_llm_interpreter.render_answer(
        question=question,
        deterministic_data=data,
        deterministic_answer=deterministic_answer,
    )

    return {
        "success": True,
        "usecase_id": usecase_id,
        "user_id": user_id,
        "intent": intent,
        "answer": rendered_answer,
        "llm_interpretation": {
            "intent": llm_intent,
            "period": llm_period,
            "entities": llm_entities,
        },
        "data": data,
        "data_scope": "active_plus_archive" if include_archive else "active_only",
        "account_scope": "account" if linked_account_id else "portfolio",
        "linked_account_id": linked_account_id or None,
    }
