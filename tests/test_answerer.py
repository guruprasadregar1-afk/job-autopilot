import pytest
from src.answerer import FormAnswerer, format_numeric_digits_only

def test_format_numeric_digits_only():
    # Plain integer
    assert format_numeric_digits_only(1500000) == "1500000"
    assert format_numeric_digits_only("1500000") == "1500000"
    
    # Formatted with commas
    assert format_numeric_digits_only("15,00,000") == "1500000"
    assert format_numeric_digits_only("25,00,000") == "2500000"
    
    # LPA / Lakh notation
    assert format_numeric_digits_only("15 LPA") == "1500000"
    assert format_numeric_digits_only("25 LPA") == "2500000"
    assert format_numeric_digits_only("15 Lakhs") == "1500000"
    assert format_numeric_digits_only("25 Lac") == "2500000"

    # Currency symbols & suffix
    assert format_numeric_digits_only("₹ 15,00,000 /-") == "1500000"
    assert format_numeric_digits_only("INR 2500000") == "2500000"

    # Notice period with days suffix
    assert format_numeric_digits_only("60 days") == "60"
    assert format_numeric_digits_only("60") == "60"

    # Ambiguous inputs: MUST return UNKNOWN, never round or strip
    assert format_numeric_digits_only("4.5") == "UNKNOWN"
    assert format_numeric_digits_only("4.5 years") == "UNKNOWN"
    assert format_numeric_digits_only("3.2") == "UNKNOWN"
    assert format_numeric_digits_only("3.2 years") == "UNKNOWN"
    assert format_numeric_digits_only("five years") == "UNKNOWN"
    assert format_numeric_digits_only("random text") == "UNKNOWN"

    # Edge cases
    assert format_numeric_digits_only(None) == "UNKNOWN"
    assert format_numeric_digits_only("") == "UNKNOWN"

def test_direct_answer_matching_from_yaml(tmp_path):
    fake_answers = tmp_path / "answers.yaml"
    fake_answers.write_text("""
answers:
  - patterns:
      - "notice period"
      - "availability"
    value: "60 days"
    numeric_value: 60
  - patterns:
      - "current ctc"
      - "current salary"
    value: "1500000"
    numeric_value: 1500000
  - patterns:
      - "expected ctc"
      - "expected salary"
      - "expected annual compensation"
    value: "2500000"
    numeric_value: 2500000
  - patterns:
      - "postal code"
      - "zip code"
      - "pincode"
      - "pin code"
    value: "560001"
    numeric_value: 560001
  - patterns:
      - "total years of experience"
      - "overall experience"
    value: "4.5"
    numeric_value: 4.5
""", encoding="utf-8")
    fake_profile = tmp_path / "profile.yaml"
    fake_profile.write_text("personal:\n  current_city: 'Bengaluru'\n", encoding="utf-8")
    fake_settings = tmp_path / "settings.yaml"
    fake_settings.write_text("llm:\n  cli_command: 'claude.cmd'\n", encoding="utf-8")

    answerer = FormAnswerer(answers_path=fake_answers, profile_path=fake_profile, settings_path=fake_settings)

    # Notice period (numeric field -> digits only)
    ans_notice = answerer.answer_question("Please enter your notice period in days", field_type="number")
    assert ans_notice == "60"
    assert ans_notice.isdigit()

    # Current CTC (numeric field -> digits only)
    ans_ctc = answerer.answer_question("What is your current CTC in INR?", field_type="number")
    assert ans_ctc == "1500000"
    assert ans_ctc.isdigit()

    # Expected CTC (numeric field -> digits only)
    ans_exp_ctc = answerer.answer_question("What is your expected annual compensation?", field_type="number")
    assert ans_exp_ctc == "2500000"
    assert ans_exp_ctc.isdigit()

    # Postal code
    ans_pin = answerer.answer_question("Please provide your postal code / zip code", field_type="text")
    assert ans_pin == "560001"

    # Total experience (overall experience -> 4.5)
    ans_exp = answerer.answer_question("What is your total years of experience?", field_type="text")
    assert ans_exp == "4.5"

    # Per-skill experience (React) returns UNKNOWN -> NEEDS_INPUT
    ans_react = answerer.answer_question("How many years of experience in React do you have?", field_type="text")
    assert ans_react == "UNKNOWN"

def test_dropdown_option_matching():
    answerer = FormAnswerer()
    options = ["15 days or less", "1 month", "2 months", "3 months"]
    ans = answerer.answer_question("What is your notice period?", field_type="dropdown", options=options)
    # 60 days maps to 2 months
    assert ans in options

def test_unknown_question_handling():
    answerer = FormAnswerer()
    # Mocking unknown question without calling Claude
    ans = answerer.find_direct_answer("Do you hold an active secret security clearance from the US DoD?")
    assert ans is None

def test_experience_phrasing_rules():
    answerer = FormAnswerer()

    # 1. Total/overall/professional experience general phrasing returns 4.5
    ans_total_prof = answerer.find_direct_answer("total years of professional experience", field_type="text")
    assert ans_total_prof == "4.5"
    assert answerer.answer_question("total years of professional experience", field_type="text") == "4.5"

    # 2. Specific skill: Java -> UNKNOWN / None
    assert answerer.find_direct_answer("years of experience with Java", field_type="number") is None
    assert answerer.answer_question("years of experience with Java", field_type="number") == "UNKNOWN"

    # 3. Specific skill: AWS -> UNKNOWN / None
    assert answerer.find_direct_answer("years of experience with AWS", field_type="number") is None
    assert answerer.find_direct_answer("with AWS", field_type="number") is None
    assert answerer.answer_question("with AWS", field_type="number") == "UNKNOWN"

    # 4. Specific skill: React -> UNKNOWN / None
    assert answerer.find_direct_answer("years of experience with React", field_type="number") is None
    assert answerer.find_direct_answer("with React", field_type="number") is None
    assert answerer.answer_question("with React", field_type="number") == "UNKNOWN"

    # 5. Specific skill: Full Stack Development -> UNKNOWN / None
    assert answerer.find_direct_answer("years of experience with Full Stack Development", field_type="number") is None
    assert answerer.find_direct_answer("with Full Stack Development", field_type="number") is None
    assert answerer.find_direct_answer("years with Full Stack Development", field_type="number") is None
    assert answerer.answer_question("with Full Stack Development", field_type="number") == "UNKNOWN"

