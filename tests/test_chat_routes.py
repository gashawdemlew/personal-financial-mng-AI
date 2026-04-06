import asyncio
import unittest
from unittest.mock import Mock, patch

from app.main import admin_list_chat_quota_config, delete_chat_session, get_chat_daily_limit_for_usecase, rag_chat, rag_chat_quota, rag_chat_summary


class TestChatRoutes(unittest.TestCase):
    def test_financial_guide_requires_user_id_for_rag_chat(self):
        payload = {
            "usecase_id": "financial-guide",
            "chat_id": "chat-1",
            "question": "What is my highest expense in the last month?",
            "with_audio": False,
        }

        with patch("app.main.ensure_usecase_registered", return_value=None):
            result = asyncio.run(rag_chat(payload))

        self.assertEqual(
            result,
            {"success": False, "message": "user_id required for financial-guide usecase"},
        )

    def test_rag_chat_returns_daily_limit_response(self):
        payload = {
            "usecase_id": "kacha-wallet",
            "chat_id": "chat-1",
            "question": "hello",
            "with_audio": False,
        }

        with patch("app.main.ensure_usecase_registered", return_value=None), \
             patch(
                 "app.main.consume_daily_chat_quota",
                 return_value={"allowed": False, "limit": 10, "used": 11, "remaining": 0, "reset_on": "2026-03-23"},
             ):
            result = asyncio.run(rag_chat(payload))

        self.assertFalse(result["success"])
        self.assertIn("Daily chat limit reached", result["message"])
        self.assertEqual(result["quota"]["limit"], 10)

    def test_get_chat_daily_limit_for_usecase_uses_per_usecase_values(self):
        with patch("app.main.get_chat_quota_config", return_value=None), \
             patch("app.main._parse_chat_daily_limits", return_value={"financial-guide": 10, "superapp-guidance": 20, "default": 10}):
            self.assertEqual(get_chat_daily_limit_for_usecase("financial-guide"), 10)
            self.assertEqual(get_chat_daily_limit_for_usecase("superapp-guidance"), 20)

    def test_get_chat_daily_limit_for_usecase_prefers_database_config(self):
        with patch("app.main.get_chat_quota_config", return_value={"usecase_id": "financial-guide", "daily_limit": 7}):
            self.assertEqual(get_chat_daily_limit_for_usecase("financial-guide"), 7)

    def test_rag_chat_quota_returns_current_status(self):
        with patch("app.main.ensure_usecase_registered", return_value=None), \
             patch(
                 "app.main.get_daily_chat_quota_status",
                 return_value={"allowed": True, "limit": 20, "used": 3, "remaining": 17, "identifier": "user_1", "reset_on": "2026-03-23"},
             ):
            result = asyncio.run(
                rag_chat_quota(usecase_id="superapp-guidance", user_id="user_1", chat_id=None)
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["quota"]["limit"], 20)
        self.assertEqual(result["quota"]["used"], 3)
        self.assertEqual(result["quota"]["remaining"], 17)

    def test_admin_list_chat_quota_config_returns_db_config(self):
        with patch("app.main.ensure_usecase_registered", return_value=None), \
             patch(
                 "app.main.get_chat_quota_config",
                 return_value={"usecase_id": "financial-guide", "daily_limit": 8, "created_at": "", "updated_at": ""},
             ):
            result = asyncio.run(admin_list_chat_quota_config(usecase_id="financial-guide"))

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "database")
        self.assertEqual(result["effective_daily_limit"], 8)

    def test_chat_summary_uses_bounded_history_window(self):
        payload = {
            "usecase_id": "financial-guide",
            "chat_id": "chat-1",
        }
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ]
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "bounded summary"}}]
        }

        with patch("app.main.resolve_chat_usecase", return_value={"ok": True, "usecase_id": "financial-guide"}), \
             patch("app.main.resolve_effective_chat_id", return_value={"ok": True, "chat_id": "chat-1"}), \
             patch("app.main.ensure_usecase_registered", return_value=None), \
             patch("app.main.load_best_history", return_value=history), \
             patch("app.main.summary_history_window", return_value=history[:2]) as summary_window_mock, \
             patch("app.main.requests.post", return_value=fake_response) as post_mock:
            result = asyncio.run(rag_chat_summary(payload))

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"], "bounded summary")
        summary_window_mock.assert_called_once_with(history)
        request_payload = post_mock.call_args.kwargs["json"]
        transcript = request_payload["messages"][1]["content"]
        self.assertIn("1. USER: first", transcript)
        self.assertIn("2. ASSISTANT: second", transcript)
        self.assertNotIn("third", transcript)

    def test_delete_chat_session_clears_global_and_finance_history(self):
        with patch("app.main.resolve_chat_usecase", return_value={"ok": True, "usecase_id": "financial-guide"}), \
             patch("app.main.resolve_effective_chat_id", return_value={"ok": True, "chat_id": "chat-1"}), \
             patch("app.main.ensure_usecase_registered", return_value=None), \
             patch("app.main.redis_client.delete") as redis_delete_mock, \
             patch("app.main.delete_global_chat_messages") as delete_global_mock, \
             patch("app.main.delete_chat_messages") as delete_finance_mock:
            result = asyncio.run(delete_chat_session("chat-1", usecase_id="financial-guide"))

        self.assertEqual(
            result,
            {
                "success": True,
                "usecase_id": "financial-guide",
                "chat_id": "chat-1",
                "message": "Chat session and history deleted",
            },
        )
        redis_delete_mock.assert_called_once()
        delete_global_mock.assert_called_once_with(usecase_id="financial-guide", chat_id="chat-1")
        delete_finance_mock.assert_called_once_with(usecase_id="financial-guide", chat_id="chat-1")


if __name__ == "__main__":
    unittest.main()
