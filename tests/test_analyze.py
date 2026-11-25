import json

from app.analyze import analyze, find_places


def test_places_with_hebrew_prefixes():
    assert analyze("שריפה בכרמיאל")["location"] == "כרמיאל"
    assert analyze("תאונה קשה מצפת לכיוון ראש פינה")["places"][:2] == ["צפת", "ראש פינה"]
    assert analyze("עומסי תנועה בכביש 89 סמוך לצומת מירון")["location"] == "צומת מירון"   # צומת קודם לכביש
    assert analyze("אזור קו העימות מלכיה (15 שניות)")["location"] == "מלכיה"             # יישוב קודם לאזור


def test_no_false_places():
    for text in ["יאיר גולן: ממשלת מיעוט היא החלופה היחידה", "הבית נהרס כליל", "שלומי ודפנה התחתנו",
                 "צה\"ל תקף בצפון מזרח רמאללה", "עמיר פרץ התראיין", "הכביש יפתח מחר בבוקר"]:
        assert find_places(text) == [], text


def test_real_messages():
    a = analyze("🚨 ירי רקטות וטילים (21/9/2026) 15:27 אזור קו העימות מלכיה (15 שניות) היכנסו למרחב המוגן")
    assert (a["type"], a["location"], a["relevant"], a["ended"]) == ("security", "מלכיה", True, False)
    a = analyze("✅ עדכון (21/9/2026) 15:32 האירוע הסתיים השוהים במרחב המוגן יכולים לצאת. אזור קו העימות")
    assert a["type"] == "security" and a["ended"]
    a = analyze("תושבים יקרים, במהלך בדיקות שגרתיות נמצאו נתונים חריגים במי השתיה בכרמיאל")
    assert (a["type"], a["location"]) == ("infrastructure", "כרמיאל")
    # כיסוי ארצי: אירוע במרכז הארץ רלוונטי, ומשויך לאזור שלו
    a = analyze("דוברות מד\"א: התקבל דיווח במוקד 101 על רוכב אופנוע שנפגע מרכב בראשון לציון")
    assert (a["type"], a["location"], a["relevant"], a["north"], a["regions"]) == \
        ("accident", "ראשון לציון", True, False, ["shfela"])
    assert analyze("שריפה בכרמיאל")["regions"] == ["galil-maaravi"]
    assert analyze("ירי רקטות לעוטף עזה")["regions"] == ["south"]
    # שם יישוב שהוא גם מילה נפוצה לא מזוהה כמקום
    assert analyze("תאונה ליד הגשר, נהג נפגע")["places"] == []
    # שם רחוב אינו מקום האירוע
    assert analyze("הולכת רגל נפגעה מרכב ברחוב משמר הירדן בתל אביב")["places"] == ["תל אביב - יפו"]
    assert analyze("מחאה בשדרות חיים בר לב בירושלים, חסימת צירים")["places"] == ["ירושלים"]
    # בצפון אבל לא אירוע → לא רלוונטי
    assert not analyze("סוכות בכרמיאל: כל הפעילויות והאירועים היום")["relevant"]


def test_severity():
    sev = lambda t: analyze(t)["severity"]
    # קריטי: איום על ציבור רחב או רב-נפגעים
    assert sev("🚨 ירי רקטות וטילים, קו העימות: שתולה, היכנסו למרחב המוגן") == 3
    assert sev("תאונה קשה בכביש 6, שלושה הרוגים") == 3
    assert sev("שריפת חורש גדולה ליד צפת, האש מתפשטת לעבר בתים, פינוי תושבים") == 3
    # בינוני
    assert sev("תאונה בכביש 85, נהג נהרג") == 2
    assert sev("תאונה בכביש 85, שני פצועים במצב בינוני") == 2
    assert sev("רוכב אופנוע נפצע קשה בתאונה בעפולה") == 2
    assert sev("שריפה בדירה בקומה שלישית בכרמיאל, צוותי כיבוי במקום") == 2
    assert sev("דובר צה\"ל: בהמשך להתרעות באבן מנחם, מדובר בזיהוי שווא") == 2
    assert sev("כביש 90 חסום לתנועה בשני הכיוונים") == 2
    # נמוך: אדם אחד במצב קל/בינוני, רכב בוער, מפגע
    assert sev("תאונה קלה בכביש 85") == 1
    assert sev("דוברות מד\"א: הולכת רגל נפגעה מרכב בראשון לציון, מצבה בינוני") == 1
    assert sev("נתניה פרישמן שריפת רכב") == 1
    assert sev("כוחות הצלה הוזעקו לרחוב עזרא בבני ברק, אישה כבת 70 נפלה במדרכה") == 1


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "e.db"))
    monkeypatch.setenv("SEED_DEMO", "0")
    from app.db import connect, init_db
    from app.seed import run_seed
    init_db()
    run_seed()
    return connect


