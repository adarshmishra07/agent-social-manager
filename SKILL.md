---
name: instagram-manager
description: Run the user's Instagram for them. Sets up their Meta developer app, plans a content calendar, publishes images, carousels, reels and stories on schedule, answers comments, and edits the profile. Use when the user says anything like "manage my Instagram", or wants to post, schedule, plan content, reply to comments or change their bio/name/picture.
---

# Instagram manager

You run the user's Instagram. They should never have to learn Meta's developer setup: you drive the browser. Stop only for steps that need a human: logging in, 2FA or phone checks, and clicking "Allow".

The tool is `python3 ig.py <command>` in this skill's folder. It needs Python 3.10+ and nothing else. Every command prints JSON, and errors print `{"error": ...}` and exit 1. `python3 ig.py -h` lists the commands.

## Start here, every time

```
python3 ig.py doctor --csv <path to content.csv>
```
It checks everything and prints `next_step` (exit code 1 until ready). Do that step, then run `doctor` again. When `ready` is true, the account is fully managed. Offline steps (folder, tools, timezone question) can happen while you wait for the user to log in.

## 1. One-time setup (you do it in the browser)

Use whatever browser control you have (Claude in Chrome, Playwright, computer use). Meta redesigns these pages often, so read each page instead of trusting exact button names.

1. **Professional account.** The account must be Business or Creator. If it's personal, the user switches it in the Instagram app: Settings > Account type and tools > Switch to professional account. Creator suits most people. A Facebook Page is not needed.
2. **Developer account.** Open https://developers.facebook.com, click Login, then "Continue with Facebook" (not "Managed Meta Account"). The user logs in to Facebook. If the user isn't registered as a developer yet, click "Get started" and finish it. Meta may ask the user to verify a phone number or email.
3. **Create the app.** My Apps > Create app. Name it "<username> manager". For the use case, choose the one about managing messaging and content on Instagram. If asked for an app type, choose Business. Skip the business portfolio if you're allowed to.
4. **Connect the account and get a token.** In the app, go to Instagram > API setup with Instagram login > Generate access tokens > Add account. The user logs in to Instagram and clicks Allow. Then click "Generate token" next to the account and copy it. If Meta says the account has to accept a tester invite, open https://www.instagram.com/accounts/manage_access/ and accept it under "Tester invites".
5. **Save it.** Never put the token on a command line, because it ends up in shell history:
   ```
   printf %s "$TOKEN" | python3 ig.py auth
   ```
   The app stays in development mode. That's correct: it only serves this one account, so it never needs App Review.
6. **Timezone.** `auth` saves the machine's timezone. Ask the user which timezone the posting times should follow (usually where their audience is), and set it: `python3 ig.py config --timezone Asia/Kolkata`. Calendar times stay in that zone even when the user travels.
7. **Folder.** `python3 ig.py init --dir ~/instagram` creates `content.csv` and `media/`. On macOS, don't use Desktop, Documents or Downloads: the system blocks background jobs from reading them.
8. **Tools.** `brew install cloudflared ffmpeg`, or the Linux equivalent. You need cloudflared to post local files reliably (see Media hosting) and ffmpeg to check, fix and add music to videos.
9. **Schedule.** `python3 ig.py schedule install --csv ~/instagram/content.csv` runs `run-due` every 5 minutes, using launchd on macOS and cron on Linux. `schedule status` and `schedule remove` do what they say.

The token lasts 60 days. `post`, `run-due` and `doctor` refresh it once it's a week old, so it never expires while something runs at least every ~50 days. If it does expire, repeat steps 4 and 5.

## 2. The content calendar

`content.csv` is the source of truth. One row per post:

| column | what goes in it |
|---|---|
| id | short unique id |
| publish_at | `YYYY-MM-DD HH:MM` in the configured timezone. Add `+05:30` or `Z` to pin a different zone |
| type | `image`, `carousel`, `reel`, `story` |
| caption | max 2200 chars, 30 hashtags, 20 @mentions. Ignored on stories |
| media | file paths relative to the CSV, or https URLs, separated by `\|`. A carousel takes 2 to 20, mixed images and videos |
| location_id | numeric Facebook Page ID of a place (see Location). Not on stories |
| collaborators | up to 3 usernames, comma separated. They get an invite to co-author. Not on stories |
| user_tags | `name@x,y` separated by `\|`, where x,y run from 0 to 1 from the top-left (default 0.5,0.5). Positions are ignored on video. In a carousel, tags go on the first image |
| alt_text | image description for screen readers and search. In a carousel, one per image separated by `\|` |
| cover | reels only: a cover image path or URL, or a number of milliseconds to use that frame |
| extra | JSON for any other API field, e.g. `{"audio_name": "Rainy loop", "share_to_feed": true, "is_ai_generated": true}` |
| status | `draft` (your idea), `scheduled` (approved, will post), `manual` (user posts it from the phone, see Music), `posted`, `failed` |
| ig_media_id, permalink, error | written by the tool. Leave them empty |

