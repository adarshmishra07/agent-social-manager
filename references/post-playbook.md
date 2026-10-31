# Post playbook

What makes an Instagram post do well, as of late 2026. This is a mix of Meta's specs and widely shared creator advice. Meta doesn't publish its ranking, so treat the advice as defaults to test against the user's own stats, not as rules.

## Pick the format for the goal

| goal | format | why |
|---|---|---|
| Reach new people | Reel | Reels get shown to people who don't follow you |
| Saves and shares (teaching, lists, before/after) | Carousel | People swipe back through it and save it |
| A strong single image (product, announcement) | Image at 4:5 | It takes up the most room in the feed |
| Daily presence, behind the scenes, polls | Story | Followers only, gone in 24h, low effort |

A common mix is 3-4 reels and 2-3 carousels a week, plus stories most days. Keep a pace the user can sustain: two good posts beat five rushed ones.

## Sizes

- Feed: 1080x1350 (4:5). The grid shows the middle 3:4, so keep faces and text away from the left and right edges.
- Reels and stories: 1080x1920 (9:16). Keep text out of the top ~250 px and bottom ~350 px, where Instagram puts the username, caption and buttons.
- Reel cover: 1080x1920 with the subject in the middle. It shows as 3:4 on the grid.

## Reels

- The first 1-3 seconds decide everything. Open with the result, a bold claim, or movement. Don't open with a logo or "hey guys".
- Put text on screen. Many people watch with the sound off.
- Length: 7-15 s for trends and quick hits, 30-90 s for teaching. Cut every pause.
- Post original video. Instagram has said it favors original content, so don't repost other people's clips or videos with another app's watermark.
- A sound helps reach. See the Music section in SKILL.md for what can be automated.

## Carousels

- Slide 1 is the hook, like a headline: "5 mistakes that…", or the finished result.
- One idea per slide, big text, the same layout throughout.
- The last slide asks for an action: save this, share it with a friend, comment a word.

## Captions

- Only the first line shows before "more", so make it the hook.
- Use the words people would search for. Instagram search reads captions, so "easy vegan dinner recipe" beats "yum 😋".
- End with one clear ask: a question to answer, "save for later", or "send to someone who…".
- Hashtags: 3-5 specific ones (#veganmealprep, not #food). The API rejects posts with more than 30.
- Write like the user talks. Avoid generic AI phrasing: no "Unlock the secrets of…", no "Elevate your…", no stack of emojis.

## Alt text, tags, location, collaborators

- Alt text: describe what's in the image in plain words. It helps blind users and search.
- Tag the people and brands in the photo (`user_tags`), and add `collaborators` when another account co-created the post. Their followers see it too.
- Add a location when place matters, like a local business, an event or travel.

## When to post

Use the account's own stats: the Instagram app's Professional Dashboard shows when followers are online. Without data, start with weekday evenings in the audience's timezone, then adjust. Answer comments in the first hour.

## Before scheduling, check

- [ ] `ig.py validate` shows no problems
- [ ] The hook works in the first line or first second
- [ ] Captions and on-screen text are proofread, and no placeholder text remains
- [ ] The music route is decided (see SKILL.md)
- [ ] The user has approved it, or told you to post without asking
