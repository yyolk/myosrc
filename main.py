"""`main` is the top level module for your Flask application."""

# Import the Flask Framework
from flask import Flask, jsonify, render_template, request, url_for, flash, redirect, session, current_app
app = Flask(__name__)
# Note: We don't need to call run() since our application is embedded within
# the App Engine WSGI application server.

from google.appengine.api import urlfetch
urlfetch.set_default_fetch_deadline(45)

import requests
from requests.auth import HTTPBasicAuth
import json
from datetime import datetime
import operator
import math

from private.secret import Secret
secret = Secret()
app.secret_key = secret.session_secret

from flask.ext.github import GitHub
app.config['GITHUB_CLIENT_ID'] = secret.github_client_id
app.config['GITHUB_CLIENT_SECRET'] = secret.github_client_secret
github = GitHub(app)


@app.route('/', methods=["GET"])
def index():
    return render_template("index.html")

@app.route('/login')
def login():
    return github.authorize()

@app.route('/logout')
def logout():
    if "access_token" in session:
        # delete the authentication
        requests.delete("https://api.github.com/applications/" + secret.github_client_id + "/tokens/" + session["access_token"], auth=HTTPBasicAuth(secret.github_client_id, secret.github_client_secret))

    session.clear()
    return redirect("/")

@app.route('/callback')
@github.authorized_handler
def authorized(oauth_token):
    next_url = request.args.get('next') or url_for('index')
    if oauth_token is None:
        flash("Authorization failed.")
        return redirect("/")

    session["access_token"] = oauth_token
    return redirect("/osrc")


@github.access_token_getter
def token_getter():
    if "access_token" in session:
        return session["access_token"]


@app.route('/osrc', methods=["GET"])
def osrc():
    if not "access_token" in session:
        return redirect("/login")

    osrc_raw = raw_osrc_data()

    # Load the list of adjectives.
    with current_app.open_resource("json/adjectives.json") as f:
        adjectives = json.load(f)

    # Load the list of languages.
    with current_app.open_resource("json/languages.json") as f:
        language_list = json.load(f)

    # Load the list of event action descriptions.
    with current_app.open_resource("json/event_actions.json") as f:
        event_actions = json.load(f)

    # Compute the name of the best description of the user's weekly schedule.
    with current_app.open_resource("json/week_types.json") as f:
        week_types = json.load(f)

    # Load the list of event verbs.
    with current_app.open_resource("json/event_verbs.json") as f:
        event_verbs = json.load(f)

    # most used language
    used_languages = osrc_raw["cumulative_languages"].keys()
    if len(used_languages) > 0:
        most_used_language = max(osrc_raw["cumulative_languages"].iteritems(), key=operator.itemgetter(1))[0]
    else:
        most_used_language = None

    # events
    events_counter = dict()
    count = 0
    for event in osrc_raw["events"]:
        if not event["type"] in events_counter:
            events_counter[event["type"]] = 1
        else:
            events_counter[event["type"]] += 1
    most_done_event = max(events_counter.iteritems(), key=operator.itemgetter(1))[0]

    best_dist = -1
    week_type = None
    user_vector = osrc_raw["nomralized_events_vector"]
    for week in week_types:
        vector = week["vector"]
        norm = 1.0 / math.sqrt(sum([v * v for v in vector]))
        dot = sum([(v*norm-w) ** 2 for v, w in zip(vector, user_vector)])
        if best_dist < 0 or dot < best_dist:
            best_dist = dot
            week_type = week["name"]

    # Figure out the user's best time of day.
    with current_app.open_resource("json/time_of_day.json") as f:
        times_of_day = json.load(f)
    hours = osrc_raw["events_hours_vector"]
    best_time = None
    max_val = 0
    for i in range(len(hours)):
        if hours[i] > max_val:
            max_val = hours[i]
            best_time = i
    best_time_description = None
    for tod in times_of_day:
        times = tod["times"]
        if times[0] <= best_time < times[1]:
            best_time_description = tod["name"]
            break

    return render_template("osrc.html",
        osrc_data=osrc_raw,
        avatar=osrc_raw["user"]["avatar_url"],
        user=osrc_raw["name"],
        first_name=osrc_raw["first_name"],
        adjectives=adjectives,
        language_list=language_list,
        used_languages=used_languages,
        most_used_language=most_used_language,
        event_actions=event_actions,
        most_done_event=most_done_event,
        week_type=week_type,
        best_time=best_time,
        best_time_description=best_time_description,
        latest_repo_contributions=osrc_raw["latest_repo_contributions"][:5],
        event_verbs=event_verbs,
        unique_events=osrc_raw["unique_events"].keys(),
        events_vector=osrc_raw["events_vector"],
        weekly_unique_events=osrc_raw["weekly_unique_events"],
    )