def _add(con, sid, ext, when, text, official=False):
    from app.ingest import upsert_report
    upsert_report(con, sid, {"external_id": ext, "url": None, "published_at": when, "content": text}, when)


def test_events_merge_alert_update_and_copies(tmp_path, monkeypatch):
    connect = _db(tmp_path, monkeypatch)
    from app import repo
    from app.events_builder import build_events
    with connect() as con:
        off = repo.create_source(con, repo.SourceIn(name="רשמי", kind="telegram", address="@official_x", is_official=True), "t")
        u1 = repo.create_source(con, repo.SourceIn(name="פרטי1", kind="telegram", address="@private_one"), "t")
        u2 = repo.create_source(con, repo.SourceIn(name="פרטי2", kind="telegram", address="@private_two"), "t")
        _add(con, off["id"], "1", "2026-11-08T04:10:06+00:00", "חדירת כלי טיס עוין אזור קו העימות זרעית היכנסו למרחב המוגן")
        _add(con, off["id"], "2", "2026-11-08T04:10:07+00:00", "חדירת כלי טיס עוין אזור קו העימות שומרה היכנסו למרחב המוגן")
        _add(con, off["id"], "3", "2026-11-08T04:22:52+00:00", "עדכון: האירוע הסתיים, השוהים במרחב המוגן יכולים לצאת. אזור קו העימות")
        _add(con, u1["id"], "10", "2026-11-22T10:00:00+00:00", "שריפה בכרמיאל ליד הקניון")
        _add(con, u2["id"], "20", "2026-11-22T10:05:00+00:00", "שריפה בכרמיאל ליד הקניון")          # העתקה מילה במילה
        _add(con, u2["id"], "21", "2026-11-22T10:20:00+00:00", "צוותי כיבוי פועלים בשריפה בכרמיאל")   # דיווח עצמאי
        _add(con, u1["id"], "11", "2026-11-22T18:00:00+00:00", "שריפה חדשה בכרמיאל")                  # אחרי 8 שעות: אירוע חדש
        _add(con, u1["id"], "12", "2026-11-22T11:00:00+00:00", "תאונה בראשון לציון")                 # במרכז הארץ
        assert build_events(con) == 4
        evs = repo.list_events(con)
    alert = next(e for e in evs if e["title"] == "אירוע ביטחוני בזרעית ועוד מקום אחד")
    assert [r["relation"] for r in alert["reports"]] == ["report", "report", "update"]
    assert alert["status"] == "ended" and alert["verification"] == "official"
    fires = sorted((e for e in evs if e["event_type"] == "fire"), key=lambda e: e["first_reported_at"])
    assert [r["relation"] for r in fires[0]["reports"]] == ["report", "copy", "report"]
    assert fires[0]["verification"] == "multi_source" and fires[0]["independent_sources"] == 2
    assert fires[1]["verification"] == "single_source"
    assert fires[0]["location"]["name"] == "כרמיאל" and fires[0]["location"]["lat"] is not None


