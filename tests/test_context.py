import unittest

from helm.bridge.context import NEAR_LIMIT_PERCENT, context_gauge, context_percent
from helm.bridge.items import agent_title
from helm.contract import Context


def agent(pane: str, context=None, title=None) -> dict:
    tokens = {}
    if context is not None:
        tokens["context"] = context
    if title is not None:
        tokens["title"] = title
    return {"agent": "claude", "agent_status": "idle", "pane_id": pane, "tokens": tokens}


class ContextPercentTest(unittest.TestCase):
    def test_usagebar_forms(self):
        # The forms usagebar writes (internal/core/format.go and update.go there).
        cases = {
            "⛁ 49% (492k)": 49,
            "⚠️ 85% (850k)": 85,
            "⚠ 85% (850k)": 85,
            "49% (492k)": 49,
            "49%": 49,
            "⛁ 0% (512)": 0,
            "⚠️ 100% (1.0M)": 100,
            "5h 72% · ⛁ 14% (136k)": 14,  # the account's limit comes first
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(context_percent(text), want)

    def test_anything_else_is_unknown(self):
        for text in ["compacted (31k)", "⚠️ compacted (31k)", "compacted", "31k", "⛁ 31k", "",
                     "5h 72%", "7d 84%", "5h 72% · compacted (31k)", "101%", "12.5%", "abc 12%", None, 49, []]:
            with self.subTest(text=text):
                self.assertIsNone(context_percent(text))


class ContextGaugeTest(unittest.TestCase):
    def test_fullest_agent_and_count_near_the_limit(self):
        agents = [
            agent("w1:p1", "⛁ 49% (492k)", "fm-clients"),
            agent("w1:p2", "⚠️ 91% (910k)", "widget-cache"),
            agent("w1:p3", "compacted (31k)", "fresh"),
            agent("w1:p4", "⚠️ %d%% (800k)" % NEAR_LIMIT_PERCENT, "edge"),
            agent("w1:p5", None, "no-usagebar"),
        ]
        self.assertEqual(context_gauge(agents, agent_title), Context(top_used=91, top_agent="widget-cache", near_limit=2))

    def test_none_near(self):
        agents = [agent("w1:p1", "⛁ 79% (790k)", "a"), agent("w1:p2", "⛁ 12% (120k)", "b")]
        self.assertEqual(context_gauge(agents, agent_title), Context(top_used=79, top_agent="a", near_limit=0))

    def test_unknown_stays_unknown(self):
        # No agents, or none with a percent: unknown, never "0 % used".
        self.assertEqual(context_gauge([], agent_title), Context())
        agents = [agent("w1:p1", "compacted (26k)"), agent("w1:p2"), {"pane_id": "w1:p3", "tokens": "bad"}, {"pane_id": "w1:p4"}]
        self.assertEqual(context_gauge(agents, agent_title), Context())

    def test_first_of_equals_wins_and_name_falls_back(self):
        agents = [
            {"pane_id": "w2:p1", "terminal_title_stripped": "Claude Code", "tokens": {"context": "50%"}},
            agent("w2:p2", "50%", "second"),
        ]
        self.assertEqual(context_gauge(agents, agent_title).top_agent, "Claude Code")
        self.assertEqual(context_gauge([{"pane_id": "w2:p9", "tokens": {"context": "50%"}}], agent_title).top_agent, "w2:p9")
        long_title = agent("w2:p3", "60%", "a-really-long-task-name-for-a-worker-pane")
        self.assertEqual(len(context_gauge([long_title], agent_title).top_agent), 28)


if __name__ == "__main__":
    unittest.main()