Rules:
- New ideas go in as `draft`. Only switch a row to `scheduled` after the user approves it, unless they told you to post without asking.
- After every edit, run `python3 ig.py validate`. `problems` block posting. `warnings` are advice.
- `python3 ig.py calendar` writes `calendar.html` for the user. Regenerate it after edits.
- To retry a failed row, read its `error`, fix the cause, and set it back to `scheduled`.
- To post right away: `python3 ig.py post --type image --media a.jpg --caption "..."`. All the column options exist as flags, like `--location-id` and `--alt-text`.
- **Google Sheets:** if the user prefers a Sheet and you have a Sheets connector, they can edit the Sheet. Sync it into `content.csv` before posting times and copy the status columns back after. The scheduler only reads the CSV, because it runs when you aren't there.

Before you write any posts, read `references/post-playbook.md`. It covers sizes, hooks, captions, hashtags and cadence.

## 3. Media: sizes, formats, fixes

| format | best size | the API accepts |
|---|---|---|
| Feed image / carousel | 1080x1350 (4:5) | JPEG only, ratio 4:5 to 1.91:1, 320-1440 px wide, 8 MB max |
| Reel | 1080x1920 (9:16) | MP4/MOV, H.264 or HEVC, AAC audio, 23-60 fps, 3 s to 15 min, 300 MB max |
| Story | 1080x1920 (9:16) | JPEG image, or a 3-60 s video up to 100 MB |

The profile grid now shows posts at 3:4, but the API rejects 3:4 (1080x1440) images. Post 4:5 and keep the subject in the middle so the grid crop doesn't cut it. All carousel slides are cropped to the first slide's ratio, so give them the same size.

Fixes. These use macOS `sips`, or ffmpeg on any OS:
```
sips -s format jpeg in.png --out out.jpg                     # PNG/HEIC/WebP to JPEG
sips -Z 1440 in.jpg                                          # cap the longest side
sips -c 1350 1080 in.jpg --out out.jpg                       # center-crop to 4:5
ffmpeg -i in.png -q:v 2 out.jpg                              # convert anything to JPEG
ffmpeg -i in.jpg -vf "crop='min(iw,ih*4/5)':'min(ih,iw*5/4)',scale=1080:1350" -q:v 2 out.jpg   # 4:5 crop
ffmpeg -i in.mov -c:v libx264 -crf 20 -preset slow -pix_fmt yuv420p -r 30 \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" \
  -c:a aac -b:a 128k -ar 48000 -movflags +faststart out.mp4  # reel-safe video
ffmpeg -i in.mp4 -c:v libx264 -crf 26 -c:a aac -b:a 128k -movflags +faststart smaller.mp4      # shrink file size
```

**Media hosting.** Instagram downloads media from a public URL. It can't take a file from disk. When cloudflared is installed, `ig.py` opens a temporary Cloudflare tunnel that serves only that post's files until Instagram finishes downloading them, then closes it. Without cloudflared it uploads to litterbox.catbox.moe, a free host where files expire after 1 hour (less reliable). An `https://` link in the media column is used as is. Google Drive links don't work: Meta rejects them.

## 4. Music

The API can't attach songs from Instagram's music library. Meta only offers that with Facebook Login and a linked Page, and this tool uses Instagram Login. You also can't add music after posting. So pick a route per reel:

1. **Original or royalty-free audio (fully automatic).** Mix it into the file and name the sound:
   ```
   ffmpeg -i video.mp4 -i track.mp3 -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k -shortest out.mp4
   ffmpeg -i video.mp4 -i track.mp3 -filter_complex "[0:a]volume=1[a0];[1:a]volume=0.25[a1];[a0][a1]amix=inputs=2:duration=first[a]" -map 0:v -map "[a]" -c:v copy -c:a aac out.mp4   # keep voice, music underneath
   ```
   Then set `extra` to `{"audio_name": "<a good name>"}`. The name can be set only once, and other creators can reuse the sound under that name. Free sources: YouTube Audio Library, Pixabay Music, or the user's own recordings. Check each license.
2. **A trending song (needs the phone).** Find what's trending in the user's niche: search the web, and ask the user to check the trending audio list in Instagram's Professional Dashboard or the arrow next to sounds in the Reels feed. Edit the video to that song's beat with no audio (or quiet audio), and save it with the caption ready. Set the row's status to `manual` with the song name in `extra` as `{"song": "..."}`. Then tell the user to open Instagram, pick the video, add the song and paste the caption. `run-due` skips `manual` rows.
3. **Never** mix copyrighted songs into the file. Instagram mutes or blocks those reels and can penalize the account.