def test_hospital_is_not_event_location():
    a = analyze("דוברות מד\"א: התקבל דיווח במוקד 101 במרחב אשר על פצוע מאירוע אלימות בסח'נין. "
                "הפצוע פונה לבית החולים לגליל בנהריה במצב בינוני")
    assert a["location"] == "סכנין" and "נהריה" not in a["places"]
    assert analyze("תאונה בכביש 85, הפצועים פונו לבית החולים זיו בצפת")["location"] == "כביש 85"


def test_hospital_phrasings():
    for tail in ["ומפנים אותו למרכז הרפואי לגליל בנהריה", "ומפנים לבי\"ח הגליל בנהריה", "פונה לביה״ח בנהריה",
                 "והועבר למיון המרכז הרפואי בנהריה"]:
        a = analyze(f"דוברות מד\"א: פצוע מאירוע אלימות בסח'נין. חובשים מעניקים טיפול {tail}")
        assert a["places"] == ["סכנין"], tail


def test_lebanon_event_is_not_a_northern_event():
    a = analyze("לפי דיווחים ערביים, כוחותינו מבצעים כעת פיצוצי מבנים בכפר השיעי בני חיאן, סמוך לגבול הצפון")
    assert not a["relevant"] and a["places"] == []
    # אבל אם מוזכר יישוב ישראלי ספציפי, זה כן אירוע בצפון
    a = analyze("חיזבאללה שיגר רקטות לעבר קריית שמונה, נפילה בשטח פתוח")
    assert a["relevant"] and a["location"] == "קריית שמונה"


def test_genre_report_vs_article():
    from app.analyze import analyze
    # מאמר דעה שמזכיר מקום וסוג אירוע: לא אירוע
    a = analyze("התבוסה הישראלית בחזית השמינית: הנזק העצום לתדמית. לדעתי מה שקרה בצפת אחרי ירי הרקטות מוכיח זאת")
    assert (a["genre"], a["relevant"]) == ("opinion", False)
    # מעצר וסיכומים: לא אירוע חי
    assert analyze("צעיר חשוד במעורבות בתאונת פגע וברח נעצר בראשון לציון")["genre"] == "followup"
    assert analyze("שוטרי מחוז ש\"י סיכלו בשבוע החולף גניבת 29 כלי רכב בירושלים")["genre"] == "followup"
    assert analyze("בהמשך לאירוע השריפה שאירע לפנות בוקר בכרמיאל, אנו מבקשים להביע תמיכה")["genre"] == "followup"
    assert analyze("ח\"כ תקף את השר אחרי ירי הרקטות לשדרות, ועדת החוץ והביטחון תתכנס")["genre"] == "politics"
    assert analyze("לקראת סוף השבוע אנו מבקשים לרענן הנחיות ביטחון לתושבי כרמיאל")["genre"] == "guidance"
    # דיווח חי נשאר דיווח גם כשיש בו מילה של סיכום
    a = analyze("לפני זמן קצר: מחבל ביצע ירי בצומת גולני ונעצר. כוחות בזירה")
    assert (a["genre"], a["relevant"]) == ("report", True)
    a = analyze("דוברות מד\"א: בשעה 21:55 התקבל דיווח על תאונת דרכים בכביש 89 סמוך לצפת")
    assert (a["genre"], a["relevant"]) == ("report", True)
    assert analyze("כפר תבור שריפה")["relevant"]          # הודעה קצרה בלי סימנים = דיווח


