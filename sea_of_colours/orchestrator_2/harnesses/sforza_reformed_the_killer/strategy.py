"""Evidence-bound SNAP tactics and a small RED-first ammunition budget."""
from __future__ import annotations

from collections.abc import Mapping

from sea_of_colours.game.session import HARVESTER_BUILD_COST, PROBE_BUILD_COST, REPAIR_COST
from sea_of_colours.game.weapons import SNAP_COST_BLUE_PURITY, SNAP_COST_CREDITS, BLUE_COST_BY_KIND, WEAPONISED_BLUE_CAP
from . import option_economics, weapon_forge


def number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def cell(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            pass
    return None


def rules(view):
    return (view.get("meta") or {}).get("rules") or {}


def radius(view):
    from sea_of_colours.game.tuning import probe_vision_radius
    return number(rules(view).get("probe_radius"), probe_vision_radius())


def inside(target, origin, distance):
    return sum((left - right) ** 2 for left, right in zip(target, origin)) <= distance ** 2


def terrain(view, colour):
    result = {}
    for row in view.get(colour.lower() + "_tiles") or []:
        if not isinstance(row, Mapping) or row.get("freshness", "fresh") != "fresh":
            continue
        target = cell([row.get("x"), row.get("y")])
        if target is not None:
            result[target] = number(row.get("purity"))
    return result


def pure_cells(view):
    return {target for target, purity in terrain(view, "red").items()
            if option_economics._tier(purity) == "pure"}


def blue_needed(view):
    return (not any(option_economics._tier(purity) in {"pure", "mass"}
                    for purity in terrain(view, "red").values())
            and number(((view.get("orbit") or {}).get("weapon_stock") or {}).get("snap")) == 0
            and weapon_forge._blue_total(view) < snap_blue_cost(view))


def snap_blue_cost(view):
    price = ((view.get("orbit") or {}).get("weapon_prices") or {}).get("snap") or {}
    return max(0, number(price.get("blue"), SNAP_COST_BLUE_PURITY))


def own_probes(view):
    from .packager import _live_probe_cells
    return set(_live_probe_cells(view))


def covered(view, target, probes):
    if any(inside(target, origin, radius(view)) for origin in probes):
        return True
    return any(entity.get("type") == "harvester" and cell(entity.get("pos")) is not None
               and inside(target, cell(entity["pos"]), 1)
               for entity in (view.get("entities") or {}).get("mine", []) if isinstance(entity, Mapping))


def rival_eyes(view):
    day = number((view.get("hud") or {}).get("day"), number((view.get("meta") or {}).get("day")))
    from sea_of_colours.game.tuning import probe_lifetime_nights
    lifetime = number(rules(view).get("probe_lifetime_nights"), probe_lifetime_nights() or 0)
    return {cell(row.get("at")) for row in weapon_forge.rival_eyes(view)
            if cell(row.get("at")) is not None and number(row.get("day_seen")) > 0
            and (lifetime <= 0 or day - number(row.get("day_seen")) < lifetime)}


def takeover_targets(view):
    eyes = rival_eyes(view)
    targets = set()
    for region in view.get("redsign") or []:
        if not isinstance(region, Mapping) or region.get("mine"):
            continue
        centre = region.get("center") or region.get("centre")
        if cell(centre) is None:
            continue
        centre = tuple(float(coordinate) for coordinate in centre)
        covering = {eye for eye in eyes if inside(centre, eye, radius(view))}
        if len(covering) == 1:
            targets.update(covering - own_probes(view))
    return sorted(targets)


def protected_targets(view):
    eyes = rival_eyes(view)
    probes = own_probes(view)
    return sorted(target for target in pure_cells(view)
                  if any(inside(target, eye, radius(view)) for eye in eyes)
                  and covered(view, target, probes - {target}))


def unknown_rival_ground(view):
    known = set(terrain(view, "red")) | set(terrain(view, "blue"))
    return {target for region in view.get("redsign") or []
            if isinstance(region, Mapping) and not region.get("mine")
            for raw in region.get("cells") or []
            if isinstance(raw, (list, tuple)) and len(raw) >= 2
            for target in [cell(raw[:2])] if target is not None and target not in known}


def menu(registry, view, option_cls):
    from .agency import _option_drop_cells, _option_walk_cells
    pures = pure_cells(view)
    blue = terrain(view, "blue")
    reveal_first = unknown_rival_ground(view)
    for key, option in list(registry.items()):
        drops = _option_drop_cells(option)
        path = drops + _option_walk_cells(option)
        if option.kind == "snap" or any(target in pures for target in path):
            del registry[key]
        elif any(target in reveal_first for target in path):
            del registry[key]
        elif not blue_needed(view) and (option.kind == "blue_grab" or any(target in blue for target in path)):
            del registry[key]
    for index, target in enumerate(sorted(pures), 1):
        if covered(view, target, own_probes(view)):
            name = f"PURE_PICK{index}"
            registry[name] = option_cls(name, "grab", f"Take only PURE {target}",
                "Drop then immediately lift; sacrificing our probe at the landing is allowed.",
                payload={"eye_action": "direct", "target": list(target), "drop_at": list(target), "cells": [list(target)]},
                rationale="Bank this known PURE without a halo walk; no weapon needed if uncontested.")
    stock = number(((view.get("orbit") or {}).get("weapon_stock") or {}).get("snap"))
    if stock > 0:
        for index, target in enumerate(protected_targets(view), 1):
            name = f"FIRST_CLAIM{index}"
            registry[name] = option_cls(name, "snap", f"SNAP then take PURE {target}",
                "H1 SNAP; H2 drop with surviving coverage; H3 pickup. One harvester, no paired grab needed.",
                payload={"eye_action": "claim", "target": list(target), "drop_at": list(target), "cells": [list(target)]},
                rationale="COMPARE: direct PURE_PICK lands at H1 without a charge. FIRST_CLAIM instead denies H1 and lands H2. A rival probe at H1 followed by a drop at H2 counters this play with a collision; never treat it as guaranteed insurance.")
        if number((view.get("orbit") or {}).get("probe_stock")) > 0:
            for index, target in enumerate(takeover_targets(view), 1):
                name = f"CUT_THE_EYE{index}"
                registry[name] = option_cls(name, "snap", f"SNAP rival eye {target}, establish our probe",
                    "H1 SNAP; H2 probe on the cooled square. Reveal now, choose the exact harvest next planning turn.",
                    payload={"eye_action": "takeover", "target": list(target)},
                    rationale="Remove the single known eye supporting their redsign; may disrupt their opening. Hidden/replacement coverage may remain.")
    for index, region in enumerate(view.get("redsign") or [], 1):
        if not isinstance(region, Mapping) or region.get("mine"):
            continue
        target = cell(region.get("center") or region.get("centre"))
        if target is not None and number((view.get("orbit") or {}).get("probe_stock")) > 0:
            name = f"REVEAL_SIGN{index}"
            registry[name] = option_cls(name, "probe", f"Survey rival redsign {target}",
                "Probe only: centre is not an exact PURE coordinate. Plan the harvest next turn.", payload={"at": list(target)})
    return registry


def pack(pk, payload):
    action, target = payload["eye_action"], cell(payload.get("target"))
    if target is None or target in pk._drop_cells:
        return
    if action != "direct" and pk.moves:
        pk.log.append("sforza_reformed_the_killer: skipped second/late SNAP choice")
        return
    mark = pk.begin()
    if action == "takeover":
        pk.moves.append({"a": "snap_launch", "at": list(target)})
        if not pk.spend_probe(target):
            pk.rollback(mark)
        return
    unit = pk.next_harvester()
    if unit is None:
        return
    if action == "claim":
        pk.moves.append({"a": "snap_launch", "at": list(target)})
    if not pk.emit_chain(unit, target, []):
        pk.rollback(mark)


def guard(moves, view):
    from sea_of_colours.game.policy import MAX_MOVES
    probes = own_probes(view)
    pures, blue, red = pure_cells(view), terrain(view, "blue"), terrain(view, "red")
    reveal_first = unknown_rival_ground(view)
    stock = number(((view.get("orbit") or {}).get("weapon_stock") or {}).get("snap"))
    probe_stock = number((view.get("orbit") or {}).get("probe_stock"))
    allowed_snaps = set(protected_targets(view)) | set(takeover_targets(view))
    positions, used, grabbed, pure_units = {}, set(), set(), set()
    available = {asset.get("id") for asset in view.get("my_assets") or []
                 if isinstance(asset, Mapping) and asset.get("kind") == "harvester" and asset.get("state") == "orbit"}
    blue_unit, blue_amount = None, weapon_forge._blue_total(view)
    output, notes = [], []
    pending_snap = None
    for hour, raw in enumerate(moves[:MAX_MOVES], 1):
        move = dict(raw)
        verb, unit = move.get("a"), str(move.get("unit", ""))
        target = cell(move.get("at") if verb != "step" else move.get("to"))
        permitted = True
        if verb in {"snap", "snap_launch"}:
            permitted = hour == 1 and stock > 0 and target in allowed_snaps
            if permitted:
                move["a"] = "snap_launch"
                stock -= 1
                probes.discard(target)
                pending_snap = target
        elif verb in {"emp_launch", "chaff_flare", "mine_lay"}:
            permitted = False
        elif verb == "probe":
            permitted = target is not None and probe_stock > 0 and target not in positions.values()
            if permitted:
                probes.add(target)
                probe_stock -= 1
        elif verb in {"drop", "step"}:
            permitted = target is not None
            if verb == "drop":
                permitted = permitted and unit in available and unit not in used and target not in grabbed and covered(view, target, probes)
                permitted = permitted and target not in reveal_first
                permitted = permitted and any(later.get("a") == "pickup" and later.get("unit") == unit for later in moves[hour:MAX_MOVES])
            else:
                origin = positions.get(unit)
                permitted = permitted and origin is not None and sum(abs(a-b) for a,b in zip(origin,target)) == 1 and unit not in pure_units
                permitted = permitted and target not in reveal_first
            if target in blue:
                permitted = permitted and blue_needed(view) and blue_unit in (None, unit) and blue_amount < snap_blue_cost(view)
            if permitted:
                positions[unit] = target
                used.add(unit)
                probes.discard(target)
                if target in pures:
                    pure_units.add(unit)
                if target in blue and target not in grabbed:
                    blue_unit = unit
                    blue_amount += blue[target]
                grabbed.add(target)
        elif verb == "pickup":
            permitted = unit in positions
            if permitted:
                del positions[unit]
        elif verb != "wait":
            permitted = False
        if not permitted:
            notes.append(f"sforza_reformed_the_killer veto H{hour} {verb}: strategy/resource/coverage constraint")
            move = {"a": "wait"}
        output.append(move)
    if pending_snap is not None:
        next_move = output[1] if len(output) > 1 else {}
        if not ((next_move.get("a") == "probe" and cell(next_move.get("at")) == pending_snap)
                or (next_move.get("a") == "drop" and cell(next_move.get("at")) == pending_snap
                    and len(output) > 2 and output[2].get("a") == "pickup" and output[2].get("unit") == next_move.get("unit"))):
            return [{"a": "wait"} for _ in output], notes + ["sforza_reformed_the_killer veto: incomplete SNAP follow-up"]
    return output, notes


def orbit_plan(view, *, weapons_enabled=True):
    from .orbit_policy import _my_harvesters, DEFAULT_DIALS
    orbit = view.get("orbit") or {}
    if orbit.get("final_orbit"):
        return [], "Final orbit: no procurement"
    credits = number(orbit.get("credits"))
    prices = orbit.get("ship_prices") or {}
    actions, notes = [], []
    def buy(verb, price, **fields):
        nonlocal credits
        if price < 0 or credits < price:
            return False
        actions.append({"a": verb, **fields})
        credits -= price
        notes.append(f"{verb} {fields}: {price}c")
        return True
    for harvester in _my_harvesters(view):
        if harvester.get("damaged"):
            buy("repair", number(prices.get("repair"), REPAIR_COST), unit=harvester["id"])
    fleet = number(orbit.get("harvester_cap_used"))
    fleet_cap = number(orbit.get("harvester_cap_max"), 3)
    harvester_cost = number(prices.get("harvester_build"), HARVESTER_BUILD_COST)
    if fleet == 0 and fleet_cap > 0 and buy("build_harvester", harvester_cost):
        fleet += 1
    probe_cost = number(prices.get("probe_build"), PROBE_BUILD_COST)
    probes = number(orbit.get("probe_stock"))
    for _ in range(max(0, 2 - probes)):
        if buy("build_probe", probe_cost, count=1):
            probes += 1
    stock = orbit.get("weapon_stock") or {}
    snap_price = (orbit.get("weapon_prices") or {}).get("snap") or {}
    snap_blue = number(snap_price.get("blue"), SNAP_COST_BLUE_PURITY)
    snap_credit = number(snap_price.get("credits"), SNAP_COST_CREDITS)
    held = sum(number(stock.get(kind)) * cost for kind,cost in BLUE_COST_BY_KIND.items())
    saving_for_second = 0 < fleet < min(2, fleet_cap)
    if saving_for_second:
        if buy("build_harvester", harvester_cost):
            fleet += 1
        else:
            return actions, "sforza_reformed_the_killer RED-first orbit: " + "; ".join(notes) + f"; reserve {credits}c toward second harvester ({harvester_cost}c)"
    if (weapons_enabled and fleet > 0 and number(stock.get("snap")) == 0
            and weapon_forge._blue_total(view) >= snap_blue
            and held + snap_blue <= number(rules(view).get("weapon_blue_cap"), WEAPONISED_BLUE_CAP)):
        buy("build_snap", snap_credit, count=1)
    if fleet < fleet_cap and fleet > 0 and not saving_for_second:
        buy("build_harvester", harvester_cost)
    if probe_cost > 0:
        count = min(max(0, DEFAULT_DIALS.probe_target_stock - probes), credits // probe_cost)
        if count:
            buy("build_probe", count * probe_cost, count=count)
    return actions, "sforza_reformed_the_killer RED-first orbit: " + "; ".join(notes) + f"; remaining {credits}c"
