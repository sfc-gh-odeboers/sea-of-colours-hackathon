from __future__ import annotations

from copy import deepcopy
import json

import pytest

from sea_of_colours.orchestrator_2.harnesses.sforza_reformed_the_killer import agency, harness, packager, strategy


@pytest.fixture
def view(monkeypatch):
    monkeypatch.setattr(strategy, "rival_eyes", lambda view: {(7, 5)})
    return {"hud": {"day": 2}, "meta": {"rules": {"probe_radius": 4}},
            "my_assets": [{"id": "harvester_p1", "kind": "harvester", "state": "orbit"}],
            "orbit": {"credits": 2000, "harvester_cap_used": 1, "harvester_cap_max": 3,
                      "probe_stock": 2, "blue_purity_total": 100, "weapon_stock": {"snap": 1},
                      "harvesters": [{"id": "harvester_p1", "status": "orbital"}]},
            "entities": {"mine": [{"id": "probe_p1_a", "type": "probe", "pos": [4, 5], "nights_remaining": 2},
                                   {"id": "harvester_p1", "type": "harvester", "pos": None}]},
            "red_tiles": [{"x": 5, "y": 5, "purity": 255, "freshness": "fresh"}],
            "blue_tiles": [{"x": 6, "y": 5, "purity": 100, "freshness": "fresh"}],
            "redsign": [{"center": [5, 5], "mine": False, "cells": [[5, 5]]}]}


def compile_choice(view, name):
    menu = strategy.menu({}, view, agency.Option)
    moves, _ = packager.pack_recipe([menu[name]], view, complete=False)
    return strategy.guard(moves, view)[0]


def test_claim_is_exact_single_pure_sequence(view):
    moves = compile_choice(view, "FIRST_CLAIM1")
    assert [move["a"] for move in moves] == ["snap_launch", "drop", "pickup"]
    assert moves[0]["at"] == moves[1]["at"] == [5, 5]


def test_direct_grab_can_crush_support_probe(view):
    view["entities"]["mine"][0]["pos"] = [5, 5]
    assert "FIRST_CLAIM1" not in strategy.menu({}, view, agency.Option)
    assert [move["a"] for move in compile_choice(view, "PURE_PICK1")] == ["drop", "pickup"]


def test_takeover_has_probe_and_no_guessed_harvest(view):
    view["red_tiles"] = []
    moves = compile_choice(view, "CUT_THE_EYE1")
    assert moves == [{"a": "snap_launch", "at": [7, 5]}, {"a": "probe", "at": [7, 5]}]


def test_redundant_eyes_and_empty_probe_stock_withhold_takeover(view, monkeypatch):
    monkeypatch.setattr(strategy, "rival_eyes", lambda view: {(7, 5), (6, 5)})
    assert "CUT_THE_EYE1" not in strategy.menu({}, view, agency.Option)
    view["orbit"]["probe_stock"] = 0
    assert "REVEAL_SIGN1" not in strategy.menu({}, view, agency.Option)


def test_blue_gate_and_budget(view):
    view["orbit"]["weapon_stock"] = {}
    view["orbit"]["blue_purity_total"] = 0
    assert not strategy.blue_needed(view)
    view["red_tiles"][0]["purity"] = 151
    assert not strategy.blue_needed(view)
    view["red_tiles"] = []
    assert strategy.blue_needed(view)
    view["orbit"]["blue_purity_total"] = 100
    assert not strategy.blue_needed(view)


def test_fallback_moves_cannot_bypass_blue_gate(view):
    moves = [{"a": "drop", "unit": "harvester_p1", "at": [6, 5]},
             {"a": "pickup", "unit": "harvester_p1"}]
    assert all(move["a"] == "wait" for move in strategy.guard(moves, view)[0])


def test_incomplete_or_second_snap_does_not_spend_charge(view):
    assert strategy.guard([{"a": "snap_launch", "at": [5, 5]}], view)[0] == [{"a": "wait"}]
    menu = strategy.menu({}, view, agency.Option)
    moves, _ = packager.pack_recipe([menu["FIRST_CLAIM1"], menu["CUT_THE_EYE1"], menu["PURE_PICK1"]], view, complete=False)
    assert [move["a"] for move in moves] == ["snap_launch", "drop", "pickup"]