def test_user_approved_screening_answers():
    answerer = FormAnswerer()

    # 1. total work experience
    assert answerer.find_direct_answer("total work experience", field_type="text") == "4.5"

    # 2. JavaScript proficiency
    js_text = "Yes, I have professional experience developing applications using JavaScript, including backend services and frontend functionality."
    assert answerer.find_direct_answer("Are you proficient in JavaScript?", field_type="textarea") == js_text
    assert answerer.find_direct_answer("Are you proficient in JavaScript?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you proficient in JavaScript?", field_type="radio", options=["No", "Yes"]) == "Yes"

    # 3. TypeScript proficiency
    ts_text = "Yes, I have experience using TypeScript to develop and maintain application code."
    assert answerer.find_direct_answer("Are you proficient in TypeScript?", field_type="textarea") == ts_text
    assert answerer.find_direct_answer("Are you proficient in TypeScript?", field_type="dropdown", options=["Yes", "No"]) == "Yes"

    # 4. Node.js experience
    node_text = "Yes, I have experience developing backend services and APIs using Node.js."
    assert answerer.find_direct_answer("Are you experienced with Node.js?", field_type="textarea") == node_text
    assert answerer.find_direct_answer("Are you experienced with Node.js?", field_type="dropdown", options=["No", "Yes"]) == "Yes"
    assert answerer.find_direct_answer("are you experienced with nodejs", field_type="dropdown", options=["Yes", "No"]) == "Yes"

    # 5. Express.js familiarity
    express_text = "Yes, I have experience working with Express.js for backend API development."
    assert answerer.find_direct_answer("Are you familiar with Express.js?", field_type="textarea") == express_text
    assert answerer.find_direct_answer("Are you familiar with Express.js?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("are you familiar with expressjs", field_type="dropdown", options=["Yes", "No"]) == "Yes"

    # 6. React familiarity
    react_text = "Yes, I have experience developing frontend interfaces and integrating APIs using React."
    assert answerer.find_direct_answer("Are you familiar with React?", field_type="textarea") == react_text
    assert answerer.find_direct_answer("Are you familiar with React?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("are you familiar with reactjs", field_type="dropdown", options=["Yes", "No"]) == "Yes"

    # 7. Next.js familiarity
    next_text = "Yes, I have experience working with Next.js applications, including frontend development, routing, responsive layouts, and API integration."
    assert answerer.find_direct_answer("Are you familiar with Next.js?", field_type="textarea") == next_text
    assert answerer.find_direct_answer("Are you familiar with Next.js?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("are you familiar with nextjs", field_type="dropdown", options=["Yes", "No"]) == "Yes"

    # 8. MongoDB experience (No disclaimer; Yes for dropdown)
    mongo_text = "I have worked with MongoDB as part of full-stack application development."
    assert answerer.find_direct_answer("Are you experienced with MongoDB?", field_type="textarea") == mongo_text
    assert answerer.find_direct_answer("Are you experienced with MongoDB?", field_type="dropdown", options=["Yes", "No"]) == "Yes"

    # 9. Hybrid model (Yes for dropdown/radio/checkbox; full sentence for textarea)
    hybrid_text = "Yes, I am comfortable working in a hybrid model and collaborating with the team both remotely and in person."
    assert answerer.find_direct_answer("Are you comfortable working with a hybrid model?", field_type="textarea") == hybrid_text
    assert answerer.find_direct_answer("Are you comfortable working with a hybrid model?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you comfortable working with a hybrid model?", field_type="radio", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you comfortable working with a hybrid model?", field_type="checkbox") == "Yes"

    # 10. Team collaboration (Yes for dropdown/radio/checkbox; full sentence for textarea)
    team_text = "Yes, I am comfortable collaborating with developers and other stakeholders, discussing technical requirements, and working together to deliver application features."
    assert answerer.find_direct_answer("Are you comfortable working in a team?", field_type="textarea") == team_text
    assert answerer.find_direct_answer("Are you comfortable working in a team?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you comfortable working in a team?", field_type="radio", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you comfortable working in a team?", field_type="checkbox") == "Yes"

    # 11. User-approved questions (Work authorization in India -> Yes, Visa sponsorship -> No, Remote/Onsite -> Yes)
    assert answerer.find_direct_answer("do you require visa sponsorship", field_type="dropdown", options=["Yes", "No"]) == "No"
    assert answerer.find_direct_answer("will you require visa sponsorship", field_type="dropdown", options=["Yes", "No"]) == "No"
    assert answerer.find_direct_answer("Do you require visa sponsorship?", field_type="dropdown", options=["Yes", "No"]) == "No"
    assert answerer.find_direct_answer("Do you require visa sponsorship?", field_type="radio", options=["Yes", "No"]) == "No"
    assert answerer.find_direct_answer("Are you legally authorized to work in India?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you authorized to work in India?", field_type="radio", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you comfortable working remotely?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you comfortable working on-site?", field_type="radio", options=["Yes", "No"]) == "Yes"

    # 12. Relocation questions - user approved (India only, "Yes" for radio/dropdown/checkbox)
    assert answerer.find_direct_answer("Are you willing to relocate?", field_type="dropdown", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Are you open to relocation?", field_type="radio", options=["Yes", "No"]) == "Yes"
    assert answerer.find_direct_answer("Willing to relocate", field_type="checkbox") == "Yes"

    # Relocation naming countries outside India strictly returns None (NEEDS_INPUT)
    assert answerer.find_direct_answer("Are you willing to relocate to Germany?", field_type="dropdown", options=["Yes", "No"]) is None
    assert answerer.find_direct_answer("Are you willing to relocate to the United States?", field_type="radio", options=["Yes", "No"]) is None
    assert answerer.find_direct_answer("Are you open to relocation to Canada?", field_type="dropdown", options=["Yes", "No"]) is None

    # Unapproved questions strictly return None (NEEDS_INPUT)
    assert answerer.find_direct_answer("Gender", field_type="dropdown", options=["Male", "Female"]) is None
    assert answerer.find_direct_answer("Do you have a disability?", field_type="dropdown", options=["Yes", "No"]) is None
    assert answerer.find_direct_answer("Veteran status", field_type="dropdown", options=["Yes", "No"]) is None


def test_skill_entries_exact_matching_and_negative_guards():
    answerer = FormAnswerer()

    # 1. "familiar with React Native" must NOT match "familiar with React" -> UNKNOWN
    assert answerer.find_direct_answer("familiar with React Native") is None
    assert answerer.answer_question("Are you familiar with React Native?") == "UNKNOWN"

    # 2. "Node-RED" must NOT match Node.js -> UNKNOWN
    assert answerer.find_direct_answer("Are you experienced with Node-RED?") is None
    assert answerer.answer_question("Are you experienced with Node-RED?") == "UNKNOWN"

    # 3. "next steps in the hiring process" must NOT match Next.js -> UNKNOWN
    assert answerer.find_direct_answer("Are you familiar with next steps in the hiring process?") is None
    assert answerer.find_direct_answer("next steps in the hiring process") is None

    # 4. "years of experience with React" must NOT match React proficiency or return 4.5 -> UNKNOWN
    assert answerer.find_direct_answer("years of experience with React") is None
    assert answerer.answer_question("years of experience with React") == "UNKNOWN"

    # 5. Number fields on skill questions must return UNKNOWN / None (no duration applied)
    assert answerer.find_direct_answer("Are you familiar with React?", field_type="number") is None
    assert answerer.find_direct_answer("How many years of experience with React?", field_type="number") is None

    # 6. Hybrid & Teamwork exact_match guards: substrings must NOT match
    assert answerer.find_direct_answer("Are you experienced with hybrid mobile application development?") is None
    assert answerer.find_direct_answer("Do you have experience managing a team?") is None
    assert answerer.answer_question("Are you experienced with hybrid mobile application development?") == "UNKNOWN"
    assert answerer.answer_question("Do you have experience managing a team?") == "UNKNOWN"


def test_linkedin_real_strings_with_punctuation_and_normalization():
    answerer = FormAnswerer()

    real_questions = [
        ("Are you experienced with Node.js?", "are you experienced with nodejs", "Yes"),
        ("Are you familiar with Next.js?", "are you familiar with nextjs", "Yes"),
        ("Are you proficient in JavaScript?", "are you proficient in javascript", "Yes"),
        ("Are you familiar with Express.js?", "are you familiar with expressjs", "Yes"),
        ("Are you familiar with React?", "are you familiar with react", "Yes"),
        ("Are you proficient in TypeScript?", "are you proficient in typescript", "Yes"),
        ("Are you experienced with MongoDB?", "are you experienced with mongodb", "Yes"),
    ]

    for q_str, expected_norm, expected_val in real_questions:
        norm_output = answerer.normalize(q_str)
        assert norm_output == expected_norm
        # Dropdown returns "Yes"
        assert answerer.find_direct_answer(q_str, field_type="dropdown", options=["Yes", "No"]) == expected_val
        # Radio returns "Yes"
        assert answerer.find_direct_answer(q_str, field_type="radio", options=["No", "Yes"]) == expected_val
        # Checkbox returns "Yes"
        assert answerer.find_direct_answer(q_str, field_type="checkbox") == expected_val
        # Textarea returns descriptive sentence without MongoDB disclaimer
        ta_val = answerer.find_direct_answer(q_str, field_type="textarea")
        assert ta_val is not None and len(ta_val) > 10
        assert "My specific level of expertise should be verified against my resume" not in ta_val


def test_linkedin_url_answer_and_punctuation_variants():
    answerer = FormAnswerer()
    expected_url = "https://www.linkedin.com/in/guru-prasad-769b99227324"

    variants = [
        "LinkedIn Profile",
        "LinkedIn Profile:",
        "LinkedIn Profile*",
        "LinkedIn Profile URL",
        "LinkedIn Profile URL:",
        "Your LinkedIn Profile URL",
        "your linkedin profile url",
        "linkedin profile link",
        "LinkedIn Profile - URL",
    ]

    for q in variants:
        ans_text = answerer.find_direct_answer(q, field_type="text")
        assert ans_text == expected_url, f"Failed for variant '{q}': got '{ans_text}'"

        ans_url = answerer.find_direct_answer(q, field_type="url")
        assert ans_url == expected_url, f"Failed for URL field_type '{q}': got '{ans_url}'"

    # Fill ONLY text/URL inputs: radio/dropdown/checkbox/number must return None
    assert answerer.find_direct_answer("LinkedIn Profile", field_type="number") is None
    assert answerer.find_direct_answer("LinkedIn Profile", field_type="radio") is None
    assert answerer.find_direct_answer("LinkedIn Profile", field_type="dropdown", options=["Yes", "No"]) is None
    assert answerer.find_direct_answer("LinkedIn Profile", field_type="checkbox") is None

    # Profile URLs stay denylisted for navigation
    from src.policy import PolicyEngine, CriticalPolicyViolationError, PolicyBlockError
    with pytest.raises((CriticalPolicyViolationError, PolicyBlockError)):
        PolicyEngine.validate_navigation(expected_url)


def test_website_portfolio_answer_and_punctuation_variants():
    answerer = FormAnswerer()
    expected_url = "https://guruprasad-dev-portfolio.vercel.app"

    variants = [
        "Website",
        "Website:",
        "Website*",
        "Website URL",
        "Website URL:",
        "Portfolio",
        "Portfolio:",
        "Portfolio URL",
        "Personal Website",
        "personal website",
    ]

    for q in variants:
        ans_text = answerer.find_direct_answer(q, field_type="text")
        assert ans_text == expected_url, f"Failed for variant '{q}': got '{ans_text}'"

        ans_url = answerer.find_direct_answer(q, field_type="url")
        assert ans_url == expected_url, f"Failed for URL field_type '{q}': got '{ans_url}'"

    # Fill ONLY text/URL inputs: radio/dropdown/checkbox/number must return None
    assert answerer.find_direct_answer("Website", field_type="number") is None
    assert answerer.find_direct_answer("Website", field_type="radio") is None
    assert answerer.find_direct_answer("Website", field_type="dropdown", options=["Yes", "No"]) is None
    assert answerer.find_direct_answer("Website", field_type="checkbox") is None


def test_last_working_date_computation_and_rollovers():
    from datetime import datetime, timezone, timedelta
    from src.answerer import compute_last_working_date

    kolkata_tz = timezone(timedelta(hours=5, minutes=30))

    # 1. Year rollover: 2026-10-19 + 75 days -> 2027-01-02
    base_2026 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=kolkata_tz)
    res_default = compute_last_working_date(base_date=base_2026)
    assert res_default == "02 Jan 2027", f"Expected '02 Jan 2027', got '{res_default}'"

    # Formats with year rollover date
    assert compute_last_working_date(base_date=base_2026, format_hint="Please enter DD/MM/YYYY") == "02/01/2027"
    assert compute_last_working_date(base_date=base_2026, format_hint="YYYY-MM-DD") == "2027-01-02"
    assert compute_last_working_date(base_date=base_2026, format_hint="MM/DD/YYYY") == "01/02/2027"
    assert compute_last_working_date(base_date=base_2026, format_hint="") == "02 Jan 2027"

    # 2. Month rollover: 2026-03-01 + 75 days -> 2026-05-15
    base_mar = datetime(2026, 3, 1, 10, 0, 0, tzinfo=kolkata_tz)
    res_mar = compute_last_working_date(base_date=base_mar)
    assert res_mar == "15 May 2026", f"Expected '15 May 2026', got '{res_mar}'"

    # 3. Leap year rollover: 2028-01-10 + 75 days -> 2028-03-25 (Feb 2028 has 29 days)
    base_leap = datetime(2028, 1, 10, 10, 0, 0, tzinfo=kolkata_tz)
    res_leap = compute_last_working_date(base_date=base_leap)
    assert res_leap == "25 Mar 2028", f"Expected '25 Mar 2028', got '{res_leap}'"


def test_last_working_date_question_variants_and_text_only():
    answerer = FormAnswerer()

    variants = [
        "What is your last working date?",
        "What is your last working date?*",
        "what is your last working date",
        "Last working date",
        "last working date",
        "Last working date*",
        "Last working date:*",
    ]

    for q in variants:
        ans = answerer.find_direct_answer(q, field_type="text")
        assert ans is not None, f"Expected answer for '{q}', got None"
        assert len(ans.split()) == 3, f"Expected 'DD Mon YYYY' format for '{q}', got '{ans}'"

    # Text inputs only: numeric, radio, dropdown, checkbox return None
    assert answerer.find_direct_answer("What is your last working date?", field_type="number") is None
    assert answerer.find_direct_answer("What is your last working date?", field_type="radio") is None
    assert answerer.find_direct_answer("What is your last working date?", field_type="dropdown", options=["Immediate", "30 days"]) is None
    assert answerer.find_direct_answer("What is your last working date?", field_type="checkbox") is None


def test_notice_period_and_profile_consistency_75_days():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent

    # Check answers.yaml
    answers_data = yaml.safe_load(open(root / "config" / "answers.yaml", encoding="utf-8"))
    notice_entries = [
        e for e in answers_data.get("answers", [])
        if any("notice period" in p for p in e.get("patterns", []))
    ]
    assert len(notice_entries) == 1
    assert notice_entries[0]["value"] == "75 days"
    assert notice_entries[0]["numeric_value"] == 75

    # Check profile.yaml
    profile_data = yaml.safe_load(open(root / "config" / "profile.yaml", encoding="utf-8"))
    assert profile_data.get("compensation_and_notice", {}).get("notice_period_days") == 75


def test_item_1_positive_answers_matching():
    """
    Verifies Item 2 positive test requirements:
    1. Real labels with asterisks: 'How many years of relevant work experience do you have?*' -> dropdown selects '3-4 years'.
    2. 'Do you have a Bachelor's degree?' -> 'Yes'.
    3. Dropdown with 'BCA' -> 'BCA'.
    4. Dropdown with 'Professional' -> 'Professional'.
    """
    answerer = FormAnswerer()

    # 1. Relevant work experience dropdown
    opts_exp = ["1-2 years", "3-4 years", "5-6 years", "7-10 years", "11+ years"]
    labels_exp = [
        "How many years of relevant work experience do you have?*",
        "how many years of relevant work experience do you have",
        "Years of relevant work experience*",
        "years of relevant work experience",
    ]
    for lbl in labels_exp:
        ans = answerer.find_direct_answer(lbl, field_type="dropdown", options=opts_exp)
        assert ans == "3-4 years", f"Expected '3-4 years' for '{lbl}', got '{ans}'"
        assert answerer.answer_question(lbl, field_type="dropdown", options=opts_exp) == "3-4 years"

    # 2. Bachelor's degree (Yes/No)
    opts_yes_no = ["Yes", "No"]
    labels_bach_yn = [
        "Do you have a Bachelor's degree?",
        "Do you have a Bachelor's degree?*",
        "Have you completed a bachelor's degree?",
        "Do you hold a bachelor's degree",
    ]
    for lbl in labels_bach_yn:
        ans = answerer.find_direct_answer(lbl, field_type="dropdown", options=opts_yes_no)
        assert ans == "Yes", f"Expected 'Yes' for '{lbl}', got '{ans}'"
        assert answerer.find_direct_answer(lbl, field_type="radio", options=opts_yes_no) == "Yes"
        assert answerer.answer_question(lbl, field_type="dropdown", options=opts_yes_no) == "Yes"

    # 3. Bachelor's degree name - user accepted options in order and text input
    # a) Dropdown with ["BCA", "B.Tech", "B.Sc"] selects "BCA"
    opts_bca_drop = ["BCA", "B.Tech", "B.Sc"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts_bca_drop) == "BCA"
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts_bca_drop) == "BCA"

    # b) Dropdown with ["Bachelor of Computer Applications", "B.Tech"] selects "Bachelor of Computer Applications"
    opts_full_name = ["Bachelor of Computer Applications", "B.Tech"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts_full_name) == "Bachelor of Computer Applications"
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts_full_name) == "Bachelor of Computer Applications"

    # c) Text input labelled "Which bachelor's degree do you have?" gets "Bachelor of Computer Applications (BCA)"
    expected_text_deg = "Bachelor of Computer Applications (BCA)"
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="text") == expected_text_deg
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="text") == expected_text_deg
    assert answerer.find_direct_answer("What is your bachelor's degree?", field_type="text") == expected_text_deg
    assert answerer.find_direct_answer("Degree name", field_type="text") == expected_text_deg

    # d) Control labelled just "Bachelor's degree" with options Yes/No selects "Yes" and never "BCA"
    opts_yn = ["Yes", "No"]
    assert answerer.find_direct_answer("Bachelor's degree", field_type="dropdown", options=opts_yn) == "Yes"
    assert answerer.find_direct_answer("Bachelor's degree", field_type="radio", options=opts_yn) == "Yes"
    assert answerer.answer_question("Bachelor's degree", field_type="dropdown", options=opts_yn) == "Yes"
    assert answerer.find_direct_answer("Bachelor's degree", field_type="dropdown", options=opts_yn) != "BCA"

    # 4. English proficiency -> "Professional" (dropdown exact option)
    opts_eng = ["Basic", "Conversational", "Professional", "Native"]
    labels_eng = [
        "English proficiency",
        "English proficiency*",
        "English language proficiency",
        "English language proficiency*",
        "Level of english",
        "Level of English*",
        "English level",
        "Proficiency in english",
    ]
    for lbl in labels_eng:
        ans = answerer.find_direct_answer(lbl, field_type="dropdown", options=opts_eng)
        assert ans == "Professional", f"Expected 'Professional' for '{lbl}', got '{ans}'"
        assert answerer.answer_question(lbl, field_type="dropdown", options=opts_eng) == "Professional"


def test_item_1_negative_answers_unknown_and_needs_input():
    """
    Verifies Item 2 negative test requirements (all must give UNKNOWN -> NEEDS_INPUT):
    1. Years of experience with Java, AWS, React, Python.
    2. 'relevant work experience' as text or number.
    3. 'Do you have a Master's degree?'.
    4. 'What is your highest level of education?'.
    5. 'Field of study'.
    6. English dropdown without 'Professional'.
    7. Degree dropdown with ["B.Tech", "B.Sc Computer Science", "BBA"] -> UNKNOWN.
    8. Degree dropdown with ["BCA (Hons)"] -> UNKNOWN.
    """
    answerer = FormAnswerer()

    # 1. Years of experience with specific technologies -> strictly UNKNOWN / None
    tech_questions = [
        "How many years of experience do you have with Java?",
        "years of experience with Java",
        "How many years of experience do you have with AWS?",
        "years of experience with AWS",
        "How many years of experience do you have with React?",
        "years of experience with React",
        "How many years of experience do you have with Python?",
        "years of experience with Python",
    ]
    for q in tech_questions:
        assert answerer.find_direct_answer(q, field_type="number") is None, f"Expected None for '{q}'"
        assert answerer.answer_question(q, field_type="number") == "UNKNOWN", f"Expected UNKNOWN for '{q}'"
        assert answerer.find_direct_answer(q, field_type="text") is None, f"Expected None for '{q}'"
        assert answerer.answer_question(q, field_type="text") == "UNKNOWN", f"Expected UNKNOWN for '{q}'"

    # 2. 'relevant work experience' as text or number -> strictly UNKNOWN / None (allowed only for dropdown/select)
    rel_exp_questions = [
        "How many years of relevant work experience do you have?",
        "How many years of relevant work experience do you have?*",
        "years of relevant work experience",
        "relevant work experience",
    ]
    for q in rel_exp_questions:
        assert answerer.find_direct_answer(q, field_type="text") is None, f"Expected None for text '{q}'"
        assert answerer.answer_question(q, field_type="text") == "UNKNOWN", f"Expected UNKNOWN for text '{q}'"
        assert answerer.find_direct_answer(q, field_type="number") is None, f"Expected None for number '{q}'"
        assert answerer.answer_question(q, field_type="number") == "UNKNOWN", f"Expected UNKNOWN for number '{q}'"

    # 3. Master's degree -> strictly UNKNOWN / None
    master_questions = [
        "Do you have a Master's degree?",
        "Do you have a Master's degree?*",
        "Have you completed a master's degree?",
        "Which master's degree do you have?",
    ]
    for q in master_questions:
        assert answerer.find_direct_answer(q, field_type="dropdown", options=["Yes", "No"]) is None
        assert answerer.answer_question(q, field_type="dropdown", options=["Yes", "No"]) == "UNKNOWN"
        assert answerer.find_direct_answer(q, field_type="text") is None
        assert answerer.answer_question(q, field_type="text") == "UNKNOWN"

    # 4. Highest level of education -> strictly UNKNOWN / None
    edu_questions = [
        "What is your highest level of education?",
        "What is your highest level of education?*",
        "Highest level of education",
        "Highest education",
    ]
    for q in edu_questions:
        assert answerer.find_direct_answer(q, field_type="dropdown", options=["High School", "Bachelor", "Master", "PhD"]) is None
        assert answerer.answer_question(q, field_type="dropdown", options=["High School", "Bachelor", "Master", "PhD"]) == "UNKNOWN"
        assert answerer.find_direct_answer(q, field_type="text") is None
        assert answerer.answer_question(q, field_type="text") == "UNKNOWN"

    # 5. Field of study, university, grade, graduation year -> strictly UNKNOWN / None
    study_questions = [
        "Field of study",
        "What is your field of study?",
        "University",
        "What university did you attend?",
        "Grade",
        "Graduation year",
    ]
    for q in study_questions:
        assert answerer.find_direct_answer(q, field_type="text") is None
        assert answerer.answer_question(q, field_type="text") == "UNKNOWN"
        assert answerer.find_direct_answer(q, field_type="dropdown", options=["Computer Science", "Information Technology"]) is None
        assert answerer.answer_question(q, field_type="dropdown", options=["Computer Science", "Information Technology"]) == "UNKNOWN"

    # 6. English dropdown without 'Professional'
    # a) Options lacking 'Professional' (Basic/Conversational/Fluent/Native)
    opts_no_prof = ["Basic", "Conversational", "Fluent", "Native"]
    assert answerer.find_direct_answer("English proficiency", field_type="dropdown", options=opts_no_prof) is None
    assert answerer.answer_question("English proficiency", field_type="dropdown", options=opts_no_prof) == "UNKNOWN"

    # b) Options containing only 'Professional working proficiency' (must NOT match or nearest-match 'Professional')
    opts_working_prof = ["Basic", "Conversational", "Professional working proficiency", "Native"]
    assert answerer.find_direct_answer("English proficiency", field_type="dropdown", options=opts_working_prof) is None
    assert answerer.answer_question("English proficiency", field_type="dropdown", options=opts_working_prof) == "UNKNOWN"

    # 7. Degree dropdown with ["B.Tech", "B.Sc Computer Science", "BBA"] -> strictly UNKNOWN / None
    opts_unmatched = ["B.Tech", "B.Sc Computer Science", "BBA"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts_unmatched) is None
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts_unmatched) == "UNKNOWN"
    assert answerer.find_direct_answer("Degree name", field_type="dropdown", options=opts_unmatched) is None
    assert answerer.answer_question("Degree name", field_type="dropdown", options=opts_unmatched) == "UNKNOWN"

    # 8. Degree dropdown with ["BCA (Hons)"] -> strictly UNKNOWN / None (no partial match)
    opts_hons = ["BCA (Hons)"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts_hons) is None
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts_hons) == "UNKNOWN"


