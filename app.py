from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
from mysql.connector import Error
from datetime import date, datetime, timedelta
from calendar import monthrange

app = Flask(__name__)

################################################################
# 1) CREATE A CONNECTION TO MYSQL
################################################################
def create_connection():
    """Connect to your MySQL database."""
    try:
        connection = mysql.connector.connect(
            host='localhost',
            database='',   # Your DB name
            user='',              # Your DB user
            password=''     # Your DB password
        )
        if connection.is_connected():
            print("Connected to MySQL database")
        return connection
    except Error as e:
        print(f"Error while connecting to MySQL: {e}")
        return None

################################################################
# 2) INSERT USER FORM DATA: contacts + forms
################################################################
def insert_user_form(
    name, email,
    Race_type,
    Training_History,
    Goal_Time,
    Event_date,
    Training_Times
):
    """Insert a user into 'contacts' and a row into 'forms' with the training data."""
    last_contact_id = None
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()

            # Insert new contact
            insert_contacts_sql = """
                INSERT INTO contacts (name, email)
                VALUES (%s, %s)
            """
            cursor.execute(insert_contacts_sql, (name, email))
            last_contact_id = cursor.lastrowid

            # Insert forms row
            insert_forms_sql = """
                INSERT INTO forms (
                  contact_id, Race_type, Training_History,
                  Goal_Time, Event_date, Training_Times
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_forms_sql, (
                last_contact_id,
                Race_type,
                Training_History,
                Goal_Time,
                Event_date,
                Training_Times
            ))
            conn.commit()
            print(f"Data inserted successfully for {name}!")
    except Error as e:
        print(f"Error while inserting user: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

    return last_contact_id

################################################################
# 3) FETCH USER FORM DATA
################################################################
def get_user_form_data(contact_id):
    """
    Return (race_type, goal_time_str, event_date, training_times)
    from the most recent 'forms' row for a given contact_id.
    """
    race_type = None
    goal_time_str = None
    event_date = None
    training_times = 0

    conn = create_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Race_type, Goal_Time, Event_date, Training_Times
            FROM forms
            WHERE contact_id = %s
            ORDER BY form_id DESC
            LIMIT 1
        """, (contact_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            race_type = row[0]
            goal_time_str = row[1]
            raw_event_date = row[2]
            training_times = int(row[3] or 0)

            # Convert event_date to date object if it's a string
            if isinstance(raw_event_date, str):
                event_date = datetime.strptime(raw_event_date, '%Y-%m-%d').date()
            else:
                event_date = raw_event_date

    return (race_type, goal_time_str, event_date, training_times)

################################################################
# 4) WORKOUTS LOOKUP
################################################################
def get_workouts_for_week(week_no):
    """
    Return the row from 'workouts' for a given week_no:
    (week_no, bike_easy, bike_hard, run_easy, run_hard, swim_easy, swim_hard)
    """
    conn = create_connection()
    if not conn:
        return None

    cursor = conn.cursor()
    cursor.execute("""
        SELECT week_no,
               bike_easy, bike_hard,
               run_easy,  run_hard,
               swim_easy, swim_hard
        FROM workouts
        WHERE week_no = %s
        LIMIT 1
    """, (week_no,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

################################################################
# 5) PARSE TIME STR 'H:M:S' -> SECONDS
################################################################
def parse_time_to_seconds(time_str):
    if not time_str:
        return 0
    parts = time_str.split(':')
    h = int(parts[0]) if len(parts) > 0 else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return h*3600 + m*60 + s

################################################################
# 6) CALC WORKOUT DATA (DISTANCE, DURATION, PACE)
################################################################
def calc_workout_data(week_no, discipline, is_hard, race_type, total_goal_sec, total_weeks):
    """
    1) baseDist depends on race_type + discipline
    2) progression factor (week 1..peak) -> taper
    3) if is_hard => intensity factor 1.0, else 0.8
    4) distance = baseDist * progression * intensity
    5) For Ironman: cap distance at 90% of actual race distance
    6) compute duration & pace string
    """

    # A) base distance map for peak training (not the actual race distance, but typical peak)
    BASES = {
        "Sprint":   {"bike": 20.0, "run": 6.0,  "swim": 0.75},
        "Olympic":  {"bike": 40.0, "run": 12.0, "swim": 1.5},
        "70.3":     {"bike": 90.0, "run": 20.0, "swim": 2.5},
        "Ironman":  {"bike": 180.0,"run": 32.0, "swim": 3.8}
    }
    base_dist = 5.0  # fallback
    if race_type in BASES and discipline in BASES[race_type]:
        base_dist = BASES[race_type][discipline]

    # B) progression factor
    peak_week = total_weeks - 3
    if week_no <= peak_week:
        prog_factor = week_no / float(peak_week)
    else:
        # taper to 60% at final week
        taper_fraction = 0.6
        w_past_peak = week_no - peak_week
        prog_factor = 1.0 - (w_past_peak * (1 - taper_fraction) / 3)
    if prog_factor < 0:
        prog_factor = 0.0

    # C) intensity factor
    int_factor = 1.0 if is_hard else 0.8

    # D) distance
    distance = base_dist * prog_factor * int_factor
    if distance < 0:
        distance = 0

    # E) For Ironman only: ensure we never exceed 90% of actual race distance
    #    Real full distances: 3.8 km swim, 180 km bike, 42.2 km run
    #    We'll clamp the computed distance to 0.9 * that
    if race_type == "Ironman":
        IRONMAN_FULL = {"swim": 3.8, "bike": 180.0, "run": 42.2}
        max_allowed = IRONMAN_FULL.get(discipline, 5.0) * 0.9
        if distance > max_allowed:
            distance = max_allowed

    # F) naive approach for "duration"
    if discipline == "run":
        pace_sec_per_unit = 600.0  # ~10:00/mi
    elif discipline == "bike":
        pace_sec_per_unit = 180.0  # ~3:00/mi => 20 mph
    elif discipline == "swim":
        pace_sec_per_unit = 1200.0 # ~20:00 per km
    else:
        pace_sec_per_unit = 600.0

    duration_sec = distance * pace_sec_per_unit

    def fmt_minsec(sec):
        mm = int(sec // 60)
        ss = int(sec % 60)
        return f"{mm}:{ss:02d}"

    duration_str = fmt_minsec(duration_sec)
    pace_str = "N/A"
    if distance > 0:
        pace_per_unit_sec = duration_sec / distance
        pace_str = f"{fmt_minsec(pace_per_unit_sec)} /{discipline}"

    return {
        "distance": round(distance, 2),
        "duration": duration_str,
        "pace_str": pace_str
    }

################################################################
# 7) BUILD SCHEDULE: For each week, pick up to Training_Times workouts
################################################################
def build_schedule_for_user(contact_id, total_weeks=25):
    """
    1) fetch user (race_type, etc.)
    2) for w in 1..total_weeks => workouts row => pick up to training_times (hard first)
    3) calc_workout_data => store results
    """
    race_type, goal_time_str, event_date, training_times = get_user_form_data(contact_id)
    if not race_type or not event_date:
        return {}

    total_goal_sec = parse_time_to_seconds(goal_time_str)
    schedule = {}

    for w in range(1, total_weeks+1):
        row = get_workouts_for_week(w)
        if not row:
            continue
        # row => (week_no, bike_easy, bike_hard, run_easy, run_hard, swim_easy, swim_hard)
        (wk_no, bike_e, bike_h, run_e, run_h, swim_e, swim_h) = row

        # Priority list
        possible_workouts = [
            ("bike", bike_h, True),
            ("run",  run_h,  True),
            ("swim", swim_h, True),
            ("bike", bike_e, False),
            ("run",  run_e,  False),
            ("swim", swim_e, False),
        ]
        chosen = []
        for (disc, wname, is_hard) in possible_workouts:
            if len(chosen) < training_times and wname.lower() != "rest":
                data = calc_workout_data(w, disc, is_hard, race_type, total_goal_sec, total_weeks)
                chosen.append({
                    "discipline": disc,
                    "workout_name": wname,
                    "is_hard": is_hard,
                    "distance": data["distance"],
                    "duration": data["duration"],
                    "pace": data["pace_str"]
                })
        schedule[w] = chosen

    return schedule

################################################################
# 8) MAP SCHEDULE INTO day->workouts
################################################################
def map_schedule_to_calendar(schedule, event_date, total_weeks=25):
    """
    Suppose 'week 1' is event_date - (total_weeks-1)*7 days.
    Place chosen workouts M/W/F.
    Return { date_obj: [ {workout_info}, ... ], ... }
    """
    start_date = event_date - timedelta(weeks=(total_weeks-1))
    day_to_workouts = {}

    for w in range(1, total_weeks+1):
        week_start = start_date + timedelta(weeks=w-1)
        chosen = schedule.get(w, [])
        # place them M/W/F, etc.
        day_offsets = [0, 2, 4, 1, 3, 5, 6]
        for i, wk in enumerate(chosen):
            if i < len(day_offsets):
                d = week_start + timedelta(days=day_offsets[i])
                day_to_workouts.setdefault(d, []).append(wk)

    return day_to_workouts

################################################################
# 9) ROUTES
################################################################

@app.route('/')
def index():
    """Render the multi-step form page."""
    return render_template('forms.html')

@app.route('/submit_form', methods=['POST'])
def submit_form():
    """Process form submission -> store in DB -> redirect to /calendar/<contact_id>."""
    name = request.form.get('name')
    email = request.form.get('email')
    Race_type = request.form.get('Race_type')
    Training_History = request.form.get('Training_History')
    hours = request.form.get('hours') or '0'
    minutes = request.form.get('minutes') or '0'
    seconds = request.form.get('seconds') or '0'
    Goal_Time = f"{hours}:{minutes}:{seconds}"
    Event_date = request.form.get('Event_date')
    training_times_str = request.form.get('Training_Times') or '0'
    Training_Times = int(training_times_str)

    contact_id = insert_user_form(
        name, email,
        Race_type, Training_History,
        Goal_Time, Event_date,
        Training_Times
    )
    if not contact_id:
        return render_template('forms.html', message="Could not insert data.")

    return redirect(url_for('calendar_view', contact_id=contact_id))

@app.route('/calendar/<int:contact_id>')
def calendar_view(contact_id):
    """
    1) Build schedule (1..total_weeks)
    2) Convert to day_map
    3) Decide which year/month to show based on query params
    4) Build monthly grid
    5) Provide next/prev month
    6) Render calendar.html
    7) We also highlight Race Day with an icon if day == event_date
    """
    total_weeks = 25
    schedule = build_schedule_for_user(contact_id, total_weeks=total_weeks)
    race_type, goal_time_str, event_date, training_times = get_user_form_data(contact_id)
    if not event_date:
        return "No event date found for user"

    # day_map => day->[workouts...]
    day_map = map_schedule_to_calendar(schedule, event_date, total_weeks)

    # Month navigation
    year_str = request.args.get('year')
    month_str = request.args.get('month')
    if year_str and month_str:
        try:
            display_year = int(year_str)
            display_month = int(month_str)
        except ValueError:
            display_year = event_date.year
            display_month = event_date.month
    else:
        display_year = event_date.year
        display_month = event_date.month

    if not (1 <= display_month <= 12):
        display_month = event_date.month

    # next/prev
    next_month = display_month + 1
    next_year = display_year
    if next_month > 12:
        next_month = 1
        next_year += 1

    prev_month = display_month - 1
    prev_year = display_year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    # Build monthly grid
    start_of_month = date(display_year, display_month, 1)
    days_in_month = monthrange(display_year, display_month)[1]
    full_month_days = [
        date(display_year, display_month, d)
        for d in range(1, days_in_month+1)
    ]
    first_day_weekday = start_of_month.weekday()  # Mon=0..Sun=6

    calendar_weeks = []
    current_week = [None]*7
    day_index = first_day_weekday
    for d in full_month_days:
        current_week[day_index] = d
        day_index += 1
        if day_index == 7:
            calendar_weeks.append(current_week)
            current_week = [None]*7
            day_index = 0
    if any(x is not None for x in current_week):
        calendar_weeks.append(current_week)

    return render_template(
        "calendar.html",
        contact_id=contact_id,
        race_type=race_type,
        event_date=event_date,
        calendar_weeks=calendar_weeks,
        day_map=day_map,
        display_year=display_year,
        display_month=display_month,
        next_year=next_year,
        next_month=next_month,
        prev_year=prev_year,
        prev_month=prev_month
    )

################################################################
# 10) RUN
################################################################
if __name__ == '__main__':
    app.run(debug=True)
