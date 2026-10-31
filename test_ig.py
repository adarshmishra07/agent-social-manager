"""Run: python3 -m unittest test_ig.py"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest import mock

import ig


def row(**kw):
    return {**{k: "" for k in ig.CSV_FIELDS}, **kw}


def fake_jpeg(path, w, h):
    """Smallest file jpeg_size() accepts: SOI, an APP0 segment to skip, then SOF0 with the size."""
    app0 = b"\xff\xe0\x00\x10" + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    Path(path).write_bytes(b"\xff\xd8" + app0 + sof + b"\xff\xd9")


class DueRows(unittest.TestCase):
    def test_only_scheduled_and_past(self):
        rows = [
            row(id="a", status="scheduled", publish_at="2026-11-01 09:00"),
            row(id="b", status="scheduled", publish_at="2026-11-01 11:00"),  # future
            row(id="c", status="draft", publish_at="2026-11-01 08:00"),      # not approved
            row(id="d", status="posted", publish_at="2026-11-01 08:00"),     # already done
            row(id="e", status="scheduled", publish_at="garbage"),           # invalid, skipped
        ]
        tz = ZoneInfo("Asia/Kolkata")
        self.assertEqual(ig.due_rows(rows, datetime(2026, 11, 1, 10, 0, tzinfo=tz), tz), [0])

    def test_explicit_offset_beats_calendar_tz(self):
        tz = ZoneInfo("Asia/Kolkata")
        rows = [row(status="scheduled", publish_at="2026-11-01 09:00Z")]  # 14:30 in Kolkata
        self.assertEqual(ig.due_rows(rows, datetime(2026, 11, 1, 14, 0, tzinfo=tz), tz), [])
        self.assertEqual(ig.due_rows(rows, datetime(2026, 11, 1, 14, 30, tzinfo=tz), tz), [0])

    def test_machine_timezone_does_not_matter(self):
        # Calendar in New York, machine clock read in Tokyo: same instant, same answer.
        ny, tokyo = ZoneInfo("America/New_York"), ZoneInfo("Asia/Tokyo")
        rows = [row(status="scheduled", publish_at="2026-11-01 09:00")]
        now = datetime(2026, 11, 1, 9, 0, tzinfo=ny).astimezone(tokyo)
        self.assertEqual(ig.due_rows(rows, now, ny), [0])
        self.assertEqual(ig.due_rows(rows, now - timedelta(minutes=1), ny), [])

    def test_dst_change(self):
        # US DST ends 2026-11-01 02:00. 09:00 on 2 Nov is 14:00 UTC (EST), not 13:00.
        ny = ZoneInfo("America/New_York")
        rows = [row(status="scheduled", publish_at="2026-11-02 09:00")]
        utc = ZoneInfo("UTC")
        self.assertEqual(ig.due_rows(rows, datetime(2026, 11, 2, 13, 30, tzinfo=utc), ny), [])
        self.assertEqual(ig.due_rows(rows, datetime(2026, 11, 2, 14, 0, tzinfo=utc), ny), [0])


class Timezone(unittest.TestCase):
    def test_parse_formats(self):
        tz = ZoneInfo("Asia/Kolkata")
        self.assertEqual(ig.parse_when("2026-11-01T09:00+05:30", tz), datetime(2026, 11, 1, 9, 0, tzinfo=tz))
        for bad in ("2026-11-01", "tomorrow 9am", "01/11/2026 09:00"):
            with self.assertRaises(ValueError):
                ig.parse_when(bad, tz)

    def test_unknown_tz(self):
        with self.assertRaises(ig.IGError):
            ig.get_tz("Mars/Olympus")


class MediaKind(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(ig.media_kind("a.JPG"), "image")
        self.assertEqual(ig.media_kind("https://x.com/v.mp4?sig=1"), "video")
        with self.assertRaises(ig.IGError):
            ig.media_kind("a.png")


class Jpeg(unittest.TestCase):
    def test_reads_size_and_rejects_fakes(self):
        with tempfile.TemporaryDirectory() as d:
            fake_jpeg(Path(d, "a.jpg"), 1080, 1350)
            Path(d, "png.jpg").write_bytes(b"\x89PNG\r\n\x1a\n")
            self.assertEqual(ig.jpeg_size(Path(d, "a.jpg")), (1080, 1350))
            self.assertIsNone(ig.jpeg_size(Path(d, "png.jpg")))

    def test_real_jpeg_if_sips_available(self):
        import shutil, subprocess
        if not shutil.which("sips"):
            self.skipTest("needs macOS sips")
        with tempfile.TemporaryDirectory() as d:
            pics = [p for p in Path("/System/Library/CoreServices").rglob("*.png")][:1]
            if not pics:
                self.skipTest("no sample image")
            out = Path(d, "x.jpg")
            subprocess.run(["sips", "-s", "format", "jpeg", str(pics[0]), "--out", str(out)], capture_output=True)
            w = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(out)], capture_output=True, text=True)
            nums = [int(l.split()[-1]) for l in w.stdout.splitlines() if "pixel" in l]
            self.assertEqual(ig.jpeg_size(out), tuple(nums))


class Validate(unittest.TestCase):
    def test_media_specs(self):
        with tempfile.TemporaryDirectory() as d:
            fake_jpeg(Path(d, "tall.jpg"), 1080, 1440)   # 3:4, narrower than 4:5
            fake_jpeg(Path(d, "wide.jpg"), 1600, 1000)   # ok ratio (1.6), too wide
            fake_jpeg(Path(d, "sq.jpg"), 1080, 1080)
            Path(d, "png.jpg").write_bytes(b"\x89PNG")
            tz = ZoneInfo("UTC")
            rows = [row(id="1", publish_at="2026-11-02 09:00", type="image", status="draft", media="tall.jpg"),
                    row(id="2", publish_at="2026-11-02 09:00", type="image", status="draft", media="wide.jpg"),
                    row(id="3", publish_at="2026-11-02 09:00", type="image", status="draft", media="png.jpg"),
                    row(id="4", publish_at="2026-11-02 09:00", type="carousel", status="draft", media="sq.jpg|wide.jpg"),
                    row(id="5", publish_at="2026-11-02 09:00", type="story", status="draft", media="sq.jpg",
                        location_id="abc", collaborators="a,b,c,d", alt_text="x", cover="c.jpg",
                        user_tags="bob@x,y", extra="[1]")]
            problems, warnings = ig.validate_rows(rows, Path(d), tz, datetime(2026, 11, 1, tzinfo=tz))
        by = lambda xs, i: " ".join(p for p in xs if p.startswith(f"{i}:"))
        self.assertIn("4:5 to 1.91:1", by(problems, "1"))
        self.assertEqual(by(problems, "2"), "")
        self.assertIn("1440", by(warnings, "2"))
        self.assertIn("not a real JPEG", by(problems, "3"))
        self.assertIn("different ratios", by(warnings, "4"))
        for msg in ("numeric Facebook Page ID", "can't have a location", "max 3 collaborators", "alt_text only",
                    "cover only applies", "user_tags must", "JSON object"):
            self.assertIn(msg, by(problems, "5"))

    def test_reports_problems(self):
        with tempfile.TemporaryDirectory() as d:
            fake_jpeg(Path(d, "ok.jpg"), 1080, 1350)
            with open(Path(d, "big.jpg"), "wb") as f:
                f.truncate(9_000_000)
            tz = ZoneInfo("UTC")
            now = datetime(2026, 11, 1, 8, 0, tzinfo=tz)
            rows = [row(id="1", publish_at="2026-11-01 09:00", type="image", status="scheduled", media="ok.jpg"),
                    row(id="2", publish_at="tomorrow", type="gif", status="maybe", media="missing.png"),
                    row(id="3", publish_at="2026-10-01 09:00", type="reel", status="scheduled", media="ok.jpg"),
                    row(id="3", publish_at="2026-11-02 09:00", type="carousel", status="draft", media="ok.jpg",
                        caption="#a " * 31),
                    row(id="5", publish_at="2026-11-02 09:00", type="image", status="draft", media="big.jpg")]
            problems, _ = ig.validate_rows(rows, Path(d), tz, now)
        by = lambda i: [p for p in problems if p.startswith(f"{i}:")]
        self.assertEqual(by("1"), [])
        self.assertEqual(len(by("2")), 5)
        self.assertTrue(any("more than a day ago" in p for p in by("3")))
        self.assertTrue(any("can't use image" in p for p in by("3")))
        self.assertTrue(any("unique" in p for p in by("3")))
        self.assertTrue(any("30 hashtags" in p for p in by("3")))
        self.assertTrue(any("2 to 20" in p for p in by("3")))
        self.assertTrue(any("limit 8 MB" in p for p in by("5")))


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

    def test_options_reach_the_api(self):
        calls = []
        creds = {"user_id": "U", "access_token": "t"}
        r = row(type="image", location_id="123", collaborators="@ann, bob", user_tags="cara@0.2,0.8|dan",
                alt_text="A red bike", extra='{"is_ai_generated": true}')
        with mock.patch.object(ig, "api", self.fake_api(calls)):
            ig.publish(creds, "image", ["https://h/a.jpg"], "cap", r)
        p = calls[0][2]
        self.assertEqual(p["location_id"], "123")
        self.assertEqual(p["collaborators"], '["ann", "bob"]')
        self.assertEqual(p["alt_text"], "A red bike")
        self.assertEqual(p["is_ai_generated"], "true")
        self.assertEqual(ig.json.loads(p["user_tags"]),
                         [{"username": "cara", "x": 0.2, "y": 0.8}, {"username": "dan", "x": 0.5, "y": 0.5}])

    def test_reel_cover_and_audio_name(self):
        calls = []
        r = row(type="reel", cover="https://h/c.jpg", extra='{"audio_name": "Rainy loop", "share_to_feed": true}')
        with mock.patch.object(ig, "api", self.fake_api(calls)):
            ig.publish({"user_id": "U"}, "reel", ["https://h/v.mp4"], "", r)
        p = calls[0][2]
        self.assertEqual((p["cover_url"], p["audio_name"], p["share_to_feed"]), ("https://h/c.jpg", "Rainy loop", "true"))
        calls.clear()
        with mock.patch.object(ig, "api", self.fake_api(calls)):
            ig.publish({"user_id": "U"}, "reel", ["https://h/v.mp4"], "", row(type="reel", cover="1500"))
        self.assertEqual(calls[0][2]["thumb_offset"], "1500")

    def test_story_drops_unsupported_options(self):
        calls = []
        r = row(type="story", location_id="1", collaborators="a", user_tags="bob")
        with mock.patch.object(ig, "api", self.fake_api(calls)):
            ig.publish({"user_id": "U"}, "story", ["https://h/a.jpg"], "ignored", r)
        p = calls[0][2]
        self.assertNotIn("location_id", p)
        self.assertNotIn("collaborators", p)
        self.assertNotIn("caption", p)
        self.assertEqual(ig.json.loads(p["user_tags"]), [{"username": "bob"}])

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
                 mock.patch.object(ig, "maybe_refresh", lambda c: c), \
                 mock.patch.object(ig, "publish_quota_left", lambda c: 50), \
                 mock.patch.object(ig, "CREDS", Path(d, "none.json")):
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
        with mock.patch.object(ig, "CONFIG_DIR", Path("/nonexistent")), mock.patch.dict(os.environ, {"IG_ACCOUNT": ""}), \
             mock.patch("sys.stdout") as so, self.assertRaises(SystemExit) as cm:
            os.environ.pop("IG_CREDENTIALS", None)
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
                                       caption="<script>x</script>", media="a.jpg")], ZoneInfo("UTC"))
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;", page)


class Schedule(unittest.TestCase):
    def test_refuses_macos_protected_folder(self):
        if sys.platform != "darwin":
            self.skipTest("macOS only")
        with tempfile.TemporaryDirectory(dir=Path.home() / "Documents") as d:
            path = Path(d, "content.csv")
            ig.write_rows(str(path), [])
            with self.assertRaises(ig.IGError) as cm:
                ig.schedule("install", path)
        self.assertIn("Documents", str(cm.exception))

    def test_cron_install_replaces_only_our_line(self):
        state = {"tab": "0 1 * * * backup.sh\n*/5 * * * * old # com.agent-social-manager.rundue\n"}

        def fake_run(cmd, **kw):
            if cmd == ["crontab", "-l"]:
                return mock.Mock(returncode=0, stdout=state["tab"])
            state["tab"] = kw["input"]
            return mock.Mock(returncode=0)

        with mock.patch.object(ig.subprocess, "run", fake_run):
            res = ig.schedule_cron("install", ["python3", "/x y/ig.py", "run-due"], "/l.log")
        lines = state["tab"].splitlines()
        self.assertEqual(lines[0], "0 1 * * * backup.sh")
        self.assertEqual(len(lines), 2)
        self.assertIn("'/x y/ig.py'", lines[1])
        self.assertTrue(res["installed"])


def http_error(code, body, headers=None):
    e = ig.HTTPError("https://graph/x", code, "err", headers or {}, None)
    e.read = lambda: body.encode()
    return e


class OkResp:
    def __init__(self, body=b'{"ok": true}'):
        self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self.body


class RateLimits(unittest.TestCase):
    def test_throttle_codes_raise_ratelimited_with_regain_time(self):
        hdr = {"X-Business-Use-Case-Usage": '{"123": [{"type": "instagram", "estimated_time_to_regain_access": 17}]}'}
        for code, body in ((400, '{"error": {"code": 4, "message": "Application request limit reached"}}'),
                           (400, '{"error": {"code": 80002, "message": "too many calls"}}'),
                           (429, "slow down")):
            with mock.patch.object(ig, "urlopen", side_effect=http_error(code, body, hdr)), \
                 mock.patch.object(ig.time, "sleep") as sl:
                with self.assertRaises(ig.RateLimited) as cm:
                    ig.http_json("GET", "https://g/x")
            self.assertIn("17 min", str(cm.exception))
            sl.assert_not_called()  # never hammer a throttled API

    def test_get_retries_transient_then_succeeds(self):
        effects = [http_error(500, "{}"), http_error(400, '{"error": {"is_transient": true}}'), OkResp()]
        with mock.patch.object(ig, "urlopen", side_effect=effects), mock.patch.object(ig.time, "sleep") as sl:
            self.assertEqual(ig.http_json("GET", "https://g/x"), {"ok": True})
        self.assertEqual([c.args[0] for c in sl.call_args_list], [2, 4])

    def test_post_is_never_retried(self):
        with mock.patch.object(ig, "urlopen", side_effect=[http_error(500, "{}"), OkResp()]) as u, \
             mock.patch.object(ig.time, "sleep"):
            with self.assertRaises(ig.IGError):
                ig.http_json("POST", "https://g/media_publish", "T", {"creation_id": "1"})
        self.assertEqual(u.call_count, 1)

    def test_status_polling_backs_off(self):
        states = iter(["IN_PROGRESS"] * 6 + ["FINISHED"])
        with mock.patch.object(ig, "api", lambda *a, **k: {"status_code": next(states)}), \
             mock.patch.object(ig.time, "sleep") as sl:
            ig.wait_finished({}, "C1")
        self.assertEqual([c.args[0] for c in sl.call_args_list], [3, 6, 12, 24, 48, 60])

    def test_reply_pacing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "CONFIG_DIR", Path(d)), \
             mock.patch.object(ig.time, "sleep") as sl:
            self.assertEqual(ig.pace("reply", 20), 0)
            waited = ig.pace("reply", 20)
        self.assertGreater(waited, 18)
        self.assertEqual(sl.call_count, 1)

    def run_due_with(self, d, n_rows, quota, publish):
        path = os.path.join(d, "content.csv")
        ig.write_rows(path, [row(id=str(i), status="scheduled", publish_at="2020-01-01 00:00", type="image",
                                 media="https://h/a.jpg") for i in range(n_rows)])
        with mock.patch.object(ig, "publish", publish), mock.patch.object(ig, "load_creds", lambda: {}), \
             mock.patch.object(ig, "maybe_refresh", lambda c: c), \
             mock.patch.object(ig, "publish_quota_left", quota), mock.patch.object(ig, "CREDS", Path(d, "none.json")):
            res = ig.run_due(path)
        return res, ig.read_rows(path)

    def test_quota_exhausted_rows_wait_not_fail(self):
        with tempfile.TemporaryDirectory() as d:
            res, rows = self.run_due_with(d, 3, lambda c: 2, lambda *a: {"ig_media_id": "M", "permalink": "p"})
        self.assertEqual((res["posted"], res["waiting"], res["quota_left"]), (["0", "1"], ["2"], 0))
        self.assertEqual(rows[2]["status"], "scheduled")
        self.assertIn("quota", rows[2]["error"])

    def test_rate_limit_mid_run_stops_and_keeps_rows_scheduled(self):
        calls = []

        def publish(*a):
            calls.append(1)
            if len(calls) == 2:
                raise ig.RateLimited("Rate limited")
            return {"ig_media_id": "M", "permalink": "p"}

        with tempfile.TemporaryDirectory() as d:
            res, rows = self.run_due_with(d, 4, lambda c: 50, publish)
        self.assertEqual(len(calls), 2)  # stopped after the throttle
        self.assertEqual(res["posted"], ["0"])
        self.assertEqual(res["waiting"], ["1", "2", "3"])
        self.assertEqual([r["status"] for r in rows], ["posted", "scheduled", "scheduled", "scheduled"])

    def test_throttled_quota_check_posts_nothing(self):
        def boom(c):
            raise ig.RateLimited("Rate limited")
        with tempfile.TemporaryDirectory() as d:
            res, rows = self.run_due_with(d, 2, boom, lambda *a: self.fail("must not publish"))
        self.assertEqual(res["waiting"], ["0", "1"])

    def test_validate_warns_over_50_in_24h(self):
        tz = ZoneInfo("UTC")
        rows = [row(id=str(i), status="scheduled", type="image", media="https://h/a.jpg",
                    publish_at=f"2026-11-02 {i // 60:02d}:{i % 60:02d}") for i in range(101)]
        _, warnings = ig.validate_rows(rows, Path("."), tz, datetime(2026, 11, 1, tzinfo=tz))
        self.assertTrue(any("More than 100" in w for w in warnings))
        _, warnings = ig.validate_rows(rows[:100], Path("."), tz, datetime(2026, 11, 1, tzinfo=tz))
        self.assertFalse(any("More than 100" in w for w in warnings))


class PathSafety(unittest.TestCase):
    def test_calendar_cannot_reach_outside_its_folder(self):
        with tempfile.TemporaryDirectory() as d:
            cal = Path(d, "cal")
            (cal / "media").mkdir(parents=True)
            fake_jpeg(Path(d, "secret.jpg"), 1080, 1350)
            tz = ZoneInfo("UTC")
            rows = [row(id="1", publish_at="2026-11-02 09:00", type="image", status="draft", media="../secret.jpg"),
                    row(id="2", publish_at="2026-11-02 09:00", type="reel", status="draft", media="https://h/v.mp4",
                        cover="/etc/passwd"),
                    row(id="3", publish_at="2026-11-02 09:00", type="reel", status="draft", media="https://h/v.mp4",
                        cover="../secret.jpg")]
            problems, _ = ig.validate_rows(rows, cal, tz, datetime(2026, 11, 1, tzinfo=tz))
            self.assertTrue(any(p.startswith("1:") and "outside the calendar folder" in p for p in problems))
            self.assertTrue(any(p.startswith("2:") and "cover must be a .jpg" in p for p in problems))
            self.assertTrue(any(p.startswith("3:") and "outside the calendar folder" in p for p in problems))

            path = str(cal / "content.csv")
            ig.write_rows(path, [row(id="1", status="scheduled", publish_at="2020-01-01 00:00", type="image",
                                     media="../secret.jpg")])
            with mock.patch.object(ig, "publish", lambda *a: self.fail("must not publish")), \
                 mock.patch.object(ig, "load_creds", lambda: {}), mock.patch.object(ig, "maybe_refresh", lambda c: c), \
                 mock.patch.object(ig, "publish_quota_left", lambda c: 50), \
                 mock.patch.object(ig, "CREDS", Path(d, "none.json")):
                res = ig.run_due(path)
            self.assertIn("outside the calendar folder", res["failed"][0]["error"])

    def test_non_jpeg_cover_refused_before_any_upload(self):
        with mock.patch.object(ig, "public_urls", side_effect=AssertionError("must not upload")):
            with self.assertRaises(ig.IGError):
                ig.publish({"user_id": "U"}, "reel", ["https://h/v.mp4"], "", row(type="reel", cover="/etc/passwd"))


class Accounts(unittest.TestCase):
    def test_each_account_has_its_own_file_and_schedule(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "CONFIG_DIR", Path(d)), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IG_CREDENTIALS", None)
            self.assertEqual(ig.creds_path("default"), Path(d, "credentials.json"))
            self.assertEqual(ig.creds_path("shop-2"), Path(d, "shop-2.json"))
            with self.assertRaises(ig.IGError):
                ig.creds_path("../etc")
        self.assertEqual(ig.schedule_label("default"), ig.SCHEDULE_LABEL)
        self.assertEqual(ig.schedule_label("shop-2"), ig.SCHEDULE_LABEL + ".shop-2")

    def test_account_flag_selects_credentials(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "CONFIG_DIR", Path(d)), \
                mock.patch.dict(os.environ, {}, clear=False), mock.patch("sys.stdout"):
            os.environ.pop("IG_CREDENTIALS", None)
            Path(d, "shop-2.json").write_text('{"access_token": "T2", "user_id": "U2"}')
            seen = []
            with mock.patch.object(ig, "api", lambda m, path, c, **k: seen.append(c["access_token"]) or {}):
                ig.main(["limit", "--account", "shop-2"])
                with self.assertRaises(SystemExit):
                    ig.main(["limit"])  # default account not connected
        self.assertEqual(seen, ["T2"])

    def test_cron_lines_are_per_account(self):
        state = {"tab": ""}

        def fake_run(cmd, **kw):
            if cmd == ["crontab", "-l"]:
                return mock.Mock(returncode=0, stdout=state["tab"])
            state["tab"] = kw["input"]
            return mock.Mock(returncode=0)

        with mock.patch.object(ig.subprocess, "run", fake_run):
            ig.schedule_cron("install", ["a"], "/l", ig.schedule_label("default"))
            ig.schedule_cron("install", ["b"], "/l", ig.schedule_label("shop-2"))
            ig.schedule_cron("remove", [], "/l", ig.schedule_label("default"))
        lines = state["tab"].split()
        self.assertIn("b", lines)
        self.assertNotIn("a", lines)


class Notes(unittest.TestCase):
    def test_notes_are_saved_and_shown(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "CONFIG_DIR", Path(d)), \
             mock.patch("sys.stdout"):
            for i in range(12):
                ig.main(["note", f"lesson  {i}\nsecond line"])
            ig.main(["note", "other account lesson", "--account", "shop"])
            with self.assertRaises(SystemExit):
                ig.main(["note", "x" * 301])
            notes = ig.recent_notes()
        self.assertEqual(len(notes), 10)
        self.assertTrue(notes[-1].endswith("[default] lesson 11 second line"))
        self.assertFalse(any("other account" in n for n in notes))

    def test_config_before_auth_then_auth_keeps_it(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "CONFIG_DIR", Path(d)), \
             mock.patch.dict(os.environ, {"IG_TOKEN": "T"}), mock.patch("sys.stdout"):
            os.environ.pop("IG_CREDENTIALS", None)
            ig.main(["config", "--timezone", "Europe/London"])
            with mock.patch.object(ig, "http_json", side_effect=[{"user_id": "U", "username": "u"},
                                                                 {"access_token": "T2", "expires_in": 100}]):
                ig.main(["auth"])
            c = ig.json.loads(Path(d, "credentials.json").read_text())
        self.assertEqual((c["timezone"], c["timezone_confirmed"], c["access_token"]), ("Europe/London", True, "T2"))


class UnifiedLogin(unittest.TestCase):
    def test_facebook_token_needs_ig_user_id_and_uses_facebook_host(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "CONFIG_DIR", Path(d)), \
             mock.patch.dict(os.environ, {"IG_TOKEN": "EAAtest"}), mock.patch("sys.stdout"):
            os.environ.pop("IG_CREDENTIALS", None)
            with self.assertRaises(SystemExit):
                ig.main(["auth"])  # no --ig-user-id
            seen = []

            def fake_http(method, url, token=None, params=None):
                seen.append(url)
                return {"id": "1784", "username": "pale"}

            with mock.patch.object(ig, "http_json", fake_http):
                ig.main(["auth", "--ig-user-id", "1784"])
                c = ig.json.loads(Path(d, "credentials.json").read_text())
                self.assertEqual((c["login"], c["user_id"], c["username"]), ("facebook", "1784", "pale"))
                self.assertIs(ig.maybe_refresh(c, force=True), c)  # never refreshes
                ig.main(["limit"])
        self.assertTrue(all(u.startswith("https://graph.facebook.com/") for u in seen))
        self.assertTrue(seen[-1].endswith("/1784/content_publishing_limit"))

    def test_instagram_token_keeps_instagram_host(self):
        self.assertEqual(ig.graph_base({"login": "instagram"}), ig.GRAPH)
        self.assertEqual(ig.graph_base({}), ig.GRAPH)  # creds saved before this field existed
        self.assertEqual(ig.token_login("IGAAxyz"), "instagram")


class E2EFixes(unittest.TestCase):
    def test_schedule_refuses_temp_folders(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "content.csv")
            ig.write_rows(str(path), [])
            with self.assertRaises(ig.IGError) as cm:
                ig.schedule("install", path)
        self.assertIn("temporary folder", str(cm.exception))

    def test_calendar_lands_next_to_csv(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("sys.stdout"), \
             mock.patch.object(ig, "CONFIG_DIR", Path(d, "cfg")):
            path = Path(d, "cal", "content.csv")
            path.parent.mkdir()
            ig.write_rows(str(path), [])
            ig.main(["calendar", "--csv", str(path)])
            self.assertTrue(Path(d, "cal", "calendar.html").exists())

    def test_publish_progress_goes_to_stderr_only(self):
        api = Publish.fake_api(None, [])
        with mock.patch.object(ig, "api", api), mock.patch("sys.stderr") as err, mock.patch("sys.stdout") as so:
            ig.publish({"user_id": "U"}, "image", ["https://h/a.jpg"], "")
        self.assertIn("published", "".join(c.args[0] for c in err.write.call_args_list))
        so.write.assert_not_called()


class NextPost(unittest.TestCase):
    def test_next_scheduled_row(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "get_tz", lambda: ZoneInfo("UTC")):
            path = Path(d, "content.csv")
            ig.write_rows(str(path), [row(id="a", status="draft", publish_at="2026-11-01 08:00"),
                                      row(id="b", status="scheduled", publish_at="2026-11-03 09:00"),
                                      row(id="c", status="scheduled", publish_at="2026-11-02 09:00")])
            self.assertEqual(ig.next_post(path), {"id": "c", "at": "2026-11-02 09:00 UTC"})


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
