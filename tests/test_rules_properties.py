"""Property-based tests for the rules engine (SPEC 10, Kiro PBT)."""

from functools import lru_cache

from hypothesis import given, settings
from hypothesis import strategies as st

from masshelp.config import PACKAGE_DIR
from masshelp.rules.engine import evaluate
from masshelp.rules.models import EmploymentType, MemberFacts, SchoolEnrollment, Status, YearMonth, load_rules

NOV = YearMonth(year=2026, month=11)
MEETS = {Status.LIKELY_MEETS, Status.LIKELY_EXEMPT}


@lru_cache
def rules():
    return load_rules(PACKAGE_DIR / "rules" / "masshealth_rules.yaml")


money = st.one_of(st.none(), st.floats(min_value=0, max_value=20000, allow_nan=False))
hours = st.one_of(st.none(), st.floats(min_value=0, max_value=400, allow_nan=False))


@st.composite
def facts(draw, exempt=None):
    exemption = draw(st.sampled_from([None] + rules().exemption_ids)) if exempt is None else exempt
    return MemberFacts(
        age=draw(st.integers(min_value=19, max_value=64)),
        program="CarePlus",
        is_exempt_claimed=draw(st.one_of(st.none(), st.booleans())) if exemption is None else True,
        exemption_type=exemption,
        employment_type=draw(st.one_of(st.none(), st.sampled_from(list(EmploymentType)))),
        weekly_hours=draw(hours),
        monthly_hours=draw(hours),
        monthly_gross_income=draw(money),
        monthly_expenses=draw(money),
        monthly_net_income=draw(money),
        is_seasonal=draw(st.one_of(st.none(), st.booleans())),
        seasonal_average_monthly_income=draw(money),
        school_enrollment=draw(st.one_of(st.none(), st.sampled_from(list(SchoolEnrollment)))),
        volunteer_hours=draw(hours),
        training_hours=draw(hours),
    )


@given(facts(), st.floats(min_value=580, max_value=50000, allow_nan=False))
def test_income_at_threshold_meets(f, income):
    f = f.model_copy(update={"monthly_net_income": income, "monthly_gross_income": income, "monthly_expenses": None})
    assert evaluate(f, NOV, rules()).status in MEETS


@given(st.sampled_from(rules().exemption_ids).flatmap(lambda e: facts(exempt=e)))
def test_any_exemption_is_exempt(f):
    assert evaluate(f, NOV, rules()).status == Status.LIKELY_EXEMPT


@settings(max_examples=300)
@given(facts(), st.floats(min_value=0, max_value=200), st.floats(min_value=0, max_value=5000))
def test_monotonic(f, extra_hours, extra_income):
    before = evaluate(f, NOV, rules()).status
    more = f.model_copy(update={
        "monthly_hours": (f.monthly_hours or 0) + extra_hours if f.monthly_hours is not None else None,
        "weekly_hours": (f.weekly_hours or 0) + extra_hours / 4.33 if f.weekly_hours is not None else None,
        "volunteer_hours": (f.volunteer_hours or 0) + extra_hours if f.volunteer_hours is not None else None,
        "monthly_gross_income": (f.monthly_gross_income + extra_income) if f.monthly_gross_income is not None else None,
        "monthly_net_income": (f.monthly_net_income + extra_income) if f.monthly_net_income is not None else None,
    })
    after = evaluate(more, NOV, rules()).status
    if before in MEETS:
        assert after != Status.LIKELY_DOES_NOT_MEET


@given(
    st.floats(min_value=0, max_value=2000, allow_nan=False),
    st.floats(min_value=0, max_value=100, allow_nan=False),
    st.floats(min_value=0, max_value=100, allow_nan=False),
    st.floats(min_value=0, max_value=100, allow_nan=False),
)
def test_combination_meets(income, volunteer, training, work):
    f = MemberFacts(age=30, program="CarePlus", is_exempt_claimed=False, employment_type="employee",
                    monthly_gross_income=income, monthly_hours=work, volunteer_hours=volunteer, training_hours=training)
    # Same job's income and hours aren't double counted: the larger of the two counts.
    if max(income / 7.25, work) + volunteer + training >= 80:
        assert evaluate(f, NOV, rules()).status == Status.LIKELY_MEETS
