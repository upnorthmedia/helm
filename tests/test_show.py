import os
import tempfile
import time
import unittest
from pathlib import Path

from helm.contract import Item
from helm.bridge.commands import CommandRefused, Runner, check_allowed, openable_url
from helm.bridge.intents import IntentExecutor
from helm.bridge.items import Candidate
from helm.bridge.report_html import render_report
from helm.bridge.show import (LavishSession, ShowTarget, find_target, loopback_board_url, parse_lavish_sessions,
                              report_page)
from tests.helpers import FakeRunner, lavish_listing

NOW = 1_794_270_000.0
TAILNET = "http://deck-mac.example.ts.net:4387/session/%s"


def decision(home_path, task="widget-pricing", detail="Pick A or B", pr_url=None, home="primary", pane="w0:p1"):
    item = Item("decision|%s|%s|%s" % (home, task, task), "decision", "red", task, 0, False, home, detail,
                ["yes", "later", "hold", "focus"], pr_url, None)
    return Candidate(item, task, task, home_path, pane)


class HomeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "fm"
        (self.home / "state").mkdir(parents=True)
        (self.home / "data").mkdir()
        self.cache = root / "cache"
        self.outside = root / "elsewhere"
        self.outside.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text="x", mtime=None):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path


class LavishListingTest(unittest.TestCase):
    def test_parses_rows_and_moves_boards_to_loopback(self):
        out = lavish_listing(
            ("/fm/data/widget-pricing/board.html", "open", TAILNET % "124243bf9534df5d"),
            ("/x/y,z.html", "feedback", "http://127.0.0.1:4390/session/0123456789abcdef"),
        ).replace("/x/y,z.html", '"/x/y,z.html"')
        sessions = parse_lavish_sessions(out)
        self.assertEqual(sessions, [
            LavishSession(Path("/fm/data/widget-pricing/board.html"), "http://127.0.0.1:4387/session/124243bf9534df5d"),
            LavishSession(Path("/x/y,z.html"), "http://127.0.0.1:4390/session/0123456789abcdef"),
        ])
        self.assertEqual(sessions[0].id, "124243bf9534df5d")

    def test_skips_ended_relative_and_non_session_rows(self):
        out = lavish_listing(
            ("/a.html", "ended", TAILNET % "aaaaaaaaaaaaaaaa"),
            ("rel.html", "open", TAILNET % "bbbbbbbbbbbbbbbb"),
            ("/c.html", "open", "https://deck-mac.example:4387/session/cccccccccccccccc"),
            ("/d.html", "open", "http://deck-mac.example/session/dddddddddddddddd"),
            ("/e.html", "open", "http://deck-mac.example:4387/session/eeee?x=1"),
        )
        self.assertEqual(parse_lavish_sessions(out), [])

    def test_garbage_and_empty_output(self):
        self.assertEqual(parse_lavish_sessions(""), [])
        self.assertEqual(parse_lavish_sessions("error: boom\n"), [])
        self.assertEqual(parse_lavish_sessions(lavish_listing()), [])

    def test_loopback_board_url(self):
        self.assertEqual(loopback_board_url("http://localhost:4387/session/abcdef0123456789"),
                         "http://127.0.0.1:4387/session/abcdef0123456789")
        for bad in ("http://h:4387/session/ABCDEF0123456789", "http://h:4387/session/abc", "http://u@h:1/session/abcdef01",
                    "http://h:99999/session/abcdef01", "file:///session/abcdef01", "http://h:4387/session/abcdef01/x",
                    "http://h:4387/session/abcdef01#frag", "javascript:alert(1)", ""):
            self.assertIsNone(loopback_board_url(bad), bad)