def test_bachelors_degree_bare_label_text_input_returns_unknown():
    """A text input labelled 'Bachelor's degree' -> UNKNOWN (NEEDS_INPUT)."""
    answerer = FormAnswerer()
    assert answerer.find_direct_answer("Bachelor's degree", field_type="text") is None
    assert answerer.answer_question("Bachelor's degree", field_type="text") == "UNKNOWN"
    assert answerer.find_direct_answer("Bachelors degree", field_type="text") is None
    assert answerer.answer_question("Bachelors degree", field_type="text") == "UNKNOWN"


def test_bachelors_degree_bare_label_dropdown_bca_btech_not_yes():
    """A dropdown labelled 'Bachelor's degree' with options BCA/B.Tech -> not 'Yes' (NEEDS_INPUT)."""
    answerer = FormAnswerer()
    opts = ["BCA", "B.Tech"]
    ans = answerer.find_direct_answer("Bachelor's degree", field_type="dropdown", options=opts)
    assert ans != "Yes", f"Expected answer not to be 'Yes', got '{ans}'"
    assert ans is None or ans != "Yes"
    q_ans = answerer.answer_question("Bachelor's degree", field_type="dropdown", options=opts)
    assert q_ans != "Yes"
    assert q_ans == "UNKNOWN"


def test_bachelors_degree_bare_label_dropdown_yes_no_returns_yes():
    """A dropdown/radio labelled 'Bachelor's degree' with Yes/No -> 'Yes'."""
    answerer = FormAnswerer()
    opts_yn = ["Yes", "No"]
    assert answerer.find_direct_answer("Bachelor's degree", field_type="dropdown", options=opts_yn) == "Yes"
    assert answerer.answer_question("Bachelor's degree", field_type="dropdown", options=opts_yn) == "Yes"
    assert answerer.find_direct_answer("Bachelor's degree", field_type="radio", options=opts_yn) == "Yes"
    assert answerer.answer_question("Bachelor's degree", field_type="radio", options=opts_yn) == "Yes"
    # Case-insensitive
    opts_lower = ["yes", "no"]
    assert answerer.find_direct_answer("Bachelor's degree", field_type="dropdown", options=opts_lower) == "yes"


