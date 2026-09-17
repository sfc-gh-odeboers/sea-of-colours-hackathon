"""Declare SNAP wiring; strategy.py owns coordinated targets and follow-ups."""
from .weapon_forge import EconomyPolicy, WeaponPlay

ECONOMY = EconomyPolicy(
    seek_blue_when_rack_empty=False,
    seek_blue_always=False,
    never_buy_what_you_cannot_fire=True,
    hold_at={"snap": 1, "emp": 0, "chaff": 0},
)

PLAYS = (
    WeaponPlay(
        play_id="FIRST_CLAIM", weapon="snap", when="always",
        hour="super_early", combines_with="smash_grab", targets="contested_pure",
        why="Deny the exact contested PURE at H1, then take only that PURE with surviving coverage and lift immediately.",
        rationale="COMPARE: a direct PURE_PICK banks faster without ammunition; FIRST_CLAIM pays for one hour of protection when rival coverage suggests contention. Not guaranteed; this option includes its own grab.",
    ),
    WeaponPlay(
        play_id="CUT_THE_EYE", weapon="snap", when="redsign_theirs",
        hour="super_early", combines_with="probe", targets="finder_probe",
        why="Destroy the single known rival eye supporting a redsign, then establish our own probe and survey before harvesting.",
        rationale="COMPARE: REVEAL_SIGN buys our vision without disruption; CUT_THE_EYE spends one SNAP to also remove the single known rival eye. Another sensor or queued replacement may keep the rival operational.",
    ),
)