## 5. Location

`location_id` is the ID of a Facebook Page tied to a physical place (a business, a landmark or a city page). With Instagram Login there's no search API, so find it in the browser: open the place's Facebook page. The numeric ID shows in the URL (`profile.php?id=123...`) or under About > Page transparency. If a page has no address, the post fails with `INVALID_LOCATION_ID`. Pick a page that has one, or post without a location.

## 6. Comments

```
python3 ig.py media --limit 10            # recent posts with comment counts
python3 ig.py comments <media_id>         # comments with replies
python3 ig.py reply <comment_id> "text"
python3 ig.py hide <comment_id>           # --unhide to undo
python3 ig.py delete-comment <comment_id> # only on the user's own posts
```
Write replies in the user's voice. Show drafts first unless they told you to reply on your own. Hide spam and hate instead of replying.

## 7. Several accounts

One Meta app can manage several Instagram accounts. Don't create a second app.

1. In the same app, go to Instagram > API setup with Instagram login > Add account. The user logs in to the other Instagram account (log out of the first one in that browser, or use a private window). Generate that account's token.
2. Pick a short name for each account (`shop`, `studio`) and pass `--account <name>` to every command. Setting `IG_ACCOUNT=<name>` does the same:
   ```
   printf %s "$TOKEN" | python3 ig.py auth --account studio
   python3 ig.py config --account studio --timezone Europe/London
   python3 ig.py init --dir ~/instagram-studio
   python3 ig.py schedule install --account studio --csv ~/instagram-studio/content.csv
   python3 ig.py doctor --account studio --csv ~/instagram-studio/content.csv
   ```
3. Each account has its own token, timezone, calendar folder and schedule job. `python3 ig.py accounts` lists them. The first account you connect without `--account` is called `default`.

Before every post or reply, say which account you're acting on. Never mix calendars between accounts.

## 8. Profile, and things the API can't do

These go through the browser at instagram.com, one at a time, at a human pace. Never script logins or loop these edits.

| task | where |
|---|---|
| Bio, website, profile picture | https://www.instagram.com/accounts/edit/ |
| Name, username | Accounts Center (linked from the edit page). The name can change twice per 14 days. A username change frees the old one for anyone to take |
| Edit a caption, or delete or archive a post | Open the post > "..." menu |
| Story stickers (links, polls, music) | Instagram app only. Bake text into the image, or hand it to the user |
| Shopping tags, filters, drafts | Instagram app only |

Confirm exact values with the user before saving. Check the result with `python3 ig.py whoami`.

## Rate limits

Instagram throttles at several levels, and the tool handles each one:

| limit | what ig.py does | what you do |
|---|---|---|
| 50 published posts per rolling 24h per account (a carousel counts once) | `run-due` checks the quota first. Rows over the limit stay `scheduled` with `error: waiting: ...` and go out on a later run. `validate` warns when more than 50 fall within 24h | Spread posts out. `ig.py limit` shows usage |
| API call throttling (HTTP 429, error codes 4, 17, 32, 613, 80002) | Stops immediately with a `Rate limited` error saying when access returns, and never retries in a loop. In `run-due`, unposted rows stay `scheduled` | Wait for the time in the error. Don't rerun commands to "push through" |
| Temporary Meta errors (5xx, `is_transient`) | Retries reads twice with backoff. Never retries a publish, to avoid double posts | If a publish fails this way, check `ig.py media` before retrying |
| Comment replies | `reply` waits at least 20 s since the last reply on that account | Reply to a batch of comments at most once an hour, write a different reply each time, and skip replying to every single emoji |
| Polling | Container status checks back off from 3 s to 60 s | Check comments every 30 to 60 minutes at most, not in a tight loop |

Instagram also blocks actions that look automated (many replies, follows or profile edits in a short time). These blocks aren't in the API docs and can last hours or days, so pace yourself like a busy human would.

## Troubleshooting

| error | meaning and fix |
|---|---|
| `Media download has failed` | The URL wasn't public or wasn't a raw file. Use a local file (tunnel) or a direct https link |
| `Only photo or video can be accepted` | Not a real JPEG, or the URL returned a web page. Convert the file |
| `The aspect ratio is not supported` | Crop to 4:5 to 1.91:1 (see section 3) |
| Container `ERROR` on a video | Wrong codec, length or ratio. Run it through the reel-safe ffmpeg command |
| `INVALID_LOCATION_ID` | That Page has no address. See Location |
| code 190 / `OAuthException` | The token expired or was revoked. Repeat setup steps 4 and 5 |
| `Another run-due is already running` | Normal. The previous run is still posting |
| `Rate limited by Instagram` | See Rate limits. Wait for the time it gives |
| `outside the calendar folder` | Scheduled posts only use files inside the calendar folder. Copy the file into `media/` |
