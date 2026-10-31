"""Run: python3 -m unittest test_ig.py"""
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import ig


def row(**kw):
    return {**{k: "" for k in ig.CSV_FIELDS}, **kw}


class DueRows(unittest.TestCase):
    def test_only_scheduled_and_past(self):
        rows = [
            row(id="a", status="scheduled", publish_at="2026-11-01 09:00"),
            row(id="b", status="scheduled", publish_at="2026-11-01 11:00"),  # future
            row(id="c", status="draft", publish_at="2026-11-01 08:00"),      # not approved
            row(id="d", status="posted", publish_at="2026-11-01 08:00"),     # already done
            row(id="e", status="scheduled", publish_at="garbage"),           # invalid, skipped
        ]
        self.assertEqual(ig.due_rows(rows, datetime(2026, 11, 1, 10, 0)), [0])


class MediaKind(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(ig.media_kind("a.JPG"), "image")
        self.assertEqual(ig.media_kind("https://x.com/v.mp4?sig=1"), "video")
        with self.assertRaises(ig.IGError):
            ig.media_kind("a.png")


class Validate(unittest.TestCase):
    def test_reports_problems(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "ok.jpg").write_bytes(b"x")
            rows = [row(id="1", publish_at="2026-11-01 09:00", type="image", status="scheduled", media="ok.jpg"),
                    row(id="2", publish_at="tomorrow", type="gif", status="maybe", media="missing.png")]
            problems = ig.validate_rows(rows, Path(d))
        self.assertFalse([p for p in problems if p.startswith("1:")])
        self.assertEqual(len([p for p in problems if p.startswith("2:")]), 5)


class Publish(unittest.TestCase):
    """Fake the Graph API and check the exact call sequence."""

    def fake_api(self, calls):
        def api(method, path, creds, **params):
            calls.append((method, path, params))
            if path.endswith("/media"):
                return {"id": f"c{len(calls)}"}
            if path.endswith("/media_publish"):
                return {"id": "M1"}
            if params.get("fields") == "permalink":
                return {"permalink": "https://instagram.com/p/x"}
            return {"status_code": "FINISHED"}
        return api

    def test_carousel_flow(self):
        calls = []
        creds = {"user_id": "U", "access_token": "t"}
        urls = ["https://h/a.jpg", "https://h/b.mp4"]
        with mock.patch.object(ig, "api", self.fake_api(calls)):
            res = ig.publish(creds, "carousel", urls, "hi")
        self.assertEqual(res, {"ig_media_id": "M1", "permalink": "https://instagram.com/p/x"})
        creates = [c for c in calls if c[1] == "U/media"]
        self.assertEqual(creates[0][2], {"is_carousel_item": "true", "image_url": urls[0]})
        self.assertEqual(creates[1][2], {"is_carousel_item": "true", "video_url": urls[1], "media_type": "VIDEO"})
        self.assertEqual(creates[2][2]["media_type"], "CAROUSEL")
        self.assertEqual(creates[2][2]["caption"], "hi")
        self.assertEqual(calls[-2][1], "U/media_publish")

    def test_type_mismatch(self):
        with mock.patch.object(ig, "api", self.fake_api([])):
            with self.assertRaises(ig.IGError):
                ig.publish({"user_id": "U"}, "reel", ["https://h/a.jpg"], "")


class RunDue(unittest.TestCase):
    def test_marks_posted_and_failed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "content.csv")
            ig.write_rows(path, [
                row(id="1", status="scheduled", publish_at="2020-01-01 00:00", type="image", media="https://h/a.jpg",
                    caption="multi, line\n\"quoted\""),
                row(id="2", status="scheduled", publish_at="2020-01-01 00:00", type="image", media="https://h/b.jpg"),
            ])
            outcomes = iter([{"ig_media_id": "M1", "permalink": "p"}, ig.IGError("boom")])

            def fake_publish(*a):
                o = next(outcomes)
                if isinstance(o, Exception):
                    raise o
                return o

            with mock.patch.object(ig, "publish", fake_publish), \
                 mock.patch.object(ig, "load_creds", lambda: {}), \
                 mock.patch.object(ig, "maybe_refresh", lambda c: c):
                res = ig.run_due(path)
            rows = ig.read_rows(path)
        self.assertEqual(res["posted"], ["1"])
        self.assertEqual(rows[0]["status"], "posted")
        self.assertEqual(rows[0]["ig_media_id"], "M1")
        self.assertEqual(rows[0]["caption"], "multi, line\n\"quoted\"")
        self.assertEqual(rows[1]["status"], "failed")
        self.assertIn("boom", rows[1]["error"])


