"""Configurable, deterministic Phase 0 economy and progression simulation.

The model works in exact rational expected values. Fractional coins and items in its output
are cohort-level expectations, not proposed persisted values; gameplay continues to use
integers for every actual posting and quantity.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

BASIS_POINTS = 10_000
DAYS_PER_WEEK = 7


@dataclass(frozen=True, slots=True)
class Horizon:
    key: str
    days: int


@dataclass(frozen=True, slots=True)
class Unlock:
    key: str
    label: str
    profession_xp: int
    recommended_purchase_cost: int


@dataclass(frozen=True, slots=True)
class Cohort:
    key: str
    label: str
    active_days_per_week: int
    actions_per_active_day: int
    claim_days_per_week: int
    weekly_objective_completion_bps: int
    economic_yield_bonus_bps: int
    aspirational_sink_participation_bps: int
    launch_population_bps: int = 0
    catch_up_xp_bonus_bps: int = 0
    catch_up_active_days: int = 0


@dataclass(frozen=True, slots=True)
class Activity:
    full_reward_actions_per_active_day: int
    overflow_reward_bps: int
    material_units_ev_numerator: int
    material_units_ev_denominator: int
    material_npc_value: int
    material_sale_bps: int
    direct_coin_ev_numerator: int
    direct_coin_ev_denominator: int
    source_variance_per_rewarded_action: int
    profession_xp_per_rewarded_action: int
    account_xp_per_rewarded_action: int
    conversion_commands_per_100_actions: int
    spending_commands_per_100_actions: int
    inspection_commands_per_active_day: int
    maximum_economic_yield_bonus_bps: int


@dataclass(frozen=True, slots=True)
class CadenceRewards:
    daily_claim_coins: int
    weekly_objective_coins: int
    weekly_objective_account_xp: int


@dataclass(frozen=True, slots=True)
class Sinks:
    tool_charge_coins_per_action: int
    crafting_coins_per_economic_action: int
    npc_supplies_coins_per_economic_action: int
    aspirational_coins_per_economic_action: int
    material_consumption_bps_of_retained: int
    sink_variance_per_economic_action: int


@dataclass(frozen=True, slots=True)
class EconomyModel:
    version: str
    horizons: tuple[Horizon, ...]
    activity: Activity
    cadence_rewards: CadenceRewards
    sinks: Sinks
    unlocks: tuple[Unlock, ...]
    cohorts: tuple[Cohort, ...]
    sensitivities: tuple[Cohort, ...]


@dataclass(frozen=True, slots=True)
class DailyRates:
    actions: Fraction
    commands: Fraction
    rewarded_actions: Fraction
    economic_actions: Fraction
    action_income: Fraction
    daily_claim_income: Fraction
    weekly_objective_income: Fraction
    gross_income: Fraction
    tool_charge_sink: Fraction
    crafting_sink: Fraction
    npc_supplies_sink: Fraction
    aspirational_sink: Fraction
    recurring_sink_demand: Fraction
    source_variance: Fraction
    sink_variance: Fraction
    profession_xp: Fraction
    account_xp: Fraction
    material_stockpile: Fraction


@dataclass(frozen=True, slots=True)
class Projection:
    cohort: Cohort
    horizon: Horizon
    rates: DailyRates
    expected_actions: Fraction
    expected_commands: Fraction
    gross_income: Fraction
    recurring_sink_spend: Fraction
    milestone_sink_spend: Fraction
    total_spending: Fraction
    coin_stockpile: Fraction
    material_stockpile: Fraction
    profession_xp: Fraction
    account_xp: Fraction
    latest_unlock: Unlock
    daily_reward_share_bps: int
    sink_source_ratio_bps: int
    unfunded_sink_demand: Fraction
    source_variance: Fraction
    sink_variance: Fraction


def _as_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table")
    return cast("Mapping[str, object]", value)


def _as_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array of TOML tables")
    return cast("Sequence[object]", value)


def _string(table: Mapping[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _integer(table: Mapping[str, object], key: str, *, default: int | None = None) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _fraction(numerator: int, denominator: int) -> Fraction:
    if denominator <= 0:
        raise ValueError("expected-value denominators must be positive")
    return Fraction(numerator, denominator)


def _bps(value: Fraction, basis_points: int) -> Fraction:
    return value * basis_points / BASIS_POINTS


def _parse_cohort(value: object, name: str) -> Cohort:
    table = _as_mapping(value, name)
    return Cohort(
        key=_string(table, "key"),
        label=_string(table, "label"),
        active_days_per_week=_integer(table, "active_days_per_week"),
        actions_per_active_day=_integer(table, "actions_per_active_day"),
        claim_days_per_week=_integer(table, "claim_days_per_week"),
        weekly_objective_completion_bps=_integer(table, "weekly_objective_completion_bps"),
        economic_yield_bonus_bps=_integer(table, "economic_yield_bonus_bps"),
        aspirational_sink_participation_bps=_integer(table, "aspirational_sink_participation_bps"),
        launch_population_bps=_integer(table, "launch_population_bps", default=0),
        catch_up_xp_bonus_bps=_integer(table, "catch_up_xp_bonus_bps", default=0),
        catch_up_active_days=_integer(table, "catch_up_active_days", default=0),
    )


def load_model(path: Path) -> EconomyModel:
    """Load and validate the complete set of Phase 0 assumptions from TOML."""
    root = _as_mapping(tomllib.loads(path.read_text(encoding="utf-8")), "root")
    model_table = _as_mapping(root.get("model"), "model")
    activity_table = _as_mapping(root.get("activity"), "activity")
    rewards_table = _as_mapping(root.get("cadence_rewards"), "cadence_rewards")
    sinks_table = _as_mapping(root.get("sinks"), "sinks")

    horizons = tuple(
        Horizon(key=_string(table, "key"), days=_integer(table, "days"))
        for item in _as_sequence(root.get("horizons"), "horizons")
        for table in (_as_mapping(item, "horizon"),)
    )
    unlocks = tuple(
        Unlock(
            key=_string(table, "key"),
            label=_string(table, "label"),
            profession_xp=_integer(table, "profession_xp"),
            recommended_purchase_cost=_integer(table, "recommended_purchase_cost"),
        )
        for item in _as_sequence(root.get("unlocks"), "unlocks")
        for table in (_as_mapping(item, "unlock"),)
    )
    cohorts = tuple(
        _parse_cohort(item, "cohort") for item in _as_sequence(root.get("cohorts"), "cohorts")
    )
    sensitivities = tuple(
        _parse_cohort(item, "sensitivity")
        for item in _as_sequence(root.get("sensitivities"), "sensitivities")
    )

    activity = Activity(
        full_reward_actions_per_active_day=_integer(
            activity_table, "full_reward_actions_per_active_day"
        ),
        overflow_reward_bps=_integer(activity_table, "overflow_reward_bps"),
        material_units_ev_numerator=_integer(activity_table, "material_units_ev_numerator"),
        material_units_ev_denominator=_integer(activity_table, "material_units_ev_denominator"),
        material_npc_value=_integer(activity_table, "material_npc_value"),
        material_sale_bps=_integer(activity_table, "material_sale_bps"),
        direct_coin_ev_numerator=_integer(activity_table, "direct_coin_ev_numerator"),
        direct_coin_ev_denominator=_integer(activity_table, "direct_coin_ev_denominator"),
        source_variance_per_rewarded_action=_integer(
            activity_table, "source_variance_per_rewarded_action"
        ),
        profession_xp_per_rewarded_action=_integer(
            activity_table, "profession_xp_per_rewarded_action"
        ),
        account_xp_per_rewarded_action=_integer(activity_table, "account_xp_per_rewarded_action"),
        conversion_commands_per_100_actions=_integer(
            activity_table, "conversion_commands_per_100_actions"
        ),
        spending_commands_per_100_actions=_integer(
            activity_table, "spending_commands_per_100_actions"
        ),
        inspection_commands_per_active_day=_integer(
            activity_table, "inspection_commands_per_active_day"
        ),
        maximum_economic_yield_bonus_bps=_integer(
            activity_table, "maximum_economic_yield_bonus_bps"
        ),
    )
    cadence_rewards = CadenceRewards(
        daily_claim_coins=_integer(rewards_table, "daily_claim_coins"),
        weekly_objective_coins=_integer(rewards_table, "weekly_objective_coins"),
        weekly_objective_account_xp=_integer(rewards_table, "weekly_objective_account_xp"),
    )
    sinks = Sinks(
        tool_charge_coins_per_action=_integer(sinks_table, "tool_charge_coins_per_action"),
        crafting_coins_per_economic_action=_integer(
            sinks_table, "crafting_coins_per_economic_action"
        ),
        npc_supplies_coins_per_economic_action=_integer(
            sinks_table, "npc_supplies_coins_per_economic_action"
        ),
        aspirational_coins_per_economic_action=_integer(
            sinks_table, "aspirational_coins_per_economic_action"
        ),
        material_consumption_bps_of_retained=_integer(
            sinks_table, "material_consumption_bps_of_retained"
        ),
        sink_variance_per_economic_action=_integer(
            sinks_table, "sink_variance_per_economic_action"
        ),
    )
    result = EconomyModel(
        version=_string(model_table, "version"),
        horizons=horizons,
        activity=activity,
        cadence_rewards=cadence_rewards,
        sinks=sinks,
        unlocks=unlocks,
        cohorts=cohorts,
        sensitivities=sensitivities,
    )
    validate_model(result)
    return result


def validate_model(model: EconomyModel) -> None:
    """Reject internally inconsistent assumptions before producing design evidence."""
    if not model.horizons or not model.cohorts or not model.unlocks:
        raise ValueError("the model needs horizons, cohorts, and unlocks")
    if tuple(sorted(h.days for h in model.horizons)) != tuple(h.days for h in model.horizons):
        raise ValueError("horizons must have increasing day counts")
    if tuple(sorted(u.profession_xp for u in model.unlocks)) != tuple(
        u.profession_xp for u in model.unlocks
    ):
        raise ValueError("unlocks must have increasing XP thresholds")
    if model.unlocks[0].profession_xp != 0:
        raise ValueError("the first unlock must begin at zero XP")
    if model.activity.full_reward_actions_per_active_day <= 0:
        raise ValueError("the full-reward action allowance must be positive")
    if model.activity.material_units_ev_denominator <= 0:
        raise ValueError("material EV denominator must be positive")
    if model.activity.direct_coin_ev_denominator <= 0:
        raise ValueError("coin EV denominator must be positive")
    bps_values = (
        model.activity.overflow_reward_bps,
        model.activity.material_sale_bps,
        model.activity.maximum_economic_yield_bonus_bps,
        model.sinks.material_consumption_bps_of_retained,
    )
    if any(value < 0 or value > BASIS_POINTS for value in bps_values):
        raise ValueError("model basis-point values must be between 0 and 10,000")
    for cohort in (*model.cohorts, *model.sensitivities):
        if not 1 <= cohort.active_days_per_week <= DAYS_PER_WEEK:
            raise ValueError(f"{cohort.key}: active days must be between one and seven")
        if not 0 <= cohort.claim_days_per_week <= DAYS_PER_WEEK:
            raise ValueError(f"{cohort.key}: claim days must be between zero and seven")
        if cohort.actions_per_active_day < 0:
            raise ValueError(f"{cohort.key}: actions cannot be negative")
        cohort_bps = (
            cohort.weekly_objective_completion_bps,
            cohort.economic_yield_bonus_bps,
            cohort.aspirational_sink_participation_bps,
            cohort.launch_population_bps,
            cohort.catch_up_xp_bonus_bps,
        )
        if any(value < 0 or value > BASIS_POINTS for value in cohort_bps):
            raise ValueError(f"{cohort.key}: basis-point values must be between 0 and 10,000")
        if cohort.economic_yield_bonus_bps > model.activity.maximum_economic_yield_bonus_bps:
            raise ValueError(f"{cohort.key}: economic yield bonus exceeds the model cap")
    if sum(cohort.launch_population_bps for cohort in model.cohorts) != BASIS_POINTS:
        raise ValueError("primary cohort launch population shares must total 10,000 basis points")


def rewarded_actions_per_active_day(model: EconomyModel, cohort: Cohort) -> Fraction:
    """Apply the explicit high-activity soft cap to one active day."""
    full = min(cohort.actions_per_active_day, model.activity.full_reward_actions_per_active_day)
    overflow = max(
        0, cohort.actions_per_active_day - model.activity.full_reward_actions_per_active_day
    )
    return Fraction(full) + _bps(Fraction(overflow), model.activity.overflow_reward_bps)


def daily_rates(model: EconomyModel, cohort: Cohort) -> DailyRates:
    active_day_rate = Fraction(cohort.active_days_per_week, DAYS_PER_WEEK)
    claim_rate = Fraction(cohort.claim_days_per_week, DAYS_PER_WEEK)
    actions = active_day_rate * cohort.actions_per_active_day
    rewarded_actions = active_day_rate * rewarded_actions_per_active_day(model, cohort)
    economic_multiplier = Fraction(BASIS_POINTS + cohort.economic_yield_bonus_bps, BASIS_POINTS)
    economic_actions = rewarded_actions * economic_multiplier

    material_ev = _fraction(
        model.activity.material_units_ev_numerator,
        model.activity.material_units_ev_denominator,
    )
    direct_coin_ev = _fraction(
        model.activity.direct_coin_ev_numerator,
        model.activity.direct_coin_ev_denominator,
    )
    action_income_per_economic_action = (
        material_ev
        * model.activity.material_npc_value
        * model.activity.material_sale_bps
        / BASIS_POINTS
        + direct_coin_ev
    )
    action_income = economic_actions * action_income_per_economic_action
    daily_claim_income = claim_rate * model.cadence_rewards.daily_claim_coins
    weekly_objective_income = (
        Fraction(model.cadence_rewards.weekly_objective_coins, DAYS_PER_WEEK)
        * cohort.weekly_objective_completion_bps
        / BASIS_POINTS
    )
    gross_income = action_income + daily_claim_income + weekly_objective_income

    tool_charge_sink = actions * model.sinks.tool_charge_coins_per_action
    crafting_sink = economic_actions * model.sinks.crafting_coins_per_economic_action
    npc_supplies_sink = economic_actions * model.sinks.npc_supplies_coins_per_economic_action
    aspirational_sink = (
        economic_actions
        * model.sinks.aspirational_coins_per_economic_action
        * cohort.aspirational_sink_participation_bps
        / BASIS_POINTS
    )
    recurring_sink_demand = tool_charge_sink + crafting_sink + npc_supplies_sink + aspirational_sink

    commands = (
        actions
        + claim_rate
        + actions * model.activity.conversion_commands_per_100_actions / 100
        + actions * model.activity.spending_commands_per_100_actions / 100
        + active_day_rate * model.activity.inspection_commands_per_active_day
    )
    profession_xp = rewarded_actions * model.activity.profession_xp_per_rewarded_action
    account_xp = (
        rewarded_actions * model.activity.account_xp_per_rewarded_action
        + Fraction(model.cadence_rewards.weekly_objective_account_xp, DAYS_PER_WEEK)
        * cohort.weekly_objective_completion_bps
        / BASIS_POINTS
    )

    retained_materials = (
        material_ev
        * economic_actions
        * (BASIS_POINTS - model.activity.material_sale_bps)
        / BASIS_POINTS
    )
    material_stockpile = (
        retained_materials
        * (BASIS_POINTS - model.sinks.material_consumption_bps_of_retained)
        / BASIS_POINTS
    )
    source_variance = (
        rewarded_actions
        * model.activity.source_variance_per_rewarded_action
        * economic_multiplier
        * economic_multiplier
    )
    sink_variance = economic_actions * model.sinks.sink_variance_per_economic_action

    return DailyRates(
        actions=actions,
        commands=commands,
        rewarded_actions=rewarded_actions,
        economic_actions=economic_actions,
        action_income=action_income,
        daily_claim_income=daily_claim_income,
        weekly_objective_income=weekly_objective_income,
        gross_income=gross_income,
        tool_charge_sink=tool_charge_sink,
        crafting_sink=crafting_sink,
        npc_supplies_sink=npc_supplies_sink,
        aspirational_sink=aspirational_sink,
        recurring_sink_demand=recurring_sink_demand,
        source_variance=source_variance,
        sink_variance=sink_variance,
        profession_xp=profession_xp,
        account_xp=account_xp,
        material_stockpile=material_stockpile,
    )


def profession_xp_at_days(model: EconomyModel, cohort: Cohort, days: Fraction) -> Fraction:
    rates = daily_rates(model, cohort)
    base_xp = rates.profession_xp * days
    if cohort.catch_up_xp_bonus_bps == 0 or cohort.catch_up_active_days == 0:
        return base_xp
    catch_up_calendar_days = Fraction(
        cohort.catch_up_active_days * DAYS_PER_WEEK, cohort.active_days_per_week
    )
    boosted_days = min(days, catch_up_calendar_days)
    return base_xp + _bps(rates.profession_xp * boosted_days, cohort.catch_up_xp_bonus_bps)


def days_to_profession_xp(model: EconomyModel, cohort: Cohort, target_xp: int) -> Fraction:
    rates = daily_rates(model, cohort)
    if target_xp == 0:
        return Fraction(0)
    if rates.profession_xp <= 0:
        raise ValueError(f"{cohort.key} cannot reach a positive XP milestone")
    catch_up_calendar_days = Fraction(0)
    if cohort.catch_up_xp_bonus_bps and cohort.catch_up_active_days:
        catch_up_calendar_days = Fraction(
            cohort.catch_up_active_days * DAYS_PER_WEEK, cohort.active_days_per_week
        )
    boosted_daily_xp = (
        rates.profession_xp * (BASIS_POINTS + cohort.catch_up_xp_bonus_bps) / BASIS_POINTS
    )
    catch_up_xp = boosted_daily_xp * catch_up_calendar_days
    if target_xp <= catch_up_xp and catch_up_xp > 0:
        return Fraction(target_xp, 1) / boosted_daily_xp
    return catch_up_calendar_days + (Fraction(target_xp, 1) - catch_up_xp) / rates.profession_xp


def project(model: EconomyModel, cohort: Cohort, horizon: Horizon) -> Projection:
    rates = daily_rates(model, cohort)
    days = Fraction(horizon.days)
    gross_income = rates.gross_income * days
    recurring_demand = rates.recurring_sink_demand * days
    recurring_spend = min(gross_income, recurring_demand)
    profession_xp = profession_xp_at_days(model, cohort, days)
    account_xp = rates.account_xp * days
    reached_unlocks = tuple(
        unlock for unlock in model.unlocks if unlock.profession_xp <= profession_xp
    )
    latest_unlock = reached_unlocks[-1]
    milestone_demand = sum(
        (unlock.recommended_purchase_cost for unlock in reached_unlocks), start=0
    )
    milestone_spend = min(gross_income - recurring_spend, Fraction(milestone_demand))
    total_spending = recurring_spend + milestone_spend
    coin_stockpile = gross_income - total_spending
    unfunded_sink_demand = recurring_demand - recurring_spend + milestone_demand - milestone_spend
    daily_reward_share_bps = (
        int(rates.daily_claim_income * BASIS_POINTS / rates.gross_income)
        if rates.gross_income
        else 0
    )
    sink_source_ratio_bps = int(total_spending * BASIS_POINTS / gross_income) if gross_income else 0
    return Projection(
        cohort=cohort,
        horizon=horizon,
        rates=rates,
        expected_actions=rates.actions * days,
        expected_commands=rates.commands * days,
        gross_income=gross_income,
        recurring_sink_spend=recurring_spend,
        milestone_sink_spend=milestone_spend,
        total_spending=total_spending,
        coin_stockpile=coin_stockpile,
        material_stockpile=rates.material_stockpile * days,
        profession_xp=profession_xp,
        account_xp=account_xp,
        latest_unlock=latest_unlock,
        daily_reward_share_bps=daily_reward_share_bps,
        sink_source_ratio_bps=sink_source_ratio_bps,
        unfunded_sink_demand=unfunded_sink_demand,
        source_variance=rates.source_variance * days,
        sink_variance=rates.sink_variance * days,
    )


def _decimal(value: Fraction, places: int = 2) -> str:
    quantum = Decimal(1).scaleb(-places)
    result = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    return f"{result:.{places}f}"


def _standard_deviation(variance: Fraction) -> str:
    return f"{math.sqrt(float(variance)):.2f}"


def _csv_text(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def render_projection_worksheet(model: EconomyModel) -> str:
    rows: list[Sequence[object]] = []
    for cohort in model.cohorts:
        for horizon in model.horizons:
            result = project(model, cohort, horizon)
            rows.append(
                (
                    model.version,
                    cohort.key,
                    horizon.key,
                    horizon.days,
                    _decimal(result.rates.actions),
                    _decimal(result.rates.commands),
                    _decimal(result.expected_actions),
                    _decimal(result.expected_commands),
                    _decimal(result.gross_income),
                    _standard_deviation(result.source_variance),
                    _decimal(result.recurring_sink_spend),
                    _decimal(result.milestone_sink_spend),
                    _decimal(result.total_spending),
                    _standard_deviation(result.sink_variance),
                    _decimal(result.coin_stockpile),
                    _decimal(result.material_stockpile),
                    _decimal(result.profession_xp),
                    _decimal(result.account_xp),
                    result.latest_unlock.key,
                    result.daily_reward_share_bps,
                    result.sink_source_ratio_bps,
                    _decimal(result.unfunded_sink_demand),
                )
            )
    return _csv_text(
        (
            "model_version",
            "cohort",
            "horizon",
            "calendar_days",
            "actions_per_day",
            "commands_per_day",
            "expected_actions",
            "expected_commands",
            "expected_income_coins",
            "source_standard_deviation_coins",
            "recurring_sink_spend_coins",
            "milestone_sink_spend_coins",
            "expected_spending_coins",
            "sink_standard_deviation_coins",
            "coin_stockpile",
            "material_stockpile_units",
            "profession_xp",
            "account_xp",
            "latest_major_unlock",
            "daily_reward_share_bps",
            "sink_source_ratio_bps",
            "unfunded_sink_demand_coins",
        ),
        rows,
    )


def render_source_sink_worksheet(model: EconomyModel) -> str:
    rows: list[Sequence[object]] = []
    for cohort in model.cohorts:
        rates = daily_rates(model, cohort)
        rows.append(
            (
                model.version,
                cohort.key,
                _decimal(rates.action_income),
                _decimal(rates.daily_claim_income),
                _decimal(rates.weekly_objective_income),
                _decimal(rates.gross_income),
                _decimal(rates.source_variance),
                _decimal(rates.tool_charge_sink),
                _decimal(rates.crafting_sink),
                _decimal(rates.npc_supplies_sink),
                _decimal(rates.aspirational_sink),
                _decimal(rates.recurring_sink_demand),
                _decimal(rates.sink_variance),
            )
        )
    return _csv_text(
        (
            "model_version",
            "cohort",
            "daily_action_source_ev",
            "daily_claim_source_ev",
            "weekly_objective_source_ev_per_day",
            "total_source_ev_per_day",
            "source_variance_per_day",
            "tool_charge_sink_ev_per_day",
            "crafting_sink_ev_per_day",
            "npc_supplies_sink_ev_per_day",
            "aspirational_sink_ev_per_day",
            "total_recurring_sink_ev_per_day",
            "recurring_sink_variance_per_day",
        ),
        rows,
    )


def render_milestone_worksheet(model: EconomyModel) -> str:
    rows: list[Sequence[object]] = []
    for cohort in model.cohorts:
        rates = daily_rates(model, cohort)
        for unlock in model.unlocks:
            elapsed_days = days_to_profession_xp(model, cohort, unlock.profession_xp)
            rows.append(
                (
                    model.version,
                    cohort.key,
                    unlock.key,
                    unlock.profession_xp,
                    _decimal(elapsed_days),
                    _decimal(elapsed_days * rates.commands),
                    unlock.recommended_purchase_cost,
                )
            )
    return _csv_text(
        (
            "model_version",
            "cohort",
            "major_unlock",
            "profession_xp_required",
            "elapsed_calendar_days",
            "expected_commands",
            "recommended_purchase_cost_coins",
        ),
        rows,
    )


def render_sensitivity_worksheet(model: EconomyModel) -> str:
    rows: list[Sequence[object]] = []
    for cohort in model.sensitivities:
        for horizon in model.horizons:
            result = project(model, cohort, horizon)
            rows.append(
                (
                    model.version,
                    cohort.key,
                    horizon.key,
                    _decimal(result.rates.actions),
                    _decimal(result.gross_income),
                    _decimal(result.total_spending),
                    _decimal(result.coin_stockpile),
                    _decimal(result.profession_xp),
                    result.daily_reward_share_bps,
                    result.sink_source_ratio_bps,
                )
            )
    return _csv_text(
        (
            "model_version",
            "sensitivity",
            "horizon",
            "actions_per_day",
            "expected_income_coins",
            "expected_spending_coins",
            "coin_stockpile",
            "profession_xp",
            "daily_reward_share_bps",
            "sink_source_ratio_bps",
        ),
        rows,
    )


def render_supply_pressure_worksheet(model: EconomyModel) -> str:
    """Project aggregate supply for the configurable launch cohort mix."""
    population = 1_000
    rows: list[Sequence[object]] = []
    for horizon in model.horizons:
        results = tuple(project(model, cohort, horizon) for cohort in model.cohorts)
        gross_income = sum(
            (
                result.gross_income
                * result.cohort.launch_population_bps
                * population
                / BASIS_POINTS
                for result in results
            ),
            start=Fraction(0),
        )
        destroyed = sum(
            (
                result.total_spending
                * result.cohort.launch_population_bps
                * population
                / BASIS_POINTS
                for result in results
            ),
            start=Fraction(0),
        )
        net_new_supply = gross_income - destroyed
        unfunded_demand = sum(
            (
                result.unfunded_sink_demand
                * result.cohort.launch_population_bps
                * population
                / BASIS_POINTS
                for result in results
            ),
            start=Fraction(0),
        )
        rows.append(
            (
                model.version,
                horizon.key,
                population,
                _decimal(gross_income),
                _decimal(destroyed),
                _decimal(net_new_supply),
                int(net_new_supply * BASIS_POINTS / gross_income) if gross_income else 0,
                _decimal(net_new_supply / population),
                _decimal(unfunded_demand),
            )
        )
    return _csv_text(
        (
            "model_version",
            "horizon",
            "modeled_active_players",
            "cumulative_minted_coins",
            "cumulative_destroyed_coins",
            "net_new_supply_coins",
            "net_supply_bps_of_minted",
            "average_wallet_coins",
            "unfunded_sink_demand_coins",
        ),
        rows,
    )


def render_worksheets(model: EconomyModel) -> Mapping[str, str]:
    """Render all tracked CSV worksheets from one immutable model snapshot."""
    return {
        "phase0_projection.csv": render_projection_worksheet(model),
        "phase0_source_sink.csv": render_source_sink_worksheet(model),
        "phase0_milestones.csv": render_milestone_worksheet(model),
        "phase0_sensitivities.csv": render_sensitivity_worksheet(model),
        "phase0_supply_pressure.csv": render_supply_pressure_worksheet(model),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("balance/phase0_economy.toml"))
    parser.add_argument("--output-dir", type=Path, default=Path("balance"))
    args = parser.parse_args(argv)
    model = load_model(args.config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in render_worksheets(model).items():
        (args.output_dir / filename).write_text(content, encoding="utf-8", newline="")
    return 0
