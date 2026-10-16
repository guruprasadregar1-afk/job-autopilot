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

    # 12. Unapproved questions strictly return None (NEEDS_INPUT)
    assert answerer.find_direct_answer("Are you willing to relocate?", field_type="dropdown", options=["Yes", "No"]) is None
    assert answerer.find_direct_answer("Willing to relocate", field_type="radio", options=["Yes", "No"]) is None
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