def test_bachelors_degree_name_positive_named():
    """Named positive tests for degree name matching and accepted options in order."""
    answerer = FormAnswerer()
    # 1. Dropdown with ["BCA", "B.Tech", "B.Sc"] selects "BCA"
    opts1 = ["BCA", "B.Tech", "B.Sc"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts1) == "BCA"
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts1) == "BCA"

    # 2. Dropdown with ["Bachelor of Computer Applications", "B.Tech"] selects "Bachelor of Computer Applications"
    opts2 = ["Bachelor of Computer Applications", "B.Tech"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts2) == "Bachelor of Computer Applications"
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts2) == "Bachelor of Computer Applications"

    # 3. Text input labelled "Which bachelor's degree do you have?" gets "Bachelor of Computer Applications (BCA)"
    expected_val = "Bachelor of Computer Applications (BCA)"
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="text") == expected_val
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="text") == expected_val


def test_bachelors_degree_name_negative_named():
    """Named negative tests for degree name and education guards (UNKNOWN -> NEEDS_INPUT)."""
    answerer = FormAnswerer()
    # 1. Dropdown with ["B.Tech", "B.Sc Computer Science", "BBA"] -> UNKNOWN
    opts_unmatched = ["B.Tech", "B.Sc Computer Science", "BBA"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts_unmatched) is None
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts_unmatched) == "UNKNOWN"

    # 2. Dropdown with ["BCA (Hons)"] -> UNKNOWN (no partial match)
    opts_hons = ["BCA (Hons)"]
    assert answerer.find_direct_answer("Which bachelor's degree do you have?", field_type="dropdown", options=opts_hons) is None
    assert answerer.answer_question("Which bachelor's degree do you have?", field_type="dropdown", options=opts_hons) == "UNKNOWN"

    # 3. "What is your highest level of education?" -> UNKNOWN
    assert answerer.find_direct_answer("What is your highest level of education?", field_type="text") is None
    assert answerer.answer_question("What is your highest level of education?", field_type="text") == "UNKNOWN"

    # 4. "Do you have a Master's degree?" -> UNKNOWN
    assert answerer.find_direct_answer("Do you have a Master's degree?", field_type="dropdown", options=["Yes", "No"]) is None
    assert answerer.answer_question("Do you have a Master's degree?", field_type="dropdown", options=["Yes", "No"]) == "UNKNOWN"

    # 5. "Field of study" -> UNKNOWN
    assert answerer.find_direct_answer("Field of study", field_type="text") is None
    assert answerer.answer_question("Field of study", field_type="text") == "UNKNOWN"