def test_procurement_priority_and_no_undeclared_weapons(view):
    view["orbit"].update(probe_stock=0, weapon_stock={}, credits=750, harvester_cap_used=2)
    actions, _ = strategy.orbit_plan(view)
    assert [action["a"] for action in actions] == ["build_probe", "build_probe", "build_snap"]
    assert not any(action["a"] == "build_snap" for action in strategy.orbit_plan(view, weapons_enabled=False)[0])
    view["orbit"].update(credits=10000, weapon_stock={"snap": 1}, blue_purity_total=10000)
    assert not any(action["a"] in {"build_snap", "build_emp", "build_chaff"} for action in strategy.orbit_plan(view)[0])


def test_empty_fleet_precedes_weapons(view):
    view["orbit"].update(harvester_cap_used=0, credits=1500, weapon_stock={})
    assert strategy.orbit_plan(view)[0] == [{"a": "build_harvester"}]


def test_pure_valuation_and_overselected_run_competition(view):
    from .. import option_economics
    menu = strategy.menu({}, view, agency.Option)
    pure = menu["PURE_PICK1"]
    assert option_economics.walk_cells(pure.payload) == [(5, 5)]
    assert packager._harvest_value(pure.payload, view) == 765
    assert packager._harvest_value(menu["FIRST_CLAIM1"].payload, view) == 765
    view["red_tiles"].append({"x": 4, "y": 5, "purity": 200, "freshness": "fresh"})
    competitor = agency.Option("OTHER", "grab", "Other", "", payload={"cells": [[4, 5]]})
    kept, report = packager.reconcile_selected([competitor, pure], view)
    assert kept == [pure]
    assert next(row for row in report if row["id"] == pure.option_id)["value"] == 765
    view["red_tiles"].extend({"x": coordinate, "y": 5, "purity": 254, "freshness": "fresh"} for coordinate in (2, 3))
    competitor.payload["cells"] = [[2, 5], [3, 5], [4, 5]]
    assert packager.reconcile_selected([pure, competitor], view)[0] == [competitor]


def test_save_across_orbits_for_second_harvester(view):
    view["orbit"].update(credits=1000, probe_stock=0, weapon_stock={})
    actions, rationale = strategy.orbit_plan(view)
    assert [action["a"] for action in actions] == ["build_probe", "build_probe"]
    assert "reserve 500c" in rationale
    view["orbit"].update(credits=1500, probe_stock=2)
    assert strategy.orbit_plan(view)[0] == [{"a": "build_harvester"}]


def test_ordinary_hotdrop_kept_but_unknown_rival_smear_is_reveal_first(view):
    view["red_tiles"] = []
    payload = {"probe_at": [10, 10], "drop_at": [11, 10], "comb_path": []}
    option = agency.Option("HD1", "hotdrop", "Explore", "", payload=payload)
    assert "HD1" in strategy.menu({"HD1": option}, view, agency.Option)
    moves = [{"a": "probe", "at": [10, 10]}, {"a": "drop", "unit": "harvester_p1", "at": [11, 10]}, {"a": "pickup", "unit": "harvester_p1"}]
    assert strategy.guard(moves, view)[0] == moves
    view["redsign"][0]["cells"] = [[11, 10, 0.5]]
    assert "HD1" not in strategy.menu({"HD1": option}, view, agency.Option)
    assert [move["a"] for move in strategy.guard(moves, view)[0]] == ["probe", "wait", "wait"]


def test_crushed_probe_cannot_support_later_exploratory_drop(view):
    view["my_assets"].append({"id": "harvester_p1_extra", "kind": "harvester", "state": "orbit"})
    moves = [{"a": "drop", "unit": "harvester_p1", "at": [4, 5]}, {"a": "pickup", "unit": "harvester_p1"},
             {"a": "drop", "unit": "harvester_p1_extra", "at": [5, 5]}, {"a": "pickup", "unit": "harvester_p1_extra"}]
    assert [move["a"] for move in strategy.guard(moves, view)[0]] == ["drop", "pickup", "wait", "wait"]


def test_inputs_are_not_mutated(view):
    before = deepcopy(view)
    compile_choice(view, "FIRST_CLAIM1")
    strategy.orbit_plan(view)
    assert view == before


