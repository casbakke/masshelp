"""Types for the rules engine: config, member facts, months, and evaluations."""

from __future__ import annotations

import calendar
from datetime import date
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Status(StrEnum):
    LIKELY_EXEMPT = "LIKELY_EXEMPT"
    LIKELY_MEETS = "LIKELY_MEETS"
    LIKELY_DOES_NOT_MEET = "LIKELY_DOES_NOT_MEET"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"


class EmploymentType(StrEnum):
    EMPLOYEE = "employee"
    SELF_EMPLOYED = "self_employed"
    GIG = "gig"
    NONE = "none"


class SchoolEnrollment(StrEnum):
    FULL_TIME = "full_time"
    HALF_TIME = "half_time"
    LESS_THAN_HALF = "less_than_half"
    NONE = "none"


class YearMonth(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    month: int = Field(ge=1, le=12)

    @classmethod
    def parse(cls, value: str) -> YearMonth:
        year_s, month_s = value.strip()[:7].split("-")
        return cls(year=int(year_s), month=int(month_s))

    @classmethod
    def from_date(cls, d: date) -> YearMonth:
        return cls(year=d.year, month=d.month)

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return date(self.year, self.month, self.days)

    @property
    def days(self) -> int:
        return calendar.monthrange(self.year, self.month)[1]

    def previous(self) -> YearMonth:
        if self.month == 1:
            return YearMonth(year=self.year - 1, month=12)
        return YearMonth(year=self.year, month=self.month - 1)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class MemberFacts(BaseModel):
    """Everything the engine needs. None means "not known yet"."""

    age: int | None = None
    program: str | None = None
    is_exempt_claimed: bool | None = None
    exemption_type: str | None = None
    employment_type: EmploymentType | None = None
    employer_or_platform: str | None = None
    weekly_hours: float | None = None
    monthly_hours: float | None = None
    monthly_gross_income: float | None = None
    monthly_expenses: float | None = None
    monthly_net_income: float | None = None
    is_seasonal: bool | None = None
    seasonal_average_monthly_income: float | None = None
    school_enrollment: SchoolEnrollment | None = None
    volunteer_hours: float | None = None
    training_hours: float | None = None


class Evaluation(BaseModel):
    status: Status
    path: str | None = None
    other_paths_met: list[str] = []
    reasons: list[str] = []
    missing: list[str] = []
    # Each entry: {"covers": "income", "any_of": ["pay_stub", "employer_letter"]}
    proof_needed: list[dict] = []
    notes: list[str] = []
    derived: dict[str, float | int | None] = {}


# ---------------------------------------------------------------- config


class ExemptionRule(BaseModel):
    id: str
    label: str
    priority: int = 1
    state_option: bool = False
    screening: dict[str, str] = {}
    proof: list[str] = []


class ProofType(BaseModel):
    label: str
    instructions: dict[str, str] = {}
    alternatives: list[str] = []


class RulesConfig(BaseModel):
    version: str
    source: str
    effective_date: date
    program: str
    age_min: int
    age_max: int
    age_reference: str = "first_day_of_month"
    federal_minimum_wage: float
    hours_threshold: float
    income_threshold: float
    weeks_per_month: float
    seasonal_lookback_months: int
    mismatch_tolerance: float
    renewal_months: int
    retro_coverage_months_before: int
    retro_coverage_months_after: int
    contacts: dict[str, str]
    notes: dict[str, str]
    exemptions: list[ExemptionRule]
    path_proof: dict[str, list[str]]
    proof_types: dict[str, ProofType]

    @model_validator(mode="after")
    def _check(self) -> RulesConfig:
        expected = round(self.hours_threshold * self.federal_minimum_wage, 2)
        if abs(expected - self.income_threshold) > 0.005:
            raise ValueError(
                f"income_threshold {self.income_threshold} != hours_threshold x minimum wage ({expected})"
            )
        known = set(self.proof_types)
        for ex in self.exemptions:
            unknown = set(ex.proof) - known
            if unknown:
                raise ValueError(f"exemption {ex.id} references unknown proof types {unknown}")
        for path, proofs in self.path_proof.items():
            unknown = set(proofs) - known
            if unknown:
                raise ValueError(f"path {path} references unknown proof types {unknown}")
        for pid, pt in self.proof_types.items():
            unknown = set(pt.alternatives) - known
            if unknown:
                raise ValueError(f"proof type {pid} references unknown alternatives {unknown}")
        return self

    def exemption(self, exemption_id: str | None) -> ExemptionRule | None:
        if not exemption_id:
            return None
        for ex in self.exemptions:
            if ex.id == exemption_id:
                return ex
        return None

    @property
    def exemption_ids(self) -> list[str]:
        return [ex.id for ex in self.exemptions]


def load_rules(path: Path) -> RulesConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return RulesConfig.model_validate(data)


@lru_cache
def load_rules_cached(path: str) -> RulesConfig:
    return load_rules(Path(path))