def test_full_time_start_availability_positive():
    """Tests matching for full-time start availability with accepted options."""
    answerer = FormAnswerer()
    q = "When are you available to start working on a full-time basis?*"

    # 1. Dropdown with 'In 3 months or more'
    opts_standard = ['Immediately', 'Within 1 week', 'Within 2 weeks', 'Within 1 month', 'Within 2 months', 'In 3 months or more']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_standard) == "In 3 months or more"
    assert answerer.answer_question(q, field_type="dropdown", options=opts_standard) == "In 3 months or more"

    # 2. Dropdown with exact 'In 3 months'
    opts_alt = ['Immediately', 'Within 1 month', 'In 3 months']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_alt) == "In 3 months"

    # 3. Text field
    assert answerer.find_direct_answer(q, field_type="text") == "In 3 months or more"


def test_full_time_start_availability_negative():
    """Tests strict matching: when 3 months option is absent or question differs -> UNKNOWN."""
    answerer = FormAnswerer()
    q = "When are you available to start working on a full-time basis?*"

    # 1. Options lacking 3 months -> None / UNKNOWN (no rounding/nearest)
    opts_no_match = ['Immediately', 'Within 1 week', 'Within 2 weeks', 'Within 1 month']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_no_match) is None
    assert answerer.answer_question(q, field_type="dropdown", options=opts_no_match) == "UNKNOWN"

    # 2. Unrelated availability question -> UNKNOWN
    assert answerer.find_direct_answer("Are you available to work on weekends?", field_type="text") is None
    assert answerer.answer_question("Are you available to work on weekends?", field_type="text") == "UNKNOWN"


