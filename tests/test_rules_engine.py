import pytest

from masshelp.rules.engine import evaluate
from masshelp.rules.models import MemberFacts, Status, YearMonth

NOV = YearMonth(year=2026, month=11)
NO_EXEMPT = {"age": 34, "program": "CarePlus", "is_exempt_claimed": False}
ALL_ASKED = {**NO_EXEMPT, "school_enrollment": "none", "volunteer_hours": 0, "training_hours": 0}


def ev(rules, **facts):
    return evaluate(MemberFacts(**facts), NOV, rules)


def test_maria_gig_income(rules):
    r = ev(rules, **NO_EXEMPT, employment_type="gig", weekly_hours=25, monthly_gross_income=1150, monthly_net_income=900)
    assert r.status == Status.LIKELY_MEETS
    assert r.path == "income"
    assert "hours" in r.other_paths_met
    assert r.derived["monthly_work_hours"] == 108  # 25 x 4.33 = 108.25, rounded down
    assert r.proof_needed[0]["any_of"][0] == "gig_earnings_screenshot"


@pytest.mark.parametrize("income,status", [(579.99, Status.LIKELY_DOES_NOT_MEET), (580.00, Status.LIKELY_MEETS)])
def test_income_edge(rules, income, status):
    r = ev(rules, **ALL_ASKED, employment_type="employee", monthly_gross_income=income, monthly_hours=0)
    assert r.status == status


@pytest.mark.parametrize("hours,status", [(79, Status.LIKELY_DOES_NOT_MEET), (80, Status.LIKELY_MEETS)])
def test_hours_edge(rules, hours, status):
    r = ev(rules, **ALL_ASKED, employment_type="employee", monthly_hours=hours, monthly_gross_income=0)
    assert r.status == status


@pytest.mark.parametrize("age,status", [(18, Status.LIKELY_EXEMPT), (19, Status.LIKELY_DOES_NOT_MEET),
                                        (64, Status.LIKELY_DOES_NOT_MEET), (65, Status.LIKELY_EXEMPT)])
def test_age_edges(rules, age, status):
    facts = {**ALL_ASKED, "age": age, "employment_type": "none"}
    assert ev(rules, **facts).status == status


def test_every_exemption(rules):
    for ex in rules.exemptions:
        # Exempt regardless of hours or income.
        r = ev(rules, age=30, program="CarePlus", is_exempt_claimed=True, exemption_type=ex.id,
               employment_type="none", monthly_hours=0)
        assert r.status == Status.LIKELY_EXEMPT, ex.id
        assert r.path == f"exemption:{ex.id}"
        assert r.proof_needed


def test_parent_of_ten_year_old_no_hours_needed(rules):
    r = ev(rules, age=30, program="CarePlus", is_exempt_claimed=True, exemption_type="caretaker_child_13_or_younger")
    assert r.status == Status.LIKELY_EXEMPT
    assert r.missing == []


def test_half_time_student(rules):
    assert ev(rules, **NO_EXEMPT, school_enrollment="half_time").path == "school"


def test_combination_300_income_50_volunteer(rules):
    r = ev(rules, **NO_EXEMPT, employment_type="employee", monthly_gross_income=300, monthly_hours=20,
           volunteer_hours=50, school_enrollment="none", training_hours=0)
    assert r.status == Status.LIKELY_MEETS
    assert r.path == "combination"  # 300 / 7.25 = 41.4 + 50 = 91.4
    assert any("Combination" in n for n in r.notes)


def test_lost_job_does_not_meet(rules):
    r = ev(rules, **ALL_ASKED, employment_type="none")
    assert r.status == Status.LIKELY_DOES_NOT_MEET


def test_needs_more_info_when_unknown(rules):
    r = ev(rules, age=30, program="CarePlus")
    assert r.status == Status.NEEDS_MORE_INFO
    assert "is_exempt_claimed" in r.missing


def test_gig_without_expenses_uses_gross_with_note(rules):
    r = ev(rules, **NO_EXEMPT, employment_type="gig", monthly_gross_income=700)
    assert r.status == Status.LIKELY_MEETS
    assert any("gross" in n for n in r.notes)


def test_seasonal(rules):
    r = ev(rules, **ALL_ASKED, employment_type="employee", monthly_gross_income=0, monthly_hours=0,
           is_seasonal=True, seasonal_average_monthly_income=600)
    assert r.path == "seasonal_income"


def test_not_careplus(rules):
    assert ev(rules, age=30, program="Standard").status == Status.LIKELY_EXEMPT
