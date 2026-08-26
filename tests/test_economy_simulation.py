from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from butterbot.simulation.economy import (
    BASIS_POINTS,
    Cohort,
    EconomyModel,
    daily_rates,
    load_model,
    project,
    render_worksheets,
    rewarded_actions_per_active_day,
    validate_model,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "balance" / "phase0_economy.toml"


@pytest.fixture(scope="module")
def model() -> EconomyModel:
    return load_model(CONFIG_PATH)


def _cohort(model: EconomyModel, key: str) -> Cohort:
    return next(cohort for cohort in model.cohorts if cohort.key == key)


def test_model_contains_required_cohorts_and_horizons(model: EconomyModel) -> None:
    assert {cohort.key for cohort in model.cohorts} == {
        "casual",
        "regular",
        "dedicated",
        "optimized_hardcore",
    }
    assert {horizon.days for horizon in model.horizons} == {1, 7, 30, 91, 182, 365, 1095}
    assert sum(cohort.launch_population_bps for cohort in model.cohorts) == BASIS_POINTS
    assert {cohort.key for cohort in model.sensitivities} == {
        "returning_regular",
        "alternate_daily_only",
    }


def test_high_activity_rewards_are_soft_capped(model: EconomyModel) -> None:
    hardcore = _cohort(model, "optimized_hardcore")

    assert rewarded_actions_per_active_day(model, hardcore) == 36
    assert hardcore.actions_per_active_day == 45


def test_tool_charge_sink_scales_with_actual_activity(model: EconomyModel) -> None:
    regular = _cohort(model, "regular")
    doubled = replace(regular, actions_per_active_day=regular.actions_per_active_day * 2)

    regular_rates = daily_rates(model, regular)
    doubled_rates = daily_rates(model, doubled)

    assert doubled_rates.tool_charge_sink == regular_rates.tool_charge_sink * 2


def test_projection_preserves_flow_and_non_negative_stockpiles(model: EconomyModel) -> None:
    for cohort in model.cohorts:
        for horizon in model.horizons:
            result = project(model, cohort, horizon)

            assert result.gross_income == result.total_spending + result.coin_stockpile
            assert result.coin_stockpile >= 0
            assert result.material_stockpile >= 0
            assert result.total_spending <= result.gross_income


def test_long_horizon_stays_inside_initial_flow_envelope(model: EconomyModel) -> None:
    three_years = next(horizon for horizon in model.horizons if horizon.key == "three_years")
    for cohort in model.cohorts:
        result = project(model, cohort, three_years)
        recurring_ratio = result.rates.recurring_sink_demand / result.rates.gross_income
        monthly_income = result.rates.gross_income * 30

        assert Fraction(45, 100) <= recurring_ratio <= Fraction(71, 100)
        assert result.coin_stockpile <= monthly_income * 9
        assert result.unfunded_sink_demand == 0


def test_daily_reward_is_modest_for_primary_cohorts(model: EconomyModel) -> None:
    shares = {
        cohort.key: int(
            daily_rates(model, cohort).daily_claim_income
            * BASIS_POINTS
            / daily_rates(model, cohort).gross_income
        )
        for cohort in model.cohorts
    }

    assert 500 <= shares["casual"] <= 2_000
    assert shares["regular"] <= 1_000
    assert shares["dedicated"] <= 500
    assert shares["optimized_hardcore"] <= 500


def test_returning_bonus_changes_xp_but_not_currency(model: EconomyModel) -> None:
    regular = _cohort(model, "regular")
    returning = next(cohort for cohort in model.sensitivities if cohort.key == "returning_regular")
    month = next(horizon for horizon in model.horizons if horizon.key == "one_month")

    regular_result = project(model, regular, month)
    returning_result = project(model, returning, month)

    assert returning_result.profession_xp > regular_result.profession_xp
    assert returning_result.gross_income == regular_result.gross_income


def test_rejects_yield_bonus_above_the_declared_budget(model: EconomyModel) -> None:
    regular = _cohort(model, "regular")
    invalid = replace(
        model,
        cohorts=(
            replace(
                regular,
                economic_yield_bonus_bps=model.activity.maximum_economic_yield_bonus_bps + 1,
                launch_population_bps=BASIS_POINTS,
            ),
        ),
    )

    with pytest.raises(ValueError, match="economic yield bonus exceeds"):
        validate_model(invalid)


def test_tracked_phase0_worksheets_are_current(model: EconomyModel) -> None:
    for filename, expected in render_worksheets(model).items():
        actual = (REPOSITORY_ROOT / "balance" / filename).read_text(encoding="utf-8")
        assert actual == expected, f"regenerate {filename} with python -m butterbot.simulation"


def test_sensitivities_cover_every_accepted_horizon(model: EconomyModel) -> None:
    rows = render_worksheets(model)["phase0_sensitivities.csv"].strip().splitlines()[1:]

    assert len(rows) == len(model.sensitivities) * len(model.horizons)