def test_resigned_from_current_employer_positive():
    """Tests matching for resignation from current employer (Yes/No)."""
    answerer = FormAnswerer()
    q = "Have you resigned from your current employer?*"

    # 1. Dropdown with placeholder and Yes/No
    opts_with_ph = ['Select an option', 'Yes', 'No']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_with_ph) == "No"
    assert answerer.answer_question(q, field_type="dropdown", options=opts_with_ph) == "No"

    # 2. Dropdown with clean Yes/No
    opts_clean = ['Yes', 'No']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_clean) == "No"

    # 3. Radio with Yes/No
    assert answerer.find_direct_answer(q, field_type="radio", options=opts_clean) == "No"


def test_resigned_from_current_employer_negative():
    """Tests strict matching: non-Yes/No options or disallowed field types return None / UNKNOWN."""
    answerer = FormAnswerer()
    q = "Have you resigned from your current employer?*"

    # 1. Dropdown with options that are not Yes/No
    opts_non_standard = ['Yes', 'In Progress']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_non_standard) is None
    assert answerer.answer_question(q, field_type="dropdown", options=opts_non_standard) == "UNKNOWN"

    # 2. Text input -> UNKNOWN
    assert answerer.find_direct_answer(q, field_type="text") is None
    assert answerer.answer_question(q, field_type="text") == "UNKNOWN"

    # 3. Unrelated resignation question -> UNKNOWN
    assert answerer.find_direct_answer("Why did you resign from your last role?", field_type="text") is None
    assert answerer.answer_question("Why did you resign from your last role?", field_type="text") == "UNKNOWN"


