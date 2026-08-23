# ☕ Coffee Chat Scheduler

A small local web app that checks Google Calendar free/busy status for a
list of people and suggests meeting times — the same way Google Calendar's
own "suggested times" sidebar works when you add guests to an event. Built
for scheduling coffee chats (club recruitment, 1:1 catch-ups, etc.) without
the back-and-forth of "when are you free?" emails.

It only works for people whose free/busy info you can already see in
Google Calendar — typically anyone in your school's Google Workspace domain
(most `.edu` accounts have this on by default), or anyone who's explicitly
shared their calendar with you.

## Features

- **Two scheduling modes**
  - **Group** — find times that work for everyone on the list at once.
  - **Separate 1:1s** — get non-overlapping suggested times for *each*
    person individually (so you're never double-booked across different
    people). Scarcest people (fewest open slots) are matched first, so a
    hard-to-schedule person isn't starved by a flexible person claiming
    their only good option.
- **Your own calendar is included automatically** — toggle-able, so
  suggestions never conflict with your own schedule (or your own
  availability, for 1:1s, where it's always on).
- **Date ranges**, not just single days — search "next week," excluding
  specific weekdays (e.g. always skip Fridays) or specific dates (e.g. give
  at least a day's notice by excluding tomorrow).
- **Variable-length suggestions** — set a min/max duration and each
  suggestion is as long as the actual free gap allows, instead of forcing
  every suggestion to one fixed length.
- **Buffer time** around busy events, so nothing gets suggested right up
  against the edge of a class or another meeting.
- **Time zone aware** — correctly handles DST across multi-day ranges, and
  can optionally show a second time zone side-by-side for out-of-area
  recipients.
- **Simple / Advanced UI** — the default view has just the essentials;
  everything else lives behind an "Advanced options" disclosure.
- **Light/dark theme**, following your system preference with a manual
  override.

## One-time setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Create a Google OAuth Client ID** (free, takes ~3 minutes)
   - Go to https://console.cloud.google.com/
   - Create a new project (any name, e.g. "coffee-chat-scheduler")
   - Go to **APIs & Services > Library**, search for **Google Calendar API**, click **Enable**
   - Go to **APIs & Services > OAuth consent screen**
     - User type: **Internal** if your Google account is part of a
       Google Workspace organization (e.g. a school `.edu` domain) — this
       skips Google's app-verification review entirely. Otherwise choose
       **External** and add your own email as a test user.
     - Fill in the app name and your support email.
   - Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**
     - Application type: **Web application**
     - Under **Authorized redirect URIs**, add: `http://localhost:5000/oauth2callback`
     - Click Create, then **Download JSON**
   - Rename the downloaded file to `client_secret.json` and put it in this folder

3. **Run the app**

   ```bash
   python app.py
   ```

   Open http://localhost:5000, click **Connect Google Calendar**, and sign
   in with the Google account whose calendar view you want to use (i.e. the
   account that already shows you these people's busy times in the normal
   Google Calendar UI). The consent screen will ask for two things: viewing
   free/busy status, and your own email address (used to auto-detect "you"
   for the self-inclusion feature) — nothing else.

4. Enter one or more recipient email addresses, pick a date range, a
   meeting length, and how many suggestions you want, then click
   **Check availability**.

## Project structure

```
app.py                          Flask backend — all scheduling logic
templates/index.html            The single page, server-rendered with Jinja
static/app.js                   Theme toggle, form behavior, tooltip positioning
static/style-editorial.css      Active stylesheet (flat/bordered "editorial" look)
static/style.css                An earlier design (not currently used) — kept
                                 for comparison; switch back by changing the
                                 <link> in index.html if you prefer it
```

## Notes

- `token.json` and `self_email.txt` store your login after the first
  connect, so you won't need to re-authenticate every time. Delete them to
  disconnect.
- Nothing is sent anywhere except directly to Google's API from your own
  machine — this runs entirely locally, with no external server or
  database involved.
- This is a personal-use local tool, not a hosted multi-user service —
  each person who wants to use it clones this repo and connects their own
  Google account.
- If a person shows "Couldn't read this calendar," it means Google isn't
  giving you visibility into their free/busy status (they're outside your
  organization and haven't shared their calendar with you).

## License

MIT — see [LICENSE](LICENSE).
