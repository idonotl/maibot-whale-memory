from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace, ModuleType
import asyncio
import importlib
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
pkg = ModuleType("whale_memory_test")
pkg.__path__ = [str(ROOT)]
sys.modules["whale_memory_test"] = pkg
e = importlib.import_module("whale_memory_test.engine")
p = importlib.import_module("whale_memory_test.plugin")


def fact(text="这位用户喜欢桂花乌龙茶", quote="我最喜欢桂花乌龙茶", key="茶饮偏好", kind="fact"):
    return dict(text=text, quote=quote, fact_key=key, kind=kind, importance=.7)


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = e.Store(Path(self.tmp.name)/"test.db")
        self.store.start()

    def tearDown(self):
        self.tmp.cleanup()

    def test_persistent_and_question_alias(self):
        self.store.save("private:u", "u", [fact()], "1")
        reopened = e.Store(self.store.path)
        rows = reopened.recall("private:u", "我最喜欢喝什么茶", "turn", author="u")
        self.assertEqual(rows[0]["text"], fact()["text"])

    def test_scope_and_group_author_isolation(self):
        self.store.save("private:u", "u", [fact()], "1")
        self.assertEqual(self.store.recall("group:g", "桂花乌龙茶", "2"), [])
        self.store.save("group:g", "other", [fact()], "3")
        self.assertEqual(self.store.recall("group:g", "我喜欢什么茶", "4", author="u"), [])
        self.assertTrue(self.store.recall("group:g", "他喜欢桂花乌龙茶吗", "5", author="u"))
        self.assertEqual(self.store.recall("group:other", "桂花乌龙茶", "6"), [])

    def test_fact_supersedes_only_same_author_scope(self):
        self.store.save("s", "u", [fact()], "1")
        self.store.save("s", "u", [fact("这位用户现在喜欢茉莉花茶", "我现在喜欢茉莉花茶")], "2")
        rows = self.store.recall("s", "我喜欢什么茶", "3", author="u")
        self.assertEqual(len(rows), 1)
        self.assertIn("茉莉", rows[0]["text"])
        self.assertEqual(self.store.list_recent()[1]["status"], "superseded")

    def test_unrelated_and_greeting_are_not_recalled(self):
        self.store.save("s", "u", [fact()], "1")
        self.assertEqual(self.store.recall("s", "你好在吗哈哈", "2"), [])
        self.assertEqual(self.store.recall("s", "明天的足球比赛谁赢", "3"), [])

    def test_decay_and_stable_fact(self):
        self.store.save("s", "u", [fact(kind="episode", key="")], "1", now=100)
        self.assertEqual(self.store.recall("s", "桂花乌龙茶", "2", now=100+86400*900), [])
        self.store.save("stable", "u", [fact()], "3", now=100)
        self.assertTrue(self.store.recall("stable", "桂花乌龙茶", "4", now=100+86400*900))

    def test_quota_duplicate_and_reinforcement_dedup(self):
        self.assertEqual(self.store.save("s", "u", [fact()], "1", daily_limit=1), 1)
        self.assertEqual(self.store.save("s", "u", [fact()], "1", daily_limit=1), 0)
        self.assertEqual(self.store.save("s", "u", [fact("这位用户喜欢茉莉花茶")], "2", daily_limit=1), 0)
        a = self.store.recall("s", "桂花乌龙茶", "same")
        b = self.store.recall("s", "桂花乌龙茶", "same")
        self.assertAlmostEqual(b[0]["reinforcement"], .2)
        c = self.store.recall("s", "桂花乌龙茶", "same")
        self.assertAlmostEqual(c[0]["reinforcement"], .2)

    def test_forget_does_not_delete_other_author(self):
        self.store.save("s", "u", [fact()], "1")
        self.store.save("s", "v", [fact()], "2")
        self.assertEqual(self.store.forget("s", "u", "桂花"), 1)
        self.assertEqual(self.store.recall("s", "我喝什么茶", "3", author="u"), [])
        self.assertTrue(self.store.recall("s", "我喝什么茶", "4", author="v"))

    def test_forget_also_removes_superseded_matching_content(self):
        self.store.save("s", "u", [fact()], "1")
        self.store.save("s", "u", [fact("这位用户现在喜欢茉莉花茶", "我现在喜欢茉莉花茶")], "2")
        self.assertEqual(self.store.forget("s", "u", "桂花"), 1)
        self.assertEqual(len(self.store.list_recent()), 1)

    def test_delayed_extraction_cannot_restore_forgotten_memory(self):
        stamp = __import__('time').time()-1
        self.store.forget("s", "u", "桂花")
        self.assertEqual(self.store.save("s", "u", [fact()], "old", source_stamp=stamp), 0)

    def test_extraction_requires_quote_and_excludes_secrets(self):
        data = dict(memories=[fact()])
        self.assertEqual(len(e.parse_extraction(json.dumps(data, ensure_ascii=False), "我最喜欢桂花乌龙茶")), 1)
        self.assertEqual(e.parse_extraction(json.dumps(data), "我没说过"), [])
        data["memories"][0].update(text="这位用户的密码是abc", quote="我的密码是abc")
        self.assertEqual(e.parse_extraction(json.dumps(data), "我的密码是abc"), [])

    def test_allowlist(self):
        cfg = SimpleNamespace(bot_account_id="b", private_users=["u"], group_ids=["g"], webui_test_prefix="memory-acceptance-")
        m = dict(platform="qq", bot="b", user="u", group="", namespace="")
        private = p.scope_for(m, cfg)
        self.assertTrue(private)
        m["group"] = "g"
        self.assertNotEqual(p.scope_for(m, cfg), private)
        m["group"] = "unauthorized"
        self.assertEqual(p.scope_for(m, cfg), "")


class WiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_background_extraction_and_real_sdk_hooks(self):
        with TemporaryDirectory() as tmp:
            plugin = p.create_plugin()
            plugin.set_plugin_config({"plugin": {"enabled": True, "config_version": "0.1.0", "private_users": ["u"], "bot_account_id": "b"}})
            class LLM:
                async def generate(self, **kw):
                    self.kw = kw
                    return {"success": True, "response": json.dumps({"memories": [fact()]}, ensure_ascii=False)}
            llm = LLM()
            plugin._ctx = SimpleNamespace(paths=SimpleNamespace(data_dir=Path(tmp)), llm=llm, logger=__import__('logging').getLogger("test"))
            await plugin.on_load()
            m = dict(scope="s", user="u", stamp=__import__('time').time(), text="记住，我最喜欢桂花乌龙茶", mid="1")
            await plugin.extract(("s", "u"), [m])
            self.assertEqual(plugin.stats["extracted"], 1)
            self.assertEqual(llm.kw["model_name"], "deepseek-flash-affect")
            self.assertNotIn("embed", str(llm.kw))
            self.assertEqual(plugin.last_error, "")
            await plugin.on_unload()


if __name__ == "__main__":
    unittest.main()