def test_desired_annual_compensation_range_positive():
    """Tests matching for desired annual compensation range question with accepted options."""
    answerer = FormAnswerer()
    q = "Our compensation is based on experience, expertise, and skills. To offer a competitive package, what is your desired annual compensation range?*"

    # 1. Checkbox group with standard Particle41 options
    opts = [
        '4,00,000 to 6,00,000 per year',
        '7,00,000 to 10,00,000 per year',
        '11,00,000 to 15,00,000 per year',
        '16,00,000 to 20,00,000 per year',
        '21,00,000 to 25,00,000 per year',
        '26,00,000 or more per year'
    ]
    assert answerer.find_direct_answer(q, field_type="checkbox", options=opts) == "16,00,000 to 20,00,000 per year"
    assert answerer.answer_question(q, field_type="checkbox", options=opts) == "16,00,000 to 20,00,000 per year"

    # 2. Dropdown with alternate accepted option
    opts_alt = ['10-15 LPA', '16-20 LPA', '21-25 LPA']
    assert answerer.find_direct_answer("what is your desired annual compensation range", field_type="dropdown", options=opts_alt) == "16-20 LPA"

    # 3. Text field
    assert answerer.find_direct_answer(q, field_type="text") == "16,00,000 to 20,00,000 per year"


def test_desired_annual_compensation_range_negative():
    """Tests strict matching: options lacking desired range or unrelated questions return None / UNKNOWN."""
    answerer = FormAnswerer()
    q = "Our compensation is based on experience, expertise, and skills. To offer a competitive package, what is your desired annual compensation range?*"

    # 1. Options lacking 16-20 range -> None / UNKNOWN
    opts_unmatched = ['4,00,000 to 6,00,000 per year', '7,00,000 to 10,00,000 per year']
    assert answerer.find_direct_answer(q, field_type="checkbox", options=opts_unmatched) is None
    assert answerer.answer_question(q, field_type="checkbox", options=opts_unmatched) == "UNKNOWN"

    # 2. Unrelated compensation question -> UNKNOWN
    assert answerer.find_direct_answer("What is your desired hourly rate in USD?", field_type="text") is None
    assert answerer.answer_question("What is your desired hourly rate in USD?", field_type="text") == "UNKNOWN"