def test_guard_caps_blue_to_one_outing_and_rejects_second_pure_grab(view):
    view["orbit"].update(weapon_stock={}, blue_purity_total=0)
    view["red_tiles"] = []
    view["my_assets"].append({"id": "harvester_p1_extra", "kind": "harvester", "state": "orbit"})
    view["blue_tiles"].append({"x": 7, "y": 5, "purity": 100, "freshness": "fresh"})
    moves = [{"a": "drop", "unit": "harvester_p1", "at": [6, 5]},
             {"a": "pickup", "unit": "harvester_p1"},
             {"a": "drop", "unit": "harvester_p1_extra", "at": [7, 5]},
             {"a": "pickup", "unit": "harvester_p1_extra"}]
    guarded, _ = strategy.guard(moves, view)
    assert [move["a"] for move in guarded] == ["drop", "pickup", "wait", "wait"]


def test_guard_does_not_launch_sortie_without_room_to_pick_up(view):
    assert strategy.guard([{"a": "drop", "unit": "harvester_p1", "at": [5, 5]}], view)[0] == [{"a": "wait"}]


def test_repair_and_probe_floor_precede_snap(view):
    view["entities"]["mine"][1]["damaged"] = True
    view["orbit"].update(weapon_stock={}, probe_stock=0, credits=1000)
    assert [action["a"] for action in strategy.orbit_plan(view)[0]] == ["repair", "build_probe", "build_probe"]


def test_real_engine_direct_and_snap_pure_capture(monkeypatch):
    from sea_of_colours.game.session import Entity, GameSession
    for snap in (False, True):
        session = GameSession.new(24, 18, seed=1201)
        session.entities["harvester_p1"].x = session.entities["harvester_p1"].y = None
        session.entities["harvester_p2"].x = session.entities["harvester_p2"].y = None
        session.weapon_stock["p1"] = {"snap": 1}
        session.entities["probe_p1_test"] = Entity("probe_p1_test", "probe", "p1", 5, 5)
        moves = ([{"a": "snap_launch", "at": [6, 5]}] if snap else [])
        moves += [{"a": "drop", "unit": "harvester_p1", "at": [6, 5] if snap else [5, 5]},
                  {"a": "pickup", "unit": "harvester_p1"}]
        session.stash_policy("p1", moves)
        session.stash_policy("p2", [{"a": "wait"}])
        session.maybe_resolve_if_ready()
        assert session.entities["harvester_p1"].x is None
        assert not session.entities["harvester_p1"].damaged
        if not snap:
            assert "probe_p1_test" not in session.entities


def test_actual_harness_submission_uses_coordinated_claim(monkeypatch):
    from sea_of_colours.snowpark import engine
    from turnlab import boards, store, turn
    board = next(board for board in boards.discover(store.store()) if board.id == "LAB_30890438_d2_p1")
    opened = turn.open_board(board.id, arms={board.seat: "snap"})
    scratch = turn._scratch_clone(store.store(), opened["run_id"])
    from sea_of_colours.game.session import Entity
    session = engine._hydrate_session(store.store(), scratch)
    session.entities["probe_p1_support"] = Entity("probe_p1_support", "probe", board.seat, 8, 8)
    session.entities["probe_p2_contest"] = Entity("probe_p2_contest", "probe", "p2", 10, 8)
    engine.save_session_full(store.store(), session)
    actual = engine.get_view(store.store(), scratch, board.seat)
    monkeypatch.setattr(strategy, "rival_eyes", lambda view: {(10, 8)})
    choices = strategy.menu({}, actual["agent_view"], agency.Option)
    selected = next((name for name in choices if name.startswith("FIRST_CLAIM")), None)
    assert selected, list(choices)
    class FakeInvoker:
        def __init__(self, **kwargs):
            pass
        def invoke(self, prompt, **kwargs):
            if "COMMIT" in prompt or "PLAN PASS" in prompt:
                response = json.dumps({"posture": "aggressive", "plan": [selected], "note": "claim pure",
                    "situational": {"mine": False, "players": [], "chaff": False, "emp": False, "snap": True},
                    "chaff_react": False, "intent": "claim pure", "reflection": "", "reasoning": ""})
            else:
                response = selected + " captures the known pure after an opening SNAP."
            return {"ok": True, "response": response, "elapsed_ms": 1}
    monkeypatch.setattr(harness, "CortexChatInvoker", FakeInvoker)
    result = harness.run(store=store.store(), session_id=scratch, player=board.seat, view=actual)
    assert result["submitted_policy"] and not result["extras"]["fallback_used"]
    assert [move["a"] for move in result["extras"]["final_moves"]][:3] == ["snap_launch", "drop", "pickup"]