# For displaying pretty json data
@app.route('/osrc_raw', methods=["GET"])
def osrc_raw():
    if not "access_token" in session:
        return redirect("/login")

    osrc_raw = raw_osrc_data()

    return jsonify(osrc_data=osrc_raw)


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, Nothing at this URL.', 404


@app.errorhandler(500)
def application_error(e):
    """Return a custom 500 error."""
    return 'Sorry, unexpected error: {}'.format(e), 500

def trimHTTP(url):
    if url.startswith("https://api.github.com/"):
        url = url[23:] # trim the "https://api.github.com/" (23 chars)
    if url.endswith("{/privacy}"):
        url = url[:-10] # trim last 10 chars
    return url

def raw_osrc_data():
    osrc_data = {}

    # user
    userInfo = github.get('user')
    osrc_data["user"] = userInfo
    name = userInfo["name"]
    osrc_data["name"] = name
    split_name = name.split()
    osrc_data["first_name"] = name.split()[0]
    if len(split_name) > 1:
        osrc_data["last_name"] = name.split()[1]

    # languages
    repos = github.get("user/repos")
    all_languages = dict()
    cumulative_languages = dict()
    for repo in repos:
        repoName = repo["name"]
        languagesURL = repo["languages_url"]
        languages = github.get(trimHTTP(languagesURL))
        for key in languages:
            if not key in cumulative_languages:
                cumulative_languages[key] = languages[key]
            else:
                cumulative_languages[key] += languages[key]
        all_languages[repoName] = languages

    osrc_data["repos"] = repos
    osrc_data["all_languages"] = all_languages
    osrc_data["cumulative_languages"] = cumulative_languages

    # events
    eventsURL = trimHTTP(userInfo["events_url"])
    events = github.get(eventsURL, params={"per_page": 100}) # won't return more than 100 per page
    osrc_data["events"] = events

    # work schedule
    event_dates = []
    events_vector = [0,0,0,0,0,0,0] # sunday is first
    events_hours_vector = [0]*24 # initialize list of zeros
    latest_repo_contributions = []
    recorded_repos = []
    unique_events = {} # unique events over past received events
    weekly_unique_events = [{} for x in range(7)] # unique events over each week
    for event in events:
        date_string = event["created_at"]
        date_obj = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%SZ") # monday is first
        event_dates.append(date_obj)

        # work days vector
        # do math to shift day over by 1
        actual_day = (date_obj.weekday()+1) % 7
        events_vector[actual_day] += 1

        # most worked hour
        events_hours_vector[date_obj.hour] += 1

        # latest repo contributions
        if event["type"] == "PushEvent":
            name = event["repo"]["name"]
            url = "https://github.com/" + name
            latest_repo_contributions.append( (date_obj, name, url) )

        if not event["type"] in unique_events:
            unique_events[event["type"]] = 1
        else:
            unique_events[event["type"]] += 1

        # make sure each dict has each of the event types
        for i in range(len(weekly_unique_events)):
            if not event["type"] in weekly_unique_events[i]:
                weekly_unique_events[i][event["type"]] = 0

        weekly_unique_events[actual_day][event["type"]] += 1

    norm = math.sqrt(sum([ v*v for v in events_vector ]))
    nomralized_events_vector = [ float(v)/norm for v in events_vector ]

    osrc_data["event_dates"] = event_dates
    osrc_data["events_vector"] = events_vector
    osrc_data["nomralized_events_vector"] = nomralized_events_vector
    osrc_data["events_hours_vector"] = events_hours_vector
    osrc_data["unique_events"] = unique_events
    osrc_data["weekly_unique_events"] = weekly_unique_events

    # sort and add latest_repo_contributions
    sorted(latest_repo_contributions, key=operator.itemgetter(0))
    latest_repo_contributions_copy = latest_repo_contributions[:] # clone array
    latest_repo_contributions = []
    recorded_repos = []
    for contribution in latest_repo_contributions_copy:
        if not contribution[1] in recorded_repos:
            recorded_repos.append(contribution[1])
            latest_repo_contributions.append(contribution)
    osrc_data["latest_repo_contributions"] = latest_repo_contributions

    osrc_data["rate_limit"] = github.get("rate_limit")
    return osrc_data