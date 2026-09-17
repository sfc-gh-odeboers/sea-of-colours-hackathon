"""Tests for sforza_reformed_the_killer weapon plays and forge integration.

Covers: play validation, option building with mocked views, economy
settings, procurement, blue doctrine, edge cases.
"""
from __future__ import annotations

import pytest
from sea_of_colours.orchestrator_2.harnesses.sforza_reformed_the_killer import weapon_plays
from sea_of_colours.orchestrator_2.harnesses.sforza_reformed_the_killer.weapon_forge import (
    EconomyPolicy,
    WeaponPlay,
    build_options,
    compose_rationale,
    compose_title,
    contested_pures,
    contested_pure_gate,
    finder_probes,
    finder_gate,
    rival_eyes,
    blue_also_requested,
    blue_doctrine_for,
    tune_dials,
    add_procurement,
    economy_summary,
    _declared_weapons,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _minimal_view(**overrides):
    """A bare agent_view with enough structure for forge functions."""
    v = {
        "meta": {"width": 40, "height": 28},
        "hud": {"season_day_cap": 7, "day": 3},
        "orbit": {
            "weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
            "blue_purity_total": 0,
            "hoard_parcels": [],
            "weapon_specs": {
                "snap": {"radius": 0, "missiles_per_launch": 1, "cloud_hours": 1},
                "emp": {"radius": 2, "missiles_per_launch": 3, "cloud_hours": 8},
            },
        },
        "red_tiles": [],
        "redsign": [],
        "competitor_intel": {"new_this_day": []},
        "harvesters": [],
        "probes": [],
    }
    for k, val in overrides.items():
        if isinstance(val, dict) and k in v and isinstance(v[k], dict):
            v[k].update(val)
        else:
            v[k] = val
    return v


def _view_with_contested_pure(
    pure_cell=(10, 10),
    rival_probe_at=(11, 11),
    our_probe_at=(9, 9),
    snap_stock=1,
    blue=200,
):
    """View with a pure WE see, plus a rival probe within vision range."""
    return _minimal_view(
        orbit={
            "weapon_stock": {"snap": snap_stock, "emp": 0, "chaff": 0},
            "blue_purity_total": blue,
            "hoard_parcels": [],
            "weapon_specs": {
                "snap": {"radius": 0, "missiles_per_launch": 1, "cloud_hours": 1},
            },
        },
        red_tiles=[
            {"x": pure_cell[0], "y": pure_cell[1], "purity": 255},
        ],
        # rival_eyes() fallback reads "rival_probes" for synthetic fixtures
        rival_probes=[
            {"at": [rival_probe_at[0], rival_probe_at[1]], "day_seen": 2},
        ],
        probes=[
            {"x": our_probe_at[0], "y": our_probe_at[1], "day_placed": 1},
        ],
    )


def _view_with_finder_probe(
    beacon_center=(15, 15),
    rival_probe_at=(14, 14),
    snap_stock=1,
    blue=200,
    n_rival_probes=1,
):
    """View with a rival redsign and a rival probe covering the beacon."""
    rival_probes = []
    for i in range(n_rival_probes):
        rival_probes.append({
            "at": [rival_probe_at[0] + i, rival_probe_at[1]],
            "day_seen": 2,
        })
    return _minimal_view(
        orbit={
            "weapon_stock": {"snap": snap_stock, "emp": 0, "chaff": 0},
            "blue_purity_total": blue,
            "hoard_parcels": [],
            "weapon_specs": {
                "snap": {"radius": 0, "missiles_per_launch": 1, "cloud_hours": 1},
            },
        },
        redsign=[{
            "mine": False,
            "center": [beacon_center[0], beacon_center[1]],
            "cells": [
                [beacon_center[0], beacon_center[1]],
                [beacon_center[0] + 1, beacon_center[1]],
            ],
        }],
        # rival_eyes() fallback reads "rival_probes" for synthetic fixtures
        rival_probes=rival_probes,
    )


# ── play declarations ────────────────────────────────────────────────────

class TestPlayDeclarations:
    def test_plays_are_valid(self):
        for p in weapon_plays.PLAYS:
            errors = p.validate()
            assert not errors, f"{p.play_id}: {errors}"

    def test_all_snap(self):
        for p in weapon_plays.PLAYS:
            assert p.weapon == "snap", f"{p.play_id} is {p.weapon}, expected snap"

    def test_no_emp_or_chaff(self):
        weapons = {p.weapon for p in weapon_plays.PLAYS}
        assert "emp" not in weapons
        assert "chaff" not in weapons

    def test_three_plays_declared(self):
        assert len(weapon_plays.PLAYS) == 3

    def test_play_ids_unique(self):
        ids = [p.play_id for p in weapon_plays.PLAYS]
        assert len(ids) == len(set(ids))

    def test_snap_contested_exists(self):
        p = next(x for x in weapon_plays.PLAYS if x.play_id == "SNAP_CONTESTED")
        assert p.targets == "contested_pure"
        assert p.when == "redsign_theirs"
        assert p.hour == "super_early"
        assert p.combines_with == "smash_grab"

    def test_snap_finder_exists(self):
        p = next(x for x in weapon_plays.PLAYS if x.play_id == "SNAP_FINDER")
        assert p.targets == "finder_probe"
        assert p.when == "redsign_theirs"
        assert p.hour == "super_early"
        assert p.combines_with == "blind_grab"

    def test_snap_defend_exists(self):
        p = next(x for x in weapon_plays.PLAYS if x.play_id == "SNAP_DEFEND")
        assert p.targets == "contested_pure"
        assert p.when == "redsign_mine"
        assert p.hour == "super_early"

    def test_no_take_the_ground(self):
        """SNAP plays should be denial-only per plan."""
        for p in weapon_plays.PLAYS:
            assert p.take_the_ground is False, f"{p.play_id} has take_the_ground=True"


# ── economy ──────────────────────────────────────────────────────────────

class TestEconomy:
    def test_economy_type(self):
        assert isinstance(weapon_plays.ECONOMY, EconomyPolicy)

    def test_snap_hold_at_one(self):
        assert weapon_plays.ECONOMY.hold_at["snap"] == 1

    def test_emp_hold_at_zero(self):
        assert weapon_plays.ECONOMY.hold_at["emp"] == 0

    def test_chaff_hold_at_zero(self):
        assert weapon_plays.ECONOMY.hold_at["chaff"] == 0

    def test_buy_asap(self):
        assert weapon_plays.ECONOMY.buy_asap is True

    def test_never_buy_undeclared(self):
        assert weapon_plays.ECONOMY.never_buy_what_you_cannot_fire is True

    def test_seek_blue_when_rack_empty(self):
        assert weapon_plays.ECONOMY.seek_blue_when_rack_empty is True

    def test_seek_blue_not_always(self):
        assert weapon_plays.ECONOMY.seek_blue_always is False

    def test_declared_weapons_snap_only(self):
        assert _declared_weapons() == ["snap"]

    def test_economy_summary_mentions_snap(self):
        lines = economy_summary()
        assert any("snap" in line.lower() or "SNAP" in line for line in lines)

    def test_economy_summary_never_buy_emp_chaff(self):
        lines = economy_summary()
        text = " ".join(lines)
        assert "emp" in text.lower() or "chaff" in text.lower()


# ── blue doctrine ────────────────────────────────────────────────────────

class TestBlueDoctrine:
    def test_blue_requested_when_rack_empty(self):
        view = _minimal_view(
            orbit={"weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
                   "blue_purity_total": 50}
        )
        assert blue_also_requested(view) is True

    def test_blue_not_requested_when_armed(self):
        view = _minimal_view(
            orbit={"weapon_stock": {"snap": 1, "emp": 0, "chaff": 0},
                   "blue_purity_total": 50}
        )
        assert blue_also_requested(view) is False

    def test_blue_doctrine_text_nonempty_when_unarmed(self):
        view = _minimal_view(
            orbit={"weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
                   "blue_purity_total": 0}
        )
        text = blue_doctrine_for(view)
        assert len(text) > 0

    def test_blue_doctrine_text_empty_when_armed(self):
        view = _minimal_view(
            orbit={"weapon_stock": {"snap": 1, "emp": 0, "chaff": 0},
                   "blue_purity_total": 0}
        )
        text = blue_doctrine_for(view)
        assert text == ""


# ── contested pure targeting ─────────────────────────────────────────────

class TestContestedPure:
    def test_finds_contested_pure(self):
        view = _view_with_contested_pure()
        found, notes = contested_pures(view)
        assert len(found) >= 1
        assert found[0][0] == (10, 10)

    def test_no_rival_probes_no_contest(self):
        view = _minimal_view(
            red_tiles=[{"x": 10, "y": 10, "purity": 255}],
        )
        found, notes = contested_pures(view)
        assert len(found) == 0

    def test_rival_too_far_no_contest(self):
        view = _minimal_view(
            red_tiles=[{"x": 10, "y": 10, "purity": 255}],
            rival_probes=[
                {"at": [25, 25], "day_seen": 1},
            ],
        )
        found, notes = contested_pures(view)
        assert len(found) == 0

    def test_gate_always_fires(self):
        ok1, _ = contested_pure_gate(1)
        ok2, _ = contested_pure_gate(2)
        ok3, _ = contested_pure_gate(5)
        assert ok1 is True
        assert ok2 is True
        assert ok3 is True

    def test_multiple_contested_sorted(self):
        """Most-watched pure should be first."""
        view = _minimal_view(
            red_tiles=[
                {"x": 10, "y": 10, "purity": 255},
                {"x": 20, "y": 20, "purity": 255},
            ],
            rival_probes=[
                {"at": [11, 11], "day_seen": 2},
                {"at": [21, 21], "day_seen": 2},
                {"at": [22, 20], "day_seen": 2},
            ],
        )
        found, notes = contested_pures(view)
        assert len(found) == 2
        # (20,20) has 2 watchers, (10,10) has 1 — most-watched first
        assert found[0][1] >= found[1][1]


# ── finder probe targeting ───────────────────────────────────────────────

class TestFinderProbe:
    def test_finds_sole_eye(self):
        view = _view_with_finder_probe()
        probes, pure, region, notes = finder_probes(view)
        assert len(probes) >= 1

    def test_no_rival_redsign_no_finder(self):
        view = _minimal_view()
        probes, pure, region, notes = finder_probes(view)
        assert len(probes) == 0

    def test_gate_sole_eye_strong(self):
        ok, reason = finder_gate(1, False)
        assert ok is True
        assert "STRONG" in reason

    def test_gate_two_eyes_no_pure_degraded(self):
        ok, reason = finder_gate(2, False)
        assert ok is False
        assert "DEGRADED" in reason

    def test_gate_two_eyes_sees_pure_ok(self):
        ok, reason = finder_gate(2, True)
        assert ok is True

    def test_gate_many_eyes_weak(self):
        ok, reason = finder_gate(3, False)
        assert ok is False
        assert "WEAK" in reason


# ── procurement ──────────────────────────────────────────────────────────

class TestProcurement:
    def test_snap_procured_when_affordable(self):
        view = _minimal_view(
            orbit={
                "weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
                "blue_purity_total": 200,
            }
        )
        actions = []
        descs = []
        remaining = add_procurement(actions, descs, view,
                                    remaining=1000, weapons_enabled=True)
        snap_buys = [a for a in actions if a.get("a") == "build_snap"]
        assert len(snap_buys) == 1

    def test_snap_not_procured_when_capped(self):
        view = _minimal_view(
            orbit={
                "weapon_stock": {"snap": 1, "emp": 0, "chaff": 0},
                "blue_purity_total": 200,
            }
        )
        actions = []
        descs = []
        add_procurement(actions, descs, view,
                        remaining=1000, weapons_enabled=True)
        snap_buys = [a for a in actions if a.get("a") == "build_snap"]
        assert len(snap_buys) == 0

    def test_no_emp_chaff_procured(self):
        view = _minimal_view(
            orbit={
                "weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
                "blue_purity_total": 500,
            }
        )
        actions = []
        descs = []
        add_procurement(actions, descs, view,
                        remaining=1000, weapons_enabled=True)
        emp_buys = [a for a in actions if "emp" in a.get("a", "")]
        chaff_buys = [a for a in actions if "chaff" in a.get("a", "")]
        assert len(emp_buys) == 0
        assert len(chaff_buys) == 0

    def test_snap_not_procured_when_cant_afford(self):
        view = _minimal_view(
            orbit={
                "weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
                "blue_purity_total": 10,
            }
        )
        actions = []
        descs = []
        add_procurement(actions, descs, view,
                        remaining=1000, weapons_enabled=True)
        snap_buys = [a for a in actions if a.get("a") == "build_snap"]
        assert len(snap_buys) == 0

    def test_weapons_disabled_no_procurement(self):
        view = _minimal_view(
            orbit={
                "weapon_stock": {"snap": 0, "emp": 0, "chaff": 0},
                "blue_purity_total": 500,
            }
        )
        actions = []
        descs = []
        add_procurement(actions, descs, view,
                        remaining=1000, weapons_enabled=False)
        assert len(actions) == 0


# ── rationale composition ────────────────────────────────────────────────

class TestRationale:
    def test_rationale_contains_why(self):
        for p in weapon_plays.PLAYS:
            rat = compose_rationale(p)
            assert p.why[:20] in rat or p.why[:20].rstrip(".") in rat

    def test_title_contains_play_id(self):
        for p in weapon_plays.PLAYS:
            t = compose_title(p, target=(10, 10))
            assert p.play_id in t


# ── tune_dials integration ───────────────────────────────────────────────

class TestTuneDials:
    def test_tune_dials_caps_emp_chaff(self):
        """Dials should cap EMP and CHAFF stockpiles to 0."""
        from dataclasses import dataclass

        @dataclass
        class FakeDials:
            blue_always_build: int = 150
            emp_stockpile_cap: int = 2
            chaff_stockpile_cap: int = 2
            snap_stockpile_cap: int = 2

        dials = tune_dials(FakeDials())
        assert dials.emp_stockpile_cap == 0
        assert dials.chaff_stockpile_cap == 0
        assert dials.snap_stockpile_cap == 1  # hold_at snap=1

    def test_tune_dials_buy_asap(self):
        from dataclasses import dataclass

        @dataclass
        class FakeDials:
            blue_always_build: int = 150
            emp_stockpile_cap: int = 2
            chaff_stockpile_cap: int = 2
            snap_stockpile_cap: int = 2

        dials = tune_dials(FakeDials())
        # snap costs 100 blue, buy_asap sets threshold to 99
        assert dials.blue_always_build == 99


# ── missing/stale field handling ─────────────────────────────────────────

class TestEdgeCases:
    def test_empty_view_no_crash(self):
        found, notes = contested_pures({})
        assert found == []

    def test_empty_view_finder_no_crash(self):
        probes, pure, region, notes = finder_probes({})
        assert probes == []

    def test_missing_orbit_blue_requested(self):
        # With declared snap plays and empty view (rack empty), blue IS requested
        assert blue_also_requested({}) is True

    def test_missing_orbit_doctrine(self):
        text = blue_doctrine_for({})
        assert isinstance(text, str)

    def test_rival_eyes_empty_view(self):
        result = rival_eyes({})
        assert result == []

    def test_pure_not_at_255(self):
        """Red tile at purity < 255 is NOT a pure."""
        view = _minimal_view(
            red_tiles=[{"x": 10, "y": 10, "purity": 200}],
            rival_probes=[
                {"at": [11, 11], "day_seen": 1},
            ],
        )
        found, notes = contested_pures(view)
        assert len(found) == 0