class Http(unittest.TestCase):
    def test_http_error_becomes_igerror_without_query_string(self):
        err = ig.HTTPError("https://graph/x?access_token=SECRET", 400, "bad", {}, None)
        err.read = lambda: b'{"error":{"message":"Invalid"}}'
        with mock.patch.object(ig, "urlopen", side_effect=err):
            with self.assertRaises(ig.IGError) as cm:
                ig.http_json("GET", "https://graph/x", params={"access_token": "SECRET"})
        self.assertIn("Invalid", str(cm.exception))
        self.assertNotIn("SECRET", str(cm.exception))

    def test_post_sends_form_body_and_bearer(self):
        seen = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b'{"id": "1"}'

        def fake(req, timeout):
            seen.update(url=req.full_url, data=req.data, auth=req.get_header("Authorization"))
            return Resp()

        with mock.patch.object(ig, "urlopen", fake):
            self.assertEqual(ig.http_json("POST", "https://g/m", "T", {"a": "1", "b": None}), {"id": "1"})
        self.assertEqual(seen, {"url": "https://g/m", "data": b"a=1", "auth": "Bearer T"})


class Refresh(unittest.TestCase):
    def test_skips_fresh_token(self):
        c = {"access_token": "t", "refreshed_at": ig.time.time()}
        with mock.patch.object(ig, "http_json") as h:
            self.assertIs(ig.maybe_refresh(c), c)
        h.assert_not_called()

    def test_refreshes_old_token_and_saves_privately(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(ig, "CREDS", Path(d, "c.json")), \
             mock.patch.object(ig, "http_json", return_value={"access_token": "new", "expires_in": 5184000}):
            c = ig.maybe_refresh({"access_token": "old", "refreshed_at": 0})
            self.assertEqual(c["access_token"], "new")
            self.assertEqual(oct(Path(d, "c.json").stat().st_mode & 0o777), "0o600")


class Cli(unittest.TestCase):
    def test_error_is_json_and_exit_1(self):
        with mock.patch.object(ig, "CREDS", Path("/nonexistent/creds.json")), \
             mock.patch("sys.stdout") as so, self.assertRaises(SystemExit) as cm:
            ig.main(["whoami"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('"error"', "".join(c.args[0] for c in so.write.call_args_list))

    def test_concurrent_run_due_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "content.csv")
            ig.write_rows(path, [])
            with ig.csv_lock(path):
                with self.assertRaises(ig.IGError):
                    ig.run_due(path)


class Calendar(unittest.TestCase):
    def test_escapes_html(self):
        page = ig.render_calendar([row(id="1", publish_at="2026-11-01 09:00", type="image", status="draft",
                                       caption="<script>x</script>", media="a.jpg")])
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;", page)


class Tunnel(unittest.TestCase):
    @unittest.skipUnless(ig.find_cloudflared() and os.environ.get("IG_TEST_TUNNEL"), "set IG_TEST_TUNNEL=1")
    def test_serves_file_publicly(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "x.jpg")
            f.write_bytes(b"\xff\xd8hello")
            with ig.tunnel([str(f)]) as urls:
                with ig.urlopen(urls[str(f)], timeout=30) as r:
                    self.assertEqual(r.read(), b"\xff\xd8hello")


if __name__ == "__main__":
    unittest.main()
