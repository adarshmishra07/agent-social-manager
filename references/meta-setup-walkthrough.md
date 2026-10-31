# Meta setup walkthrough (verified 2026-10-31)

The exact screens and buttons seen in one real end-to-end run on a newer app ("Unified login"). Meta changes these often. When a screen differs, adapt toward the goal in SKILL.md and save what you saw with `ig.py note`.

Legend: **[user]** = only the user can do it (credentials, codes). **[approve]** = explain, ask, then click yourself.

## Developer account

1. developers.facebook.com, header link **"Login"**, which goes to "Log in to Meta for Developers".
2. **"Continue with Facebook"** (not "Managed Meta Account"), then "Log in to Facebook". **[user]**
3. Not yet a developer: the header shows **"Get Started"** instead of "My Apps", and /apps/ silently redirects to the home page. **[approve]** Click "Get Started", which opens "Create a Meta for Developers account" with the steps Register > Verify account **[user: code]** > Contact info > About you. The first screen says "By proceeding, you agree to the Meta Platform Terms and Developer Policies".

## Create the app

"Apps" page > **"Create App"** > wizard "Create an app":

| step | what to do |
|---|---|
| App details | "App name" (max 30): `<username> manager`. "App contact email" is pre-filled |
| Use cases | filter **"Content management"** (not in "Featured") > tick **"Manage messaging & content on Instagram"** |
| Business | **"I don't want to connect a business portfolio yet."** Some portfolios show greyed out here but are selectable later |
| Requirements | "No requirements identified" > Next |
| Overview | **[approve]** "Create app" (the screen carries the Platform Terms line) |

## Business portfolio

App Dashboard > card "App customization and requirements" > **"Customize the Manage messaging & content on Instagram use case"**. Left menu: dropdown "Instagram API" > "Permissions and features", **"API setup with Unified login"**, "API setup with Facebook login".

Banners seen:
- "API setup with Instagram login is not available for newer apps. Your app uses API setup with Unified login instead."
- "Business portfolio selection is mandatory to use the Instagram API setup with Unified login."

**"+ Business portfolio"** opens the "Business portfolio" dialog: a list with Verified/Unverified labels, the link "Create a new business portfolio", and "Enter business ID", "Close", **"Connect"**. Wait about 2 s after it opens; earlier clicks get ignored.
- At the cap: "Unable to create new Meta Business Suite account. You've reached the limit..." Deleting a portfolio doesn't free a slot right away (it stays listed while pending deletion). Ask the user which existing one to connect.
- **[approve]** "Connect". Afterwards the URL gains `&business_id=...`, and the page says "Welcome to the Instagram API" with steps 1-4.

## Configuration (step "1. Configure your app")

"No compatible configurations found." > **"Create new configuration"** opens the fixed template "Confirm login configuration details":
- Name "Instagram API (unified login)", variation General
- "System-user access token", "Token will never expire"
- Assets: Instagram accounts, Ad accounts
- Permissions: ads_management, ads_read, instagram_basic, instagram_content_publish, instagram_manage_comments, instagram_manage_messages

**[approve]** "Create from template". The result shows "Instagram Login Compatible", a "Configuration ID", and "Selected". The redirect URL and login URL fields aren't needed for the token.

## Instagram tester (step "2. Generate access tokens")

Collapsed: open it with **"See more"**. Clicking the heading doesn't expand it.

1. **"Add account"** opens "Add an Instagram account" ("Tokens can only be generated for public Instagram accounts.") > "Continue".
2. That opens "Add people to your app". **[approve]** Select **"Instagram Tester"** under "Additional roles for this app", type the username, **pick it from the dropdown** (free text gives "Form can't be saved"), then "Add".
3. App roles > Roles shows the account as "Instagram Tester", status **"Pending"**. The "Testers (0 of 50)" count leaves Instagram testers out.
4. **[user]** In their normal browser, logged in to that Instagram account: https://www.instagram.com/accounts/manage_access/?tab=tester > Accept. Logins in an automated browser failed with `?e=1348020`. The phone app menu path couldn't be found.
5. Once accepted, the table shows the account row: "Instagram account | Token | Webhook Subscription", with **"Generate token"**.

## Token

- Before a configuration exists, "Generate token" shows a dialog titled "Token generated" with the error "Select a configuration in Step 1 before generating an access token."
- After it exists: a popup "Log in to Business Tools from Meta" > "Continue with <Facebook name>" or "Continue with Instagram". **This has to run in the user's normal browser.** The token only returns to the developer page in that same browser, and consent doesn't carry over between browsers.
- **[approve]** "Select the business assets to share": the portfolio (may be one named after the Instagram account), the Instagram account, and "Ad Accounts · Optional" (none). Then "Review what you'll share": suggest unchecking "Allow access to messages" > Save.
- The token starts with `EAA`. Save it with `pbpaste | python3 ig.py auth --account <name> --ig-user-id <id shown in the table>`. Verified working: `whoami`, `limit` (`quota_total: 100`), `media`.