def test_same_source_different_towns_are_separate_events(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    from app.db import connect, init_db
    from app.events_builder import build_events
    from app.seed import run_seed
    from app import repo
    init_db(); run_seed()
    with connect() as con:
        s = repo.create_source(con, repo.SourceIn(name="כבאות", kind="telegram", address="https://t.me/fire_x", enabled=True), "t")
        _add(con, s["id"], "1", "2026-11-23T00:01:00+00:00", "נתניה פרישמן שריפת רכב")
        _add(con, s["id"], "2", "2026-11-23T00:05:00+00:00", "טירה שריפת רכב ברחוב הראשי")
        _add(con, s["id"], "3", "2026-11-23T00:09:00+00:00", "נתניה שריפה ברחוב דוד, כוחות כיבוי בדרך")
        assert build_events(con) == 2


def test_recap_attaches_to_original_and_does_not_look_new(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    from app.db import connect, init_db
    from app.events_builder import build_events
    from app.seed import run_seed
    from app import repo
    init_db(); run_seed()
    with connect() as con:
        s = repo.create_source(con, repo.SourceIn(name="כבאות", kind="telegram", address="https://t.me/fire_y", enabled=True), "t")
        _add(con, s["id"], "1", "2026-11-23T00:01:00+00:00", "נתניה פרישמן שריפת רכב")          # 02:01 בלילה: חי
        _add(con, s["id"], "2", "2026-11-23T07:20:00+00:00",
             "עדכוני חדשות נתניה: הלילה ברחוב דוד פרישמן בעיר רכב עלה באש, כוחות הכיבוי פעלו בזירה")  # 09:20: סיכום
        _add(con, s["id"], "3", "2026-11-23T07:30:00+00:00", "אמש פרצה שריפה בבית בטירה")        # סיכום בלי אירוע מקורי
        _add(con, s["id"], "4", "2026-11-22T23:30:00+00:00", "הלילה: שריפה בכרמיאל, כוחות בדרך") # 01:30: חי
        assert build_events(con) == 2
        evs = {e["title"]: e for e in repo.list_events(con)}
        n = evs["שריפה בנתניה"]
        assert n["updated_at"].startswith("2026-11-23T00:01") and n["status"] == "ended"
        assert [r["relation"] for r in n["reports"]] == ["report", "recap"]
        assert "שריפה בכרמיאל" in evs


def test_only_field_reports():
    from app.analyze import analyze, genre
    long_oped = ("התבוסה הישראלית בחזית השמינית: הנזק לתדמית. " + "מילה " * 200 +
                 "גם בזירה הבינלאומית, אחרי ירי הרקטות לצפת, אנחנו מפסידים")
    assert genre(long_oped) == "opinion"
    assert genre('בנט: ״הטרור היהודי הבזוי נוגד את ערכי המוסר. הוא ממיט נזק על מדינת ישראל״ אחרי הפיגוע בשומרון') == "politics"
    assert genre("ראש הממשלה ביקר הבוקר בזירת השריפה בכרמיאל ונפגש עם התושבים") == "politics"
    assert genre('לבנון: תחנת הרדיו "לבנון החופשית" פרסמה סרטון על יחידת הסייבר של חיזבאללה') == "abroad"
    assert genre('דוברות המשטרה: שוטרי תחנת חולון פתחו בחקירת חשד להשלכת פריט אמל"ח ברחוב סנהדרין') == "followup"
    assert genre("סיכום חדשות הלילה • צעיר נפצע קשה באירוע ירי בקריית מוצקין") == "followup"
    assert genre("ראיון " + "מילה " * 160 + "על התאונה בכביש 6") == "article"
    for t in ["כפר תבור שריפה", "🔴 צבע אדום (23/11/2026): 07:34: • קו העימות: אבן מנחם, שתולה (15 שניות)",
              'דוברות מד"א: בשעה 08:30 התקבל דיווח במוקד 101 על תאונת דרכים בכביש 65 סמוך לצומת מי עמי',
              "הפגנה בירושלים: רחוב בר אילן נחסם, המשטרה מפזרת בכוח",
              "אור עקיבא שריפה על גג בניין דוד שמש צוות בדרך"]:
        assert genre(t) == "report", t
    a = analyze("כוחות הצלה הוזעקו בשעה 20:25 לרחוב עזרא בבני ברק, אישה כבת 70 נפלה במדרכה וסבלה מחבלות בראש")
    assert a["type"] == "medical"


def test_fire_service_accident_is_accident():
    a = analyze("דוברות כבאות והצלה לישראל | מחוז חוף תאונת דרכים קשה בכביש 6 לכיוון צפון לוחמי האש מתחנת חדרה חילצו לכוד ממשאית")
    assert a["type"] == "accident" and a["severity"] == 2
    assert analyze("אור עקיבא שריפה על גג בניין דוד שמש צוות בדרך")["type"] == "fire"


def test_every_type_has_title_and_is_allowed():
    from app import analyze, events_builder, repo
    types = {n for n, _ in analyze.TYPE_RULES}
    assert types <= set(events_builder.TITLE) and types <= set(repo.EVENT_TYPES)


def test_cyber_warnings():
    a = analyze("אזהרה לציבור. חשד לניסיון הונאה! בשעות האחרונות מופצות הודעות SMS המתחזות להודעות מטעם אגף הגביה של עיריית קריית שמונה")
    assert (a["type"], a["places"], a["severity"], a["relevant"]) == ("cyber", ["קריית שמונה"], 2, True)
    a = analyze("מערך הסייבר: הודעת SMS מתחזה לפיקוד העורף מופצת לאלפי ישראלים, אל תלחצו על הקישור")
    assert (a["type"], a["location"], a["severity"], a["relevant"]) == ("cyber", "כל הארץ", 3, True)
    assert len(a["regions"]) == 10


def test_ims_weather_warnings():
    a = analyze("ים גבוה ומסוכן לרחצה עודכן ב-23/11 09:33. עדכון: אזהרה צהובה על ים גבוה ומסוכן לרחצה בים התיכון ב-23/11 מ-10 עד 22.")
    assert (a["type"], a["location"], a["severity"], a["relevant"]) == ("weather", "חופי הים התיכון", 1, True)
    a = analyze("אזהרה כתומה: גשם עז וסכנת שיטפונות בנחלים במדבר יהודה ובערבה")
    assert (a["type"], a["severity"]) == ("weather", 2)
    a = analyze("אזהרה אדומה: עומס חום כבד ביותר")
    assert (a["type"], a["location"], a["severity"]) == ("weather", "כל הארץ", 3)


def test_no_false_weather_or_national():
    a = analyze('כוכבת "הלוטוס הלבן" ביקרה את ישראל - ומגלמת ניצולת שואה')
    assert a["type"] != "weather" and not a["relevant"]
    assert analyze("כתבה: מה קרה בסערה של 1992 ולמה זה לא יחזור")["places"] == []
    assert analyze("שלג ירד הבוקר בחרמון")["type"] == "weather"


def test_obituary_is_not_an_event():
    from app.analyze import genre
    a = analyze("הלך לעולמו הרב יצחק לוי בגיל 79, לשעבר ראש המפד״ל, שנים אחרי ששכל את בתו איילת השחר בפיגוע")
    assert (a["genre"], a["relevant"]) == ("obituary", False)
    assert genre("ברוך דיין האמת. בצער רב אנו מודיעים על פטירתו של חבר הקיבוץ. ההלוויה תתקיים מחר בכפר בלום") == "obituary"
    # דיווח על הרוג באירוע עדיין דיווח
    assert genre("גבר כבן 40 נהרג באירוע אלימות בנתיבות, פראמדיקים של מד\"א קבעו את מותו במקום") == "report"


def test_public_health():
    a = analyze("משרד הבריאות מודיע: חיידק ליסטריה התגלה בשני מוצרי גלידה; החברה מבצעת ריקול נרחב, הציבור מתבקש להימנע מצריכת המוצרים")
    assert (a["type"], a["location"], a["severity"], a["relevant"]) == ("health", "כל הארץ", 2, True)
    a = analyze("משרד הבריאות: תושבי צפת מתבקשים להרתיח את מי השתייה עד להודעה חדשה")
    assert (a["type"], a["location"], a["severity"]) == ("health", "צפת", 3)


def test_rabies_is_not_critical():
    a = analyze("משרד הבריאות: שוב תן נגוע בכלבת אותר בכניסה ליישוב ניר יפה שבגלבוע")
    assert (a["type"], a["severity"]) == ("health", 2)
