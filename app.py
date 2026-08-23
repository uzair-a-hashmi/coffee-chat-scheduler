"""
Coffee Chat Scheduler - checks Google Calendar free/busy status across a
date range for a list of email addresses, and suggests meeting times that
work for everyone (including you, by default), the same way Google
Calendar's own "suggested times" sidebar works.

Requires the signed-in Google account to have visibility into the target
person's free/busy info (same Google Workspace domain with free/busy
sharing enabled, or a calendar they've explicitly shared).

Setup: see README.md
"""
import calendar as calendar_module
import datetime
import os
from zoneinfo import ZoneInfo

from flask import Flask, redirect, render_template, request, session, url_for
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Allow OAuth over http://localhost for local development only.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
SELF_EMAIL_FILE = "self_email.txt"
REDIRECT_URI = "http://localhost:5000/oauth2callback"
MAX_RANGE_DAYS = 31  # sanity cap so a typo can't trigger a huge query

# (IANA name, friendly label) for the "also show times in" dropdown. This is
# purely a display conversion of the same already-correct instants — it
# doesn't change any free/busy math.
TIMEZONE_CHOICES = [
    ("America/New_York", "Eastern"),
    ("America/Chicago", "Central"),
    ("America/Denver", "Mountain"),
    ("America/Phoenix", "Arizona (no DST)"),
    ("America/Los_Angeles", "Pacific"),
    ("America/Anchorage", "Alaska"),
    ("Pacific/Honolulu", "Hawaii"),
    ("UTC", "UTC"),
    ("Europe/London", "London"),
]
TIMEZONE_LABELS = dict(TIMEZONE_CHOICES)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret-change-me")
# Disable static file caching so CSS/JS edits show up on a normal refresh
# instead of needing a hard refresh while actively iterating on the design.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


def static_version(filename):
    # Appended as a ?v= query string on static asset URLs so the URL itself
    # changes whenever the file's contents change. A browser can't reuse a
    # cached response tied to the *old* URL no matter what cache headers
    # that old response carried, so this works even for a copy the browser
    # cached before SEND_FILE_MAX_AGE_DEFAULT was set to 0 above.
    path = os.path.join(app.static_folder, filename)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


app.jinja_env.globals["static_version"] = static_version


def load_saved_credentials():
    # Require a self_email.txt too: it's only written after granting the
    # email scope, so its absence means an older token predates that scope
    # (Credentials.from_authorized_user_file trusts the scopes we pass it,
    # not what was actually granted, so it can't detect this on its own).
    if not os.path.exists(TOKEN_FILE) or not os.path.exists(SELF_EMAIL_FILE):
        return None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_credentials(creds)
        return creds
    except Exception:
        # Corrupted token.json, or a refresh that failed because access was
        # revoked/expired on Google's side — treat it the same as "never
        # connected" so the user gets the normal Connect button instead of
        # every page (including the landing page) crashing outright.
        return None


def save_credentials(creds):
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def load_self_email():
    if not os.path.exists(SELF_EMAIL_FILE):
        return None
    with open(SELF_EMAIL_FILE) as f:
        return f.read().strip() or None


def save_self_email(email):
    with open(SELF_EMAIL_FILE, "w") as f:
        f.write(email)


@app.route("/")
def index():
    creds = load_saved_credentials()
    connected = bool(creds and creds.valid)
    today = datetime.date.today()
    return render_template(
        "index.html", connected=connected, results=None, error=None, suggestions=None,
        individual_results=None, schedule_mode="group",
        self_email=load_self_email() if connected else None,
        start_date=today.isoformat(), end_date=(today + datetime.timedelta(days=6)).isoformat(),
        timezone_choices=TIMEZONE_CHOICES, display_tz=None, advanced_active=False,
    )


@app.route("/authorize")
def authorize():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return (
            "Missing client_secret.json. See README.md for how to create "
            "a Google OAuth Client ID and download it into this folder.",
            500,
        )
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    session["state"] = state
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    state = session.get("state")
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    save_credentials(creds)

    userinfo = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
    email = userinfo.get("email")
    if email:
        save_self_email(email)

    return redirect(url_for("index"))


def parse_emails(raw):
    emails = [e.strip() for e in raw.replace("\n", ",").split(",") if e.strip()]
    # dict.fromkeys dedupes while preserving the order the user typed them in.
    return list(dict.fromkeys(emails))


def parse_dates(raw):
    dates = set()
    for token in raw.replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        dates.add(datetime.datetime.strptime(token, "%Y-%m-%d").date())
    return dates


def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def clip_to_window(intervals, window_start, window_end):
    clipped = []
    for s, e in intervals:
        if e <= window_start or s >= window_end:
            continue
        clipped.append((max(s, window_start), min(e, window_end)))
    return clipped


