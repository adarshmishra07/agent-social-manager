---
name: instagram-manager
description: Manage the user's Instagram end to end. Set up their Meta developer app for them, plan a content calendar, publish on schedule, reply to and moderate comments, and edit their profile. Use when the user wants to post, schedule, plan content, handle comments, or change anything on their Instagram.
---

# Instagram manager

You run the user's Instagram for them. The user should not have to learn anything about Meta's developer setup: you drive it. Only stop for things Meta requires a human for: logging in, 2FA or phone verification, clicking "Allow".

Tool: `python3 ig.py <command>` in this skill's folder. Stdlib only, Python 3.10+. Every command prints JSON; errors print `{"error": ...}` and exit 1. Run `python3 ig.py -h` for the full list.

## 0. Check state first

Run `python3 ig.py whoami`. If it works, skip to section 2.

## 1. One-time setup (you do this, in the browser)

Use whatever browser automation you have (Claude in Chrome, Playwright, computer use). Use the user's own browser profile so they are already logged in where possible. Meta's UI changes often: read the page, don't rely on exact button names below.

1. **Professional account.** Instagram must be a Business or Creator account (`whoami` later shows `account_type`). If it is personal, walk the user through: Instagram app > Settings > Account type and tools > Switch to professional account. Creator is fine for most people. A Facebook Page is NOT needed.
2. **Developer account.** Go to https://developers.facebook.com. If the user is not registered as a developer, click "Get started" and finish registration. Ask the user to complete any phone or email verification.
3. **Create the app.** My Apps > Create app. Name it something like "<username> manager". When asked for a use case, pick the one for managing messaging and content on Instagram. If asked for an app type, pick Business. Skip connecting a business portfolio if allowed.
4. **Connect the account and get a token.** In the app: Instagram > API setup with Instagram login > "Generate access tokens" > Add account. The user logs in to Instagram and clicks Allow. Then click "Generate token" next to the account and copy it. If Meta says the account must accept a tester invite, open https://www.instagram.com/accounts/manage_access/ and accept it under "Tester invites".
5. **Save it.** Never put the token in a command line argument (it lands in shell history):
   ```
   printf %s "$TOKEN" | python3 ig.py auth
   ```
   Then `python3 ig.py whoami` must return the username. The app stays in development mode, which is correct: it only needs to work for this one account, so no App Review.
6. **Media hosting.** Instagram downloads media from a public URL; it cannot take local files. Install `cloudflared` (`brew install cloudflared`, or the user's package manager). The CLI then opens a temporary tunnel serving only that post's files for the minute it takes to publish, then closes it. No account needed. Without cloudflared it falls back to litterbox.catbox.moe (1 hour expiry, less reliable). If a media cell is already an `https://` URL it is used as is.

Token lifetime is 60 days. `run-due` and `post` refresh it automatically once it is a week old. As long as something posts at least every ~50 days it never expires. If it does, redo step 4-5.

## 2. Content calendar

`content.csv` is the source of truth (copy `templates/content.csv` to the user's working folder to start). Columns:

| column | meaning |
|---|---|
| id | any unique short id |
| publish_at | `YYYY-MM-DD HH:MM`, local time of the machine that runs `run-due` |
| type | `image`, `carousel`, `reel`, `story` |
| caption | max 2200 chars, hashtags inline. Ignored for stories |
| media | file paths relative to the CSV, or https URLs, separated by `|` |
| status | `draft` (you proposed it), `scheduled` (user approved, will post), `posted`, `failed` |
| ig_media_id, permalink, error | written by the tool, leave empty |

Rules:
- New ideas go in as `draft`. Only flip to `scheduled` after the user approves, unless they told you to post without asking.
- Images must be JPEG. Convert others first (macOS: `sips -s format jpeg in.png --out out.jpg`). Instagram prefers 4:5 (1080x1350) or 1:1 for feed, 9:16 for reels and stories. Carousels are cropped to the first item's ratio, 2 to 20 items.
- Max 50 posts per 24h (`python3 ig.py limit` shows usage).
- After every edit run `python3 ig.py validate` and fix what it reports.
- `python3 ig.py calendar` writes `calendar.html` for the user to look at. Regenerate after edits.
- To retry a failed row, read its `error`, fix the cause, set status back to `scheduled`.

**Google Sheets:** if the user prefers a Sheet and you have a Sheets connector, use it as the editing surface, but sync it into `content.csv` before scheduled runs and copy back the status/permalink columns after. The scheduler only reads the CSV because it runs without you.

## 3. Posting on schedule

Posting needs a machine that is on. Set up a job that runs every 5 minutes:

macOS (launchd, survives reboots): write `~/Library/LaunchAgents/com.ig-agent.rundue.plist` with `ProgramArguments` = `/usr/bin/python3 /ABS/PATH/ig.py run-due --csv /ABS/PATH/content.csv`, `StartInterval` = 300, `StandardOutPath`/`StandardErrorPath` = `/ABS/PATH/ig.log`, and an `EnvironmentVariables` PATH that includes `/opt/homebrew/bin` (for cloudflared). Load it with `launchctl load -w <plist>`.

Linux: `*/5 * * * * cd /ABS/PATH && PATH=/usr/local/bin:/usr/bin:/bin python3 ig.py run-due --csv content.csv >> ig.log 2>&1`

Overlapping runs are safe (file lock). A post that was missed while the machine slept goes out on the next run.

Post right now instead: `python3 ig.py post --type image --media "a.jpg" --caption "..."`

## 4. Comments

```
python3 ig.py media --limit 10            # recent posts with comment counts
python3 ig.py comments <media_id>         # comments plus replies
python3 ig.py reply <comment_id> "text"
python3 ig.py hide <comment_id>           # --unhide to undo
python3 ig.py delete-comment <comment_id> # only on comments on the user's own posts
```
Match the user's voice. Show drafted replies to the user first unless they told you to reply on their own. Never reply to spam or hate: hide it.

## 5. Profile (name, username, bio, picture, link)

The API cannot edit the profile. Use the browser: https://www.instagram.com/accounts/edit/ for bio, website, picture. Name and username live in Accounts Center (linked from that page). Rules:
- Always confirm the exact new value with the user before saving. A username change frees the old one for anyone to take.
- Instagram limits name changes (twice per 14 days) and may ask for verification. Hand that to the user.
- Do it at human pace, one change at a time. Never script logins or loop these edits.
- Check the result with `python3 ig.py whoami`.

## Troubleshooting

- `Media download has failed`: the URL was not public or not a raw file. Use local files (tunnel) or a direct https URL.
- `Only photo or video can be accepted`: image was not JPEG, or the URL returned HTML.
- `OAuthException` / code 190: token expired or revoked. Redo setup steps 4-5.
- Container `ERROR`: usually bad aspect ratio or video codec. Reels: H.264 MP4, 9:16, 3s to 15 min.
