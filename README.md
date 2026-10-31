# agent-social-manager

Give this to your AI agent, say "manage my Instagram", and it does. It sets up the Meta developer app for you, keeps a content calendar, posts on schedule, answers comments and edits your profile.

It's an agent skill (`SKILL.md`) plus one Python file (`ig.py`) with no dependencies. It works with Claude Code, Codex, or any agent that can run shell commands and control a browser.

## Setup

```bash
git clone https://github.com/adarshmishra07/agent-social-manager ~/.claude/skills/instagram-manager
```

Then tell your agent: **"manage my Instagram"**.

It runs `python3 ig.py doctor`, which reports what's missing and what to do next, and works through the list. It creates your Meta app in the browser, connects your account, saves the token, asks your timezone, creates a calendar folder and installs the scheduler. You log in, pass any phone check and click Allow. Nothing else.

You need:
- An Instagram Business or Creator account (free; switching takes a minute in the app).
- A Facebook account to own the Meta developer app. Meta requires one. Your normal account is fine: nothing gets posted to Facebook, and it isn't linked to your Instagram. You don't need a Facebook Page.

For agents other than Claude Code, clone it wherever they load skills from, or point them at `SKILL.md`.

## What it can do

| | how |
|---|---|
| Post images, carousels, reels, stories | Instagram API |
| Location, people tags, collaborators, alt text, reel covers, AI label | Instagram API |
| Schedule posts from a CSV calendar, in your timezone | Instagram API + launchd/cron |
| Read, reply to, hide, delete comments | Instagram API |
| Check and fix media (JPEG conversion, 4:5 crops, reel-safe video) | `validate` + ffmpeg/sips |
| Original or royalty-free music on reels | Mixed into the file with ffmpeg |
| Trending songs from Instagram's library | Agent preps the reel, you add the song in the app (the API can't) |
| Change name, username, bio, picture | Browser (the API can't) |
| Several accounts from one Meta app | `--account shop`, each with its own calendar, timezone and schedule |

## How it works

- **No passwords shared, no server.** You own the Meta app (development mode, so no App Review). The token stays in `~/.config/ig-agent/credentials.json` with mode 600 and refreshes itself.
- **The calendar is a CSV.** One row per post. Your agent writes `draft` rows, you approve them, and they become `scheduled`. `run-due` posts them every 5 minutes. `calendar` renders an HTML view. If you prefer a Google Sheet, the agent can sync one.
- **Timezones are fixed per calendar.** "2026-11-03 18:30" means 18:30 in the zone you chose, even when your laptop is in another country or the clocks change for DST.
- **Local files just work.** Instagram only downloads media from a public URL. `ig.py` opens a temporary Cloudflare tunnel for the minute it takes to publish, and it serves only that post's files. No account needed. Without `cloudflared` it falls back to a free 1-hour file host.
- **Checks before posting.** `validate` rejects files Instagram would reject: fake JPEGs, 3:4 images, wrong video codecs, more than 30 hashtags, a 9 MB image.

## CLI

```
doctor                      setup status and the next step
auth | config --timezone    save a token (stdin), set the calendar timezone
accounts                    list connected accounts (add --account NAME to any command)
init --dir ~/instagram      create content.csv and media/
post --type image --media a.jpg --caption "hi" [--location-id ...]
validate | calendar | run-due [--dry-run]
schedule install|status|remove
media | comments <id> | reply <id> "text" | hide <id> | delete-comment <id>
whoami | limit | refresh
```
Every command prints JSON. Run `python3 ig.py -h` for details.

## Limits

- 100 API posts per 24 hours per account. Extra posts wait for quota instead of failing. API throttling stops the run and says when to retry. Comment replies are spaced 20 s apart.
- Scheduled posts need the computer on. A post missed while it's asleep goes out on the next run.
- The API can't add Instagram's music library, story stickers, or edit or delete posts. `SKILL.md` lists a workaround for each.

## Tests

```bash
python3 -m unittest test_ig.py                       # offline, about 1 second
IG_TEST_TUNNEL=1 python3 -m unittest test_ig.Tunnel  # live tunnel, needs cloudflared
```

MIT license.
