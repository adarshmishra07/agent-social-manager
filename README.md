# agent-social-manager

Let your AI agent run your Instagram. It plans a content calendar, posts on schedule, answers comments and edits your profile.

It's an agent skill (`SKILL.md`) plus one dependency-free Python CLI (`ig.py`). Works with Claude Code, Codex, or any agent that can run shell commands and drive a browser.

## Why this exists

Schedulers like Postiz or Buffer are apps for humans. You have to self-host a stack or pay per seat, and then click through a UI. This is the opposite. Your agent is the UI. You talk to it, and it edits a CSV and calls Instagram's official API.

No passwords are shared. Nothing runs in anyone's cloud. You make your own Meta app in development mode (your agent does the clicking), so there's no App Review and no third party holding your token.

## What it can do

| Task | How |
|---|---|
| Post images, carousels, reels, stories | Official API |
| Schedule posts from a CSV calendar | Official API + launchd/cron |
| Read, reply to, hide, delete comments | Official API |
| Account stats, recent posts, quota | Official API |
| Change name, username, bio, picture | Browser. The API has no endpoint for this |

## Install

```bash
git clone https://github.com/adarshmishra07/agent-social-manager ~/.claude/skills/instagram-manager
brew install cloudflared   # optional but recommended, see "Media hosting"
```

For other agents, clone it wherever they load skills from, or point the agent at `SKILL.md`.

Then tell your agent: "set up Instagram manager for my account". It follows `SKILL.md`, opens the Meta developer site, creates the app, connects your account and saves the token. You only log in and click Allow.

## The calendar

`content.csv`, one row per post:

```csv
id,publish_at,type,caption,media,status,ig_media_id,permalink,error
001,2026-11-03 18:30,image,"Caption here",media/001.jpg,scheduled,,,
002,2026-11-05 12:00,carousel,"Swipe",media/a.jpg|media/b.jpg,draft,,,
```

- `draft` rows are ideas. Only `scheduled` rows get posted.
- `python3 ig.py run-due` posts whatever is due. Run it every 5 minutes from launchd or cron (`SKILL.md` has the exact setup).
- `python3 ig.py calendar` writes `calendar.html` so you can see the plan.
- Prefer a Google Sheet? The agent can edit the Sheet and sync it to the CSV.

## Media hosting

Instagram's API only accepts media from a public URL. It can't take a file from your disk. So `ig.py` does this:

1. If the media is already an `https://` URL, it uses it.
2. If `cloudflared` is installed, it opens a temporary Cloudflare quick tunnel that serves only that post's files. It closes the tunnel after publishing. No account needed.
3. Otherwise it uploads to litterbox.catbox.moe with a 1 hour expiry (a free host with no uptime promise).

Google Drive links don't work. Meta rejects them.

## CLI

```
python3 ig.py auth            # token on stdin
python3 ig.py whoami
python3 ig.py post --type image --media photo.jpg --caption "hi"
python3 ig.py run-due [--csv content.csv] [--dry-run]
python3 ig.py validate | calendar | limit | refresh
python3 ig.py media | comments <media_id> | reply <comment_id> "text"
python3 ig.py hide <comment_id> [--unhide] | delete-comment <comment_id>
```

Every command prints JSON. Errors print `{"error": ...}` and exit 1. The token is stored at `~/.config/ig-agent/credentials.json` (mode 600) and refreshes itself.

## Limits

- Needs an Instagram Business or Creator account. Personal accounts can't use the API.
- 50 API posts per 24 hours. JPEG images only.
- Scheduled posts need a machine that's on. Missed posts go out on the next run.
- The tokens don't expire as long as something posts or refreshes within 60 days.
- Profile edits go through the browser at human pace. Expect Instagram to sometimes ask for verification.

## Tests

```bash
python3 -m unittest test_ig.py                       # offline
IG_TEST_TUNNEL=1 python3 -m unittest test_ig.Tunnel  # live tunnel check, needs cloudflared
```

## License

MIT