class FindTargetTest(HomeCase):
    def test_board_url_in_the_item_text_opens_that_live_board_on_loopback(self):
        sid = "124243bf9534df5d"
        sessions = [LavishSession(self.outside / "review" / "index.html", "http://127.0.0.1:4387/session/%s" % sid)]
        cand = decision(self.home, detail="Pick an option, live board %s (round 2)" % (TAILNET % sid))
        self.assertEqual(find_target(cand, sessions, self.cache),
                         ShowTarget("board", ("open", "http://127.0.0.1:4387/session/%s" % sid)))

    def test_board_url_in_the_newest_status_line(self):
        old, new = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"
        self.write("state/widget-pricing.status", "working [at=1]: board %s\nneeds-decision [at=2]: live board %s\n"
                   % (TAILNET % old, TAILNET % new))
        sessions = [LavishSession(Path("/b/%s.html" % s), "http://127.0.0.1:4387/session/%s" % s) for s in (old, new)]
        target = find_target(decision(self.home), sessions, self.cache)
        self.assertEqual(target.argv, ("open", "http://127.0.0.1:4387/session/%s" % new))

    def test_a_board_url_that_is_not_live_falls_through(self):
        self.write("data/widget-pricing/report.md", "# Report\n")
        cand = decision(self.home, detail="board %s" % (TAILNET % "dead0000dead0000"))
        self.assertEqual(find_target(cand, [], self.cache).what, "report")

    def test_newest_session_in_the_tasks_data_dir(self):
        older = self.write("data/widget-pricing/board-1.html", mtime=100)
        newer = self.write("data/widget-pricing/review/board-2.html", mtime=200)
        other = self.write("data/other-task/board.html", mtime=300)
        sessions = [LavishSession(p, "http://127.0.0.1:4387/session/%016x" % n)
                    for n, p in enumerate((older, newer, other), start=1)]
        target = find_target(decision(self.home), sessions, self.cache)
        self.assertEqual(target, ShowTarget("board", ("open", "http://127.0.0.1:4387/session/0000000000000002")))

    def test_a_named_report_that_is_a_live_session_opens_as_the_board(self):
        page = self.write("data/gizmo-design/review/index.html")
        sessions = [LavishSession(page, "http://127.0.0.1:4387/session/00000000000000aa")]
        cand = decision(self.home, detail="see data/gizmo-design/review/index.html for the options")
        self.assertEqual(find_target(cand, sessions, self.cache).argv, ("open", "http://127.0.0.1:4387/session/00000000000000aa"))

    def test_the_tasks_report_renders_into_the_helm_cache(self):
        report = self.write("data/widget-pricing/report.md", "# Widget pricing\n")
        target = find_target(decision(self.home), [], self.cache)
        page = self.cache / "reports" / "primary-widget-pricing-report.html"
        self.assertEqual(target, ShowTarget("report", ("lavish-axi", str(page), "--reopen", "--no-gate"),
                                            source=report.resolve()))
        self.assertEqual(report_page(self.cache, decision(self.home), report), page)

    def test_a_report_path_named_in_the_item_wins_over_the_default(self):
        self.write("data/widget-pricing/report.md")
        named = self.write("data/pricing-scout/findings.md")
        cand = decision(self.home, detail="Scout wrote `data/pricing-scout/findings.md`; pick A or B")
        target = find_target(cand, None, self.cache)
        self.assertEqual(target.source, named.resolve())
        self.assertTrue(target.argv[1].endswith("primary-widget-pricing-findings.html"))

    def test_an_absolute_report_path_in_the_status_line(self):
        named = self.write("data/pricing-scout/report.md")
        self.write("state/widget-pricing.status", "needs-decision [at=1]: report at %s, pick one\n" % named)
        self.assertEqual(find_target(decision(self.home), [], self.cache).source, named.resolve())

    def test_an_html_report_opens_in_lavish_as_it_is(self):
        page = self.write("data/widget-pricing/plan.html")
        cand = decision(self.home, detail="plan: data/widget-pricing/plan.html")
        self.assertEqual(find_target(cand, [], self.cache),
                         ShowTarget("report", ("lavish-axi", str(page.resolve()), "--reopen", "--no-gate")))

    def test_report_paths_outside_the_items_own_data_dir_are_ignored(self):
        (self.outside / "data" / "evil").mkdir(parents=True)
        (self.outside / "data" / "evil" / "report.md").write_text("x")
        self.write("data/.secrets/report.md")
        self.write("state/notes.md")
        (self.home / "data" / "linked").symlink_to(self.outside / "data" / "evil")
        detail = ("%s/data/evil/report.md data/.secrets/report.md data/../state/notes.md data/linked/report.md"
                  % self.outside)
        cand = decision(self.home, task="widget-pricing", detail=detail)
        self.assertIsNone(find_target(cand, [], self.cache))

    def test_pr_when_there_is_no_board_or_report(self):
        url = "https://github.com/example/alpha/pull/12"
        target = find_target(decision(self.home, task="alpha-fix", pr_url=url), [], self.cache)
        self.assertEqual(target, ShowTarget("PR", ("open", url)))

    def test_board_beats_report_beats_pr(self):
        url = "https://github.com/example/alpha/pull/12"
        self.write("data/alpha-fix/report.md")
        board = self.write("data/alpha-fix/board.html")
        cand = decision(self.home, task="alpha-fix", pr_url=url)
        self.assertEqual(find_target(cand, [LavishSession(board, "http://127.0.0.1:4387/session/00000000000000bb")],
                                     self.cache).what, "board")
        self.assertEqual(find_target(cand, [], self.cache).what, "report")

    def test_herdr_items_and_bare_decisions_only_focus(self):
        herdr = Candidate(Item("herdr|w:p1", "herdr_blocked", "amber", "agent", 0, False, "herdr", "waiting",
                               ["focus"]), "", "", None, "w:p1")
        self.assertIsNone(find_target(herdr, None, self.cache))
        self.assertIsNone(find_target(decision(self.home), [], self.cache))