def compute_free_slots(day_start, day_end, busy_intervals):
    busy = merge_intervals(busy_intervals)
    free = []
    cursor = day_start
    for start, end in busy:
        if start > cursor:
            free.append((cursor, min(start, day_end)))
        cursor = max(cursor, end)
        if cursor >= day_end:
            break
    if cursor < day_end:
        free.append((cursor, day_end))
    return [f for f in free if f[0] < f[1]]


def intersect_two(a, b):
    a = sorted(a)
    b = sorted(b)
    i = j = 0
    result = []
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if lo < hi:
            result.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def intersect_all(list_of_interval_lists):
    if not list_of_interval_lists:
        return []
    result = list_of_interval_lists[0]
    for lst in list_of_interval_lists[1:]:
        if not result:
            break
        result = intersect_two(result, lst)
    return result


def generate_candidate_slots(windows, min_duration, max_duration):
    """Greedily fill each free window with the longest slot that fits (up to
    max_duration), so slot lengths adapt to how much room is actually there
    instead of forcing every suggestion to the same fixed length."""
    candidates = []
    for start, end in windows:
        cursor = start
        while end - cursor >= min_duration:
            length = min(max_duration, end - cursor)
            candidates.append((cursor, cursor + length))
            cursor += length
    return candidates


def pick_spread(candidates, n):
    if n <= 0 or not candidates:
        return []
    if len(candidates) <= n:
        return candidates
    if n == 1:
        return [candidates[len(candidates) // 2]]
    last = len(candidates) - 1
    picks = []
    seen = set()
    for i in range(n):
        idx = round(i * last / (n - 1))
        if idx not in seen:
            seen.add(idx)
            picks.append(candidates[idx])
    return picks


def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += datetime.timedelta(days=1)


def select_suggestions(candidates_by_day, eligible_dates, num_suggestions, per_day_count):
    """Pick up to num_suggestions (date, start, end) tuples from per-day candidate
    lists, either spread freely across the range or capped at per_day_count/day."""
    if per_day_count is None:
        pooled = []
        for d in eligible_dates:
            pooled.extend(candidates_by_day[d])
        return [(s.date(), s, e) for s, e in pick_spread(pooled, num_suggestions)]

    chosen = []
    for d in eligible_dates:
        if len(chosen) >= num_suggestions:
            break
        remaining = num_suggestions - len(chosen)
        take = min(per_day_count, remaining)
        for s, e in pick_spread(candidates_by_day[d], take):
            chosen.append((d, s, e))
    return chosen


def overlaps_any(start, end, claimed):
    return any(start < ce and end > cs for cs, ce in claimed)


def remove_claimed(candidates_by_day, eligible_dates, claimed):
    return {
        d: [(s, e) for s, e in candidates_by_day[d] if not overlaps_any(s, e, claimed)]
        for d in eligible_dates
    }


@app.route("/check", methods=["POST"])
def check():
    creds = load_saved_credentials()
    if not creds or not creds.valid:
        return redirect(url_for("authorize"))

    form = request.form
    recipient_emails = parse_emails(form.get("emails", ""))
    schedule_mode = form.get("schedule_mode", "group")
    # One-on-ones are meaningless without you in every meeting, so force it on.
    include_self = "include_self" in form or schedule_mode == "individual"
    own_email = load_self_email()
    self_email = own_email if include_self else None

    start_date_str = form.get("start_date")
    end_date_str = form.get("end_date")
    start_time_str = form.get("start_time", "09:00")
    end_time_str = form.get("end_time", "17:00")
    tz_name = form.get("tz_name", "").strip() or "UTC"
    min_duration_str = form.get("min_duration_minutes", "60")
    max_duration_str = form.get("max_duration_minutes", "60")
    buffer_str = form.get("buffer_minutes", "0")
    display_tz_name = form.get("display_tz", "")
    num_suggestions_str = form.get("num_suggestions", "3")
    per_day_no_pref = "per_day_no_pref" in form
    per_day_count_str = form.get("per_day_count", "1")
    exclude_dates_str = form.get("exclude_dates", "")
    exclude_weekday_strs = form.getlist("exclude_weekday")

    error = None
    results = None
    suggestions = None
    individual_results = None
    # Default so it's always defined for the render_template() call below
    # even if validation fails before the try block reaches the real parse.
    exclude_weekdays = set()

    emails = list(recipient_emails)
    if self_email and self_email not in emails:
        emails = [self_email] + emails

    if not emails:
        error = "Enter at least one recipient email address (or include your own calendar)."
    else:
        try:
            start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if end_date < start_date:
                raise ValueError("end date must be on or after the start date")
            if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
                raise ValueError(f"date range can't be more than {MAX_RANGE_DAYS} days")

            start_h, start_m = map(int, start_time_str.split(":"))
            end_h, end_m = map(int, end_time_str.split(":"))
            if (end_h, end_m) <= (start_h, start_m):
                raise ValueError("latest time must be after earliest time")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                raise ValueError("unrecognized browser time zone")
            try:
                exclude_weekdays = {int(v) for v in exclude_weekday_strs}
            except ValueError:
                raise ValueError("invalid day-of-week exclusion")

            min_duration = datetime.timedelta(minutes=int(min_duration_str))
            max_duration = datetime.timedelta(minutes=int(max_duration_str))
            num_suggestions = int(num_suggestions_str)
            per_day_count = None if per_day_no_pref else int(per_day_count_str)
            if min_duration.total_seconds() <= 0:
                raise ValueError("shortest duration must be positive")
            if max_duration < min_duration:
                raise ValueError("longest duration can't be shorter than the shortest duration")
            if num_suggestions <= 0:
                raise ValueError("number of suggestions must be positive")
            if per_day_count is not None and per_day_count <= 0:
                raise ValueError("suggestions per day must be positive")
            buffer = datetime.timedelta(minutes=int(buffer_str))
            if buffer.total_seconds() < 0:
                raise ValueError("buffer can't be negative")

            excluded_dates = parse_dates(exclude_dates_str)
            eligible_dates = [
                d for d in daterange(start_date, end_date)
                if d.weekday() not in exclude_weekdays and d not in excluded_dates
            ]
            if not eligible_dates:
                raise ValueError("no eligible days left in range after your exclusions")

            range_start = datetime.datetime(
                start_date.year, start_date.month, start_date.day, start_h, start_m, tzinfo=tz
            )
            range_end = datetime.datetime(
                end_date.year, end_date.month, end_date.day, end_h, end_m, tzinfo=tz
            )

            service = build("calendar", "v3", credentials=creds)
            body = {
                # Widened by the buffer so an event just outside the nominal
                # range (e.g. ending right at the range's start) still gets
                # fetched and can push its buffer zone into the range.
                "timeMin": (range_start - buffer).isoformat(),
                "timeMax": (range_end + buffer).isoformat(),
                "items": [{"id": email} for email in emails],
            }
            response = service.freebusy().query(body=body).execute()
            calendars = response.get("calendars", {})

            fmt_time = lambda dt: dt.strftime("%-I:%M %p") if os.name != "nt" else dt.strftime("%I:%M %p").lstrip("0")
            fmt_date = lambda d: f"{calendar_module.day_name[d.weekday()][:3]} {d.month}/{d.day}"

            display_tz = None
            if display_tz_name:
                try:
                    display_tz = ZoneInfo(display_tz_name)
                except Exception:
                    raise ValueError("unrecognized time zone")

            def fmt_slot(d, s, e):
                label = f"{fmt_date(d)}: {fmt_time(s)} - {fmt_time(e)}"
                if display_tz is None:
                    return label
                s2, e2 = s.astimezone(display_tz), e.astimezone(display_tz)
                tz_label = TIMEZONE_LABELS.get(display_tz_name, display_tz_name)
                converted = f"{fmt_time(s2)} - {fmt_time(e2)}"
                if s2.date() != d:
                    converted = f"{fmt_date(s2.date())} {converted}"
                return f"{label}  →  {converted} {tz_label}"

            busy_by_email = {}
            any_unreadable = False
            for email in emails:
                cal = calendars.get(email, {})
                cal_errors = cal.get("errors")
                busy_raw = cal.get("busy", [])
                busy_by_email[email] = {
                    "unreadable": bool(cal_errors),
                    # Padded by the buffer on both sides, so a slot can't be
                    # suggested right up against the edge of a busy block.
                    "busy": [
                        (
                            datetime.datetime.fromisoformat(b["start"]).astimezone(tz) - buffer,
                            datetime.datetime.fromisoformat(b["end"]).astimezone(tz) + buffer,
                        )
                        for b in busy_raw
                    ],
                }
                if cal_errors:
                    any_unreadable = True

            results = []
            candidates_by_day = {}
            free_by_email_by_day = {email: {} for email in emails}
            for d in eligible_dates:
                day_start = datetime.datetime(d.year, d.month, d.day, start_h, start_m, tzinfo=tz)
                day_end = datetime.datetime(d.year, d.month, d.day, end_h, end_m, tzinfo=tz)

                day_people = []
                free_by_person = []
                for email in emails:
                    info = busy_by_email[email]
                    day_busy = clip_to_window(info["busy"], day_start, day_end)
                    day_free = compute_free_slots(day_start, day_end, day_busy)
                    free_by_email_by_day[email][d] = day_free
                    if not info["unreadable"]:
                        free_by_person.append(day_free)
                    day_people.append(
                        {
                            "email": email,
                            "unreadable": info["unreadable"],
                            "busy": [f"{fmt_time(s)} - {fmt_time(e)}" for s, e in day_busy],
                            "free": [f"{fmt_time(s)} - {fmt_time(e)}" for s, e in day_free],
                        }
                    )

                results.append({"date": fmt_date(d), "people": day_people})

                combined_free = intersect_all(free_by_person)
                candidates_by_day[d] = generate_candidate_slots(combined_free, min_duration, max_duration)

            individual_results = None

            if schedule_mode == "individual":
                if not self_email:
                    raise ValueError("couldn't determine your own email — reconnect your Google account")
                if busy_by_email[self_email]["unreadable"]:
                    raise ValueError("your own calendar couldn't be read")

                per_person_candidates = {}
                for email in recipient_emails:
                    if email == self_email or email not in busy_by_email:
                        continue
                    if busy_by_email[email]["unreadable"]:
                        per_person_candidates[email] = None  # unreadable, no suggestions possible
                        continue
                    by_day = {}
                    for d in eligible_dates:
                        overlap = intersect_two(free_by_email_by_day[self_email][d], free_by_email_by_day[email][d])
                        by_day[d] = generate_candidate_slots(overlap, min_duration, max_duration)
                    per_person_candidates[email] = by_day

                # Scarcest people (fewest total candidate slots) get first pick,
                # so a hard-to-schedule person isn't left with nothing because an
                # easy-to-schedule person's suggestions happened to claim it first.
                def total_candidates(email):
                    by_day = per_person_candidates[email]
                    if by_day is None:
                        return -1  # unreadable people sort first and simply get skipped
                    return sum(len(v) for v in by_day.values())

                ordered_recipients = sorted(
                    (e for e in recipient_emails if e != self_email and e in busy_by_email),
                    key=total_candidates,
                )
                if not ordered_recipients:
                    raise ValueError("enter at least one recipient other than your own email for 1:1 scheduling")

                claimed = []
                individual_results = []
                for email in ordered_recipients:
                    by_day = per_person_candidates[email]
                    if by_day is None:
                        individual_results.append(
                            {"email": email, "unreadable": True, "slots": [], "found": 0, "requested": num_suggestions}
                        )
                        continue
                    available = remove_claimed(by_day, eligible_dates, claimed)
                    chosen = select_suggestions(available, eligible_dates, num_suggestions, per_day_count)
                    claimed.extend((s, e) for _, s, e in chosen)
                    individual_results.append(
                        {
                            "email": email,
                            "unreadable": False,
                            "slots": [fmt_slot(d, s, e) for d, s, e in chosen],
                            "found": len(chosen),
                            "requested": num_suggestions,
                        }
                    )
                # Restore the order the user typed them in for display.
                order_lookup = {e: i for i, e in enumerate(recipient_emails)}
                individual_results.sort(key=lambda r: order_lookup.get(r["email"], 0))
            else:
                chosen = select_suggestions(candidates_by_day, eligible_dates, num_suggestions, per_day_count)
                suggestions = {
                    "slots": [fmt_slot(d, s, e) for d, s, e in chosen],
                    "requested": num_suggestions,
                    "found": len(chosen),
                    "any_unreadable": any_unreadable,
                }
        except ValueError as e:
            error = f"Invalid input: {e}"
        except HttpError as e:
            error = f"Google Calendar couldn't be reached ({e.status_code}). Try again in a moment."
        except Exception:
            error = "Something went wrong talking to Google Calendar. Try again in a moment."

    advanced_active = bool(
        buffer_str not in ("0", "", None)
        or not per_day_no_pref
        or exclude_weekdays
        or exclude_dates_str.strip()
        or display_tz_name
        or min_duration_str != max_duration_str
        or start_time_str != "09:00"
        or end_time_str != "17:00"
        or (schedule_mode != "individual" and "include_self" not in form)
    )

    return render_template(
        "index.html", connected=True, results=results, error=error, suggestions=suggestions,
        individual_results=individual_results, schedule_mode=schedule_mode,
        self_email=own_email, include_self=include_self,
        emails=form.get("emails", ""), start_date=start_date_str, end_date=end_date_str,
        start_time=start_time_str, end_time=end_time_str,
        min_duration_minutes=min_duration_str, max_duration_minutes=max_duration_str,
        buffer_minutes=buffer_str, timezone_choices=TIMEZONE_CHOICES, display_tz=display_tz_name,
        advanced_active=advanced_active,
        num_suggestions=num_suggestions_str,
        per_day_no_pref=per_day_no_pref, per_day_count=per_day_count_str,
        exclude_dates=exclude_dates_str, exclude_weekdays=exclude_weekdays,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