def test_current_total_annual_compensation_positive():
    """Tests matching for current total annual compensation question with accepted options and numeric inputs."""
    answerer = FormAnswerer()
    q = "What is your current total annual compensation?*"

    # 1. Checkbox group with standard Particle41 options
    opts = [
        '4,00,000 to 6,00,000 per year',
        '7,00,000 to 10,00,000 per year',
        '11,00,000 to 15,00,000 per year',
        '16,00,000 to 20,00,000 per year',
        '21,00,000 to 25,00,000 per year',
        '26,00,000 or more per year'
    ]
    assert answerer.find_direct_answer(q, field_type="checkbox", options=opts) == "11,00,000 to 15,00,000 per year"
    assert answerer.answer_question(q, field_type="checkbox", options=opts) == "11,00,000 to 15,00,000 per year"

    # Variations of question label
    assert answerer.find_direct_answer("current total annual compensation", field_type="checkbox", options=opts) == "11,00,000 to 15,00,000 per year"
    assert answerer.find_direct_answer("What is your current annual compensation?", field_type="checkbox", options=opts) == "11,00,000 to 15,00,000 per year"

    # 2. Dropdown with alternate accepted option
    opts_alt = ['6-10 LPA', '11-15 LPA', '16-20 LPA']
    assert answerer.find_direct_answer(q, field_type="dropdown", options=opts_alt) == "11-15 LPA"

    # 3. Number field -> returns digits only candidate CTC "1260000"
    assert answerer.find_direct_answer(q, field_type="number") == "1260000"
    assert answerer.answer_question(q, field_type="number") == "1260000"

    # 4. Text field -> returns "1260000"
    assert answerer.find_direct_answer(q, field_type="text") == "1260000"
    assert answerer.answer_question(q, field_type="text") == "1260000"


def test_current_total_annual_compensation_negative():
    """Tests strict matching: options lacking current compensation range or unrelated questions return None / UNKNOWN."""
    answerer = FormAnswerer()
    q = "What is your current total annual compensation?*"

    # 1. Options lacking 11-15 range -> None / UNKNOWN
    opts_unmatched = ['4,00,000 to 6,00,000 per year', '16,00,000 to 20,00,000 per year']
    assert answerer.find_direct_answer(q, field_type="checkbox", options=opts_unmatched) is None
    assert answerer.answer_question(q, field_type="checkbox", options=opts_unmatched) == "UNKNOWN"

    # 2. Unrelated compensation question -> UNKNOWN
    assert answerer.find_direct_answer("What was your compensation in 2020?", field_type="text") is None
    assert answerer.answer_question("What was your compensation in 2020?", field_type="text") == "UNKNOWN"


def test_city_location_positive():
    """Tests matching for City / Location (city) from answers.yaml."""
    answerer = FormAnswerer()

    # 1. Text input for Location (city)*
    assert answerer.find_direct_answer("Location (city)*", field_type="text") == "Jaipur"
    assert answerer.answer_question("Location (city)*", field_type="text") == "Jaipur"

    # Label variations
    assert answerer.find_direct_answer("City", field_type="text") == "Jaipur"
    assert answerer.find_direct_answer("Current city", field_type="text") == "Jaipur"
    assert answerer.find_direct_answer("What is your city?", field_type="text") == "Jaipur"
    assert answerer.find_direct_answer("What is your current city?", field_type="text") == "Jaipur"

    # 2. Dropdown with exact city name
    opts = ["Delhi", "Bengaluru", "Jaipur", "Pune"]
    assert answerer.find_direct_answer("Location (city)*", field_type="dropdown", options=opts) == "Jaipur"
    assert answerer.answer_question("Location (city)*", field_type="dropdown", options=opts) == "Jaipur"

    # 3. Dropdown with extended accepted option
    opts_extended = ["Jaipur, Rajasthan, India", "Mumbai, Maharashtra, India"]
    assert answerer.find_direct_answer("Location (city)*", field_type="dropdown", options=opts_extended) == "Jaipur, Rajasthan, India"


def test_city_location_negative():
    """Tests strict matching: options lacking candidate city or unrelated questions return None / UNKNOWN."""
    answerer = FormAnswerer()

    # 1. Dropdown lacking Jaipur -> UNKNOWN (no nearest/fuzzy)
    opts_no_jaipur = ["Delhi", "Bengaluru", "Mumbai"]
    assert answerer.find_direct_answer("Location (city)*", field_type="dropdown", options=opts_no_jaipur) is None
    assert answerer.answer_question("Location (city)*", field_type="dropdown", options=opts_no_jaipur) == "UNKNOWN"

    # 2. Unrelated city question -> UNKNOWN
    assert answerer.find_direct_answer("What is your favorite city to visit?", field_type="text") is None
    assert answerer.answer_question("What is your favorite city to visit?", field_type="text") == "UNKNOWN"