class RenderReportTest(HomeCase):
    def test_renders_a_report_as_a_styled_page(self):
        md = "\n".join([
            "# Helm case v2: <three> options",
            "",
            "## Summary",
            "",
            "Built **three** options with `case/build.py`, see https://github.com/example/helm/pull/13.",
            "",
            "- **No screws.** The face is one bent cover.",
            "  - nested detail",
            "- Keys: flat caps",
            "",
            "1. first",
            "2. second",
            "",
            "| | Today | C |",
            "| --- | ---: | :---: |",
            "| Board | 4B | LCD-5 |",
            "",
            "> The captain answered on the board.",
            "",
            "```sh",
            "scripts/run_all.sh <helm>",
            "```",
            "",
            "---",
            "[docs](docs/build/bom.md) and [site](https://example.com/a?b=1&c=2)",
        ])
        page = render_report(md, self.home / "data" / "t" / "report.md", "primary", "gizmo-design", NOW)
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("<title>Helm case v2: &lt;three&gt; options</title>", page)
        self.assertIn('<h1 class="title">Helm case v2: &lt;three&gt; options</h1>', page)
        self.assertEqual(page.count("<h1"), 1)  # the first heading became the title
        self.assertIn("<h2>Summary</h2>", page)
        self.assertIn("Built <strong>three</strong> options with <code>case/build.py</code>", page)
        self.assertIn('<a href="https://github.com/example/helm/pull/13" target="_blank" rel="noopener noreferrer">', page)
        self.assertIn("<ul><li><strong>No screws.</strong> The face is one bent cover.\n<ul><li>nested detail</li></ul></li>"
                      "<li>Keys: flat caps</li></ul>", page)
        self.assertIn("<ol><li>first</li><li>second</li></ol>", page)
        self.assertIn('<th style="text-align:right">Today</th>', page)
        self.assertIn('<td style="text-align:center">LCD-5</td>', page)
        self.assertIn("<blockquote><p>The captain answered on the board.</p></blockquote>", page)
        self.assertIn('<pre><code class="language-sh">scripts/run_all.sh &lt;helm&gt;</code></pre>', page)
        self.assertIn("<hr>", page)
        self.assertIn('<span class="path" title="docs/build/bom.md">docs</span>', page)
        self.assertIn('href="https://example.com/a?b=1&amp;c=2"', page)
        self.assertIn("task <b>gizmo-design</b>", page)
        self.assertIn("background: var(--bg)", page)  # paints its own surface, light and dark
        self.assertNotIn("\u2014", page)  # no em dashes in the page chrome

    def test_nothing_in_a_report_becomes_markup(self):
        md = '<script>alert(1)</script>\n\n[x](javascript:void) <img src=x onerror=alert(1)> **<b>bold</b>**\n'
        page = render_report(md, self.home / "data" / "t" / "report.md", "primary", "t", NOW)
        body = page.split("<article>", 1)[1]
        self.assertNotIn("<script", body)
        self.assertNotIn("<img src=x", body)
        self.assertNotIn('href="javascript', body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertIn('<span class="path" title="javascript:void">x</span>', body)

    def test_images_next_to_the_report_are_embedded_and_others_are_placeholders(self):
        report = self.write("data/t/report.md")
        (report.parent / "preview.png").write_bytes(b"\x89PNG fake")
        (self.home / "data" / "secret.png").write_bytes(b"x")
        md = "![preview](preview.png)\n\n![up](../secret.png) ![far](/etc/a.png) ![web](https://example.com/a.png)\n"
        page = render_report(md, report, "primary", "t", NOW)
        self.assertIn('<img src="data:image/png;base64,iVBORyBmYWtl" alt="preview"', page)
        self.assertIn('image: up <code>../secret.png</code>', page)
        self.assertIn('image: far <code>/etc/a.png</code>', page)
        self.assertIn('image: web <code>https://example.com/a.png</code>', page)


class ExecutorOpenTest(HomeCase):
    def executor(self, live):
        runner = FakeRunner(self.home, allow_writes=live, page_roots=[self.cache, self.home / "data"])
        return runner, IntentExecutor(self.home, runner, dry_run=not live, clock=lambda: NOW, cache_dir=self.cache)

    def test_dry_run_lists_boards_logs_the_open_and_writes_nothing(self):
        self.write("data/widget-pricing/report.md", "# Pricing\n")
        runner, ex = self.executor(live=False)
        target = ex.show_target(decision(self.home))
        with self.assertLogs("helm.bridge.intents", "INFO"):
            self.assertTrue(ex.open(target, decision(self.home)))
        self.assertEqual(runner.calls, [["lavish-axi"]])  # the read only
        self.assertEqual(ex.dry_log, ["lavish-axi %s --reopen --no-gate" % (self.cache / "reports" / "primary-widget-pricing-report.html")])
        self.assertFalse(self.cache.exists())

    def test_live_renders_the_page_then_opens_it_with_lavish(self):
        self.write("data/widget-pricing/report.md", "# Pricing\n\nPick **A**.\n")
        runner, ex = self.executor(live=True)
        before = sorted(p for p in self.home.rglob("*"))
        target = ex.show_target(decision(self.home))
        self.assertTrue(ex.open(target, decision(self.home)))
        page = self.cache / "reports" / "primary-widget-pricing-report.html"
        self.assertIn("Pick <strong>A</strong>.", page.read_text())
        self.assertEqual(runner.calls[-1], ["lavish-axi", str(page), "--reopen", "--no-gate"])
        self.assertEqual(sorted(p for p in self.home.rglob("*")), before)  # nothing written under the home

    def test_live_board_opens_with_open(self):
        sid = "124243bf9534df5d"
        runner, ex = self.executor(live=True)
        runner.lavish = lavish_listing(("/b/index.html", "open", TAILNET % sid))
        cand = decision(self.home, detail="live board %s" % (TAILNET % sid))
        self.assertTrue(ex.open(ex.show_target(cand), cand))
        self.assertEqual(runner.calls, [["lavish-axi"], ["open", "http://127.0.0.1:4387/session/%s" % sid]])

    def test_lavish_unreadable_still_finds_the_report(self):
        self.write("data/widget-pricing/report.md")
        runner, ex = self.executor(live=False)
        runner.lavish = None
        self.assertEqual(ex.show_target(decision(self.home)).what, "report")

    def test_refuses_to_render_under_a_firstmate_home(self):
        self.write("data/widget-pricing/report.md")
        runner, ex = self.executor(live=True)
        ex.cache_dir = self.home / "data" / "helm-cache"
        target = ex.show_target(decision(self.home))
        with self.assertLogs("helm.bridge.intents", "WARNING"):
            self.assertFalse(ex.open(target, decision(self.home)))
        self.assertFalse((self.home / "data" / "helm-cache").exists())
        self.assertEqual(runner.calls, [["lavish-axi"]])

    def test_a_report_deleted_before_it_opens_fails_without_raising(self):
        page = self.write("data/widget-pricing/plan.html")
        runner, ex = self.executor(live=True)
        cand = decision(self.home, detail="plan: data/widget-pricing/plan.html")
        target = ex.show_target(cand)
        page.unlink()
        with self.assertLogs("helm.bridge.intents", "WARNING"):
            self.assertFalse(ex.open(target, cand))

    def test_a_report_too_deep_to_render_fails_without_raising(self):
        self.write("data/widget-pricing/report.md", ">" * 5000 + " deep\n")
        runner, ex = self.executor(live=True)
        cand = decision(self.home)
        with self.assertLogs("helm.bridge.intents", "WARNING"):
            self.assertFalse(ex.open(ex.show_target(cand), cand))

    def test_open_failure_is_reported(self):
        runner, ex = self.executor(live=True)
        runner.open_rc = 1
        cand = decision(self.home, task="alpha-fix", pr_url="https://github.com/example/alpha/pull/12")
        with self.assertLogs("helm.bridge.intents", "WARNING"):
            self.assertFalse(ex.open(ex.show_target(cand), cand))


class ViewerAllowlistTest(HomeCase):
    def test_listing_is_a_read_and_opening_needs_live(self):
        check_allowed(["lavish-axi"], allow_writes=False)
        page = self.write("data/t/board.html")
        for argv in (["open", "http://127.0.0.1:4387/session/0123456789abcdef"],
                     ["open", "https://github.com/example/alpha/pull/12"],
                     ["lavish-axi", str(page), "--reopen", "--no-gate"],
                     ["lavish-axi", str(page)]):
            with self.assertRaises(CommandRefused, msg=argv):
                check_allowed(argv, allow_writes=False, page_roots=[self.home / "data"])
            check_allowed(argv, allow_writes=True, page_roots=[self.home / "data"])

    def test_open_takes_only_a_loopback_board_or_a_github_pr(self):
        for argv in (
            ["open", "http://deck-mac.example.ts.net:4387/session/0123456789abcdef"],
            ["open", "https://evil.example/session/0123456789abcdef"],
            ["open", "http://127.0.0.1:4387/other"],
            ["open", "http://127.0.0.1:4387/session/0123456789abcdef?x=1"],
            ["open", "https://github.com/example/alpha/issues/12"],
            ["open", "https://github.com.evil.example/a/b/pull/1"],
            ["open", "file:///etc/passwd"],
            ["open", "/Applications/Calculator.app"],
            ["open", "-a", "Terminal", "https://github.com/example/alpha/pull/12"],
            ["open", "https://github.com/example/alpha/pull/12", "https://github.com/example/beta/pull/1"],
            ["open"],
            ["/usr/bin/open", "https://github.com/example/alpha/pull/12"],
        ):
            with self.assertRaises(CommandRefused, msg=argv):
                check_allowed(argv, allow_writes=True)
        self.assertFalse(openable_url("http://127.0.0.1:0/session/0123456789abcdef"))
        # The whole argument must match: no trailing newline, no non-ASCII digits.
        self.assertFalse(openable_url("http://127.0.0.1:4387/session/0123456789abcdef\n"))
        self.assertFalse(openable_url("https://github.com/example/alpha/pull/12\n"))
        self.assertFalse(openable_url("http://127.0.0.1:\u0664\u0663\u0668\u0667/session/0123456789abcdef"))
        # urlsplit drops the newline, and the board URL is rebuilt from its checked parts.
        self.assertEqual(loopback_board_url("http://h:4387/session/0123456789abcdef\n"),
                         "http://127.0.0.1:4387/session/0123456789abcdef")

    def test_lavish_axi_opens_only_pages_in_the_allowed_roots(self):
        roots = [self.cache, self.home / "data"]
        self.cache.mkdir()
        ok = self.cache / "reports.html"
        ok.write_text("x")
        check_allowed(["lavish-axi", str(ok)], allow_writes=True, page_roots=roots)
        (self.outside / "x.html").write_text("x")
        self.write("data/.secrets/x.html")
        self.write("data/t/report.md")
        self.write("state/x.html")
        (self.home / "data" / "escape.html").symlink_to(self.outside / "x.html")
        for argv in (
            ["lavish-axi", str(self.outside / "x.html")],
            ["lavish-axi", str(self.home / "data" / ".secrets" / "x.html")],
            ["lavish-axi", str(self.home / "data" / "t" / "report.md")],
            ["lavish-axi", str(self.home / "state" / "x.html")],
            ["lavish-axi", str(self.home / "data" / "escape.html")],
            ["lavish-axi", str(self.home / "data" / "missing.html")],
            ["lavish-axi", "data/t/x.html"],
            ["lavish-axi", str(ok), "--share"],
            ["lavish-axi", str(ok), "--reopen", "--reopen"],
            ["lavish-axi", "poll", str(ok)],
            ["lavish-axi", "share", str(ok)],
            ["lavish-axi", "end", str(ok)],
            ["lavish-axi", "stop"],
            ["/opt/bin/lavish-axi"],
        ):
            with self.assertRaises(CommandRefused, msg=argv):
                check_allowed(argv, allow_writes=True, page_roots=roots)

    def test_runner_refuses_before_spawning(self):
        page = self.write("data/t/board.html")
        with self.assertRaises(CommandRefused):
            Runner(allow_writes=False).run(["open", "https://github.com/example/alpha/pull/12"])
        with self.assertRaises(CommandRefused):
            Runner(allow_writes=True).run(["lavish-axi", str(page)])  # no page roots given
        with self.assertRaises(CommandRefused):
            Runner(allow_writes=True, page_roots=lambda: [self.cache]).run(["lavish-axi", str(page)])


if __name__ == "__main__":
    unittest.main()
