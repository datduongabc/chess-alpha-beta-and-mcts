"""Equal-time comparisons. No GUI work or simultaneous search in timed runs."""
import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn

from app import build_board
from engine import SEARCHES


def load_positions(path=None):
    path = Path(path) if path else Path(__file__).with_name("positions.json")
    fixtures = json.loads(path.read_text())
    for fixture in fixtures:
        fixture["board"] = build_board(fixture)
        if fixture["board"].outcome(claim_draw=True):
            raise ValueError(f"Terminal benchmark position: {fixture['name']}")
    return fixtures


def can_force_mate(board, attacker, plies):
    """Exact bounded AND/OR proof; no heuristic or timed-search engine is used."""
    outcome = board.outcome(claim_draw=True)
    if outcome:
        return outcome.winner == attacker
    if plies <= 0:
        return False
    attacking = board.turn == attacker
    for move in list(board.legal_moves):
        if attacking and plies == 1 and not board.gives_check(move):
            continue
        board.push(move)
        try:
            forced = can_force_mate(board, attacker, plies - 1)
        finally:
            board.pop()
        if forced == attacking:
            return attacking
    return not attacking


def certify_tactic(fixture):
    """Check every root action and every defense within the declared mate bound."""
    objective, plies = fixture.get("objective"), fixture.get("mate_plies")
    if objective not in ("force_mate", "avoid_mate") or plies not in (1, 3):
        raise ValueError("Tactical objectives: force_mate/avoid_mate; bound: 1 or 3 plies.")
    board = fixture["board"].copy(stack=True)
    attacker = board.turn if objective == "force_mate" else not board.turn
    accepted = []
    legal = sorted(board.legal_moves, key=lambda move: move.uci())
    for move in legal:
        board.push(move)
        try:
            won = can_force_mate(board, attacker, plies - 1 if objective == "force_mate" else plies)
        finally:
            board.pop()
        if won == (objective == "force_mate"):
            accepted.append(move.uci())
    if not accepted or len(accepted) == len(legal):
        raise ValueError(f"Tactic must have both successful and unsuccessful actions: {fixture['name']}")
    if (objective == "force_mate" and plies == 3
            and any(board.gives_check(m) and is_mate_after(board, m) for m in legal)):
        raise ValueError("Mate-in-two fixture has a mate in one.")
    if "expected_moves" in fixture and accepted != sorted(fixture["expected_moves"]):
        raise ValueError(f"Unverified expected moves: {fixture['name']}")
    return {"position": fixture["name"], "fen": board.fen(), "objective": objective,
            "mate_plies": plies, "accepted_moves": accepted, "legal_moves": len(legal),
            "scope": "Forced mate within the bound; defense success does not imply eventual survival."}


def is_mate_after(board, move):
    child = board.copy(stack=True)
    child.push(move)
    return child.is_checkmate()


def certify_material(fixture):
    """Exhaustive two-ply material diagnostic, independent of search heuristics.

    A root move is accepted when its worst legal reply maximizes material
    balance. This checks exchanges/promotion, not full-game move quality.
    """
    values = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
              chess.ROOK: 500, chess.QUEEN: 900}
    board = fixture["board"].copy(stack=True)
    player = board.turn
    def balance():
        return sum(value * (len(board.pieces(piece, player)) -
                            len(board.pieces(piece, not player)))
                   for piece, value in values.items())
    initial = balance()
    def score():
        outcome = board.outcome(claim_draw=True)
        if outcome:
            return 0 if outcome.winner is None else (100000 if outcome.winner == player else -100000)
        return balance() - initial
    scores = {}
    for move in sorted(board.legal_moves, key=lambda m: m.uci()):
        board.push(move)
        try:
            if board.outcome(claim_draw=True):
                worst = score()
            else:
                responses = []
                for reply in list(board.legal_moves):
                    board.push(reply)
                    try:
                        responses.append(score())
                    finally:
                        board.pop()
                worst = min(responses)
            scores[move.uci()] = worst
        finally:
            board.pop()
    best = max(scores.values())
    return {"position": fixture["name"], "fen": board.fen(),
            "objective": "material_after_reply", "best_gain": best,
            "accepted_moves": [move for move, value in scores.items() if value == best],
            "move_gains": scores, "scope": "Best worst-case material gain after one reply; not an optimal-play verdict."}


def run_search(board, algorithm, seconds, seed, enhanced=True):
    kwargs = {"seed": seed} if algorithm == "mcts" else {}
    return SEARCHES[algorithm](board, seconds, enhanced=enhanced, **kwargs)


def run_game(fixture, seconds, white_engine, seed, max_plies, enhanced=True):
    board = fixture["board"].copy(stack=True)
    black_engine = "mcts" if white_engine == "alphabeta" else "alphabeta"
    records = []
    for ply in range(max_plies):
        outcome = board.outcome(claim_draw=True)
        if outcome:
            break
        algorithm = white_engine if board.turn else black_engine
        before = board.fen()
        result = run_search(board, algorithm, seconds, seed + ply, enhanced)
        move = chess.Move.from_uci(result["move"])
        if move not in board.legal_moves:
            raise RuntimeError(f"{algorithm} returned an illegal move.")
        records.append({"ply": ply, "fen": before, "engine": algorithm,
                        "seed": seed + ply, **result})
        board.push(move)
    outcome = board.outcome(claim_draw=True)
    result_text = outcome.result() if outcome else "*"
    game = chess.pgn.Game.from_board(board)
    game.headers.update(Event="Chess Search Duel benchmark", Site="Local",
                        White=white_engine, Black=black_engine, Result=result_text,
                        TimeControl=f"{seconds}s per move", Seed=str(seed),
                        SearchVariant="enhanced" if enhanced else "baseline")
    termination = (outcome.termination.name.replace("_", " ").title() if outcome
                   else "Ply cap (unfinished)")
    game.headers["Termination"] = termination
    return {"variant": "enhanced" if enhanced else "baseline",
            "position": fixture["name"], "budget": seconds,
            "white": white_engine, "black": black_engine, "seed": seed,
            "result": result_text, "termination": termination,
            "plies": len(records), "searches": records, "pgn": str(game)}


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["enhanced", "baseline"], default="enhanced")
    parser.add_argument("--mode", choices=["positions", "games", "both"], default="positions")
    parser.add_argument("--budgets", nargs="+", type=float, default=[0.1, 0.5, 1.0])
    parser.add_argument("--seeds", type=int, default=20, help="MCTS repeats per position/budget")
    parser.add_argument("--seed", type=int, default=7, help="First recorded random seed")
    parser.add_argument("--game-starts", type=int, default=10, help="Distinct paired starting positions")
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--position-limit", type=int, default=12)
    parser.add_argument("--positions", type=Path, help="Alternative fixture JSON")
    parser.add_argument("--out", type=Path, default=Path("results") /
                        datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    if (any(not math.isfinite(b) or not 0.01 <= b <= 5 for b in args.budgets)
            or not 1 <= args.seeds <= 1000 or not 1 <= args.max_plies <= 1024
            or args.position_limit < 1 or args.game_starts < 1 or args.seed < 0):
        parser.error("Budgets: 0.01–5 s; repeats: 1–1000; ply cap: 1–1024; positive limits and nonnegative seed.")
    fixtures = load_positions(args.positions)[:args.position_limit]
    if not fixtures:
        parser.error("Provide at least one position.")
    certificates = {f["name"]: certify_tactic(f) for f in fixtures if f.get("objective")}
    if args.out.exists():
        parser.error("Output directory already exists; choose a new --out to preserve previous results.")
    args.out.mkdir(parents=True)
    metadata = {"started_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "platform": platform.platform(),
                "processor": platform.processor(), "chess_version": chess.__version__,
                "command": vars(args) | {"out": str(args.out), "positions": str(args.positions)},
                "fixture_sha256": hashlib.sha256((args.positions or Path(__file__).with_name("positions.json")).read_bytes()).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "engine_sha256": hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest(),
                "draw_policy": "Automatically claim threefold and fifty-move draws",
                "timing_policy": "Fresh search, serial, includes state copying and evaluations; no GUI",
                "overrun_policy": "Retain move, report elapsed time and excess; no time-forfeit claims"}
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (args.out / "reference_answers.json").write_text(json.dumps(list(certificates.values()), indent=2))
    position_rows, game_rows, move_rows = [], [], []
    with (args.out / "searches.jsonl").open("w") as detailed, (args.out / "games.pgn").open("w") as pgn:
        for budget in args.budgets:
            if args.mode in ("positions", "both"):
                for fixture in fixtures:
                    board = fixture["board"]
                    alpha_move = None
                    for algorithm in SEARCHES:
                        for repeat in range(args.seeds if algorithm == "mcts" else 1):
                            seed = args.seed + repeat
                            result = run_search(board, algorithm, budget, seed, args.variant == "enhanced")
                            if algorithm == "alphabeta":
                                alpha_move = result["move"]
                            child = board.copy(stack=True)
                            child.push_uci(result["move"])
                            solved = child.is_checkmate() if fixture.get("mate_in_one") else None
                            row = {"position": fixture["name"], "category": fixture["category"],
                                   "fen": board.fen(), "engine": algorithm, "budget": budget,
                                   "seed": seed if algorithm == "mcts" else "",
                                   "move": result["move"], "solved_mate": solved,
                                   "objective": fixture.get("objective", ""),
                                   "certified_success": (result["move"] in certificates[fixture["name"]]["accepted_moves"]
                                                         if fixture["name"] in certificates else None),
                                   "agrees_with_alpha": result["move"] == alpha_move,
                                   "elapsed": result["elapsed"],
                                   "overrun": max(0, result["elapsed"] - budget),
                                   "variant": args.variant, "qnodes": result.get("qnodes", ""),
                                   "depth": result.get("depth", ""), "nodes": result.get("nodes", ""),
                                   "cutoffs": result.get("cutoffs", ""),
                                   "simulations": result.get("simulations", ""),
                                   "rollout_plies": result.get("rollout_plies", "")}
                            position_rows.append(row)
                            detailed.write(json.dumps({"experiment": "position", **row, "search": result}) + "\n")
                    print(f"Positions: {budget:g}s · {fixture['name']}", flush=True)
            if args.mode in ("games", "both"):
                # Quiet/endgame starts first: mate-in-one fixtures would bias games.
                starts = sorted(fixtures, key=lambda f: f["category"] == "tactic")[:args.game_starts]
                for pair, fixture in enumerate(starts):
                    for white_engine in SEARCHES:
                        game = run_game(fixture, budget, white_engine, args.seed + pair * 1024, args.max_plies, args.variant == "enhanced")
                        score_white = {"1-0": 1, "0-1": 0, "1/2-1/2": 0.5, "*": None}[game["result"]]
                        alpha_score = (None if score_white is None else
                                       score_white if white_engine == "alphabeta" else 1 - score_white)
                        row = {key: value for key, value in game.items() if key not in ("searches", "pgn")}
                        row.update(pair=pair, alpha_score=alpha_score)
                        game_rows.append(row)
                        pgn.write(game["pgn"] + "\n\n")
                        for move in game["searches"]:
                            detailed.write(json.dumps({"experiment": "game", "pair": pair,
                                                       "white": white_engine, "budget": budget, **move}) + "\n")
                            move_rows.append({"pair": pair, "white": white_engine,
                                              "budget": budget, "ply": move["ply"],
                                              "engine": move["engine"], "elapsed": move["elapsed"]})
                        print(f"Game: {budget:g}s · {fixture['name']} · White {white_engine} · {game['result']}", flush=True)
    write_csv(args.out / "positions.csv", position_rows)
    write_csv(args.out / "games.csv", game_rows)
    write_csv(args.out / "game-moves.csv", move_rows)
    summaries = []
    for budget in args.budgets:
        for algorithm in SEARCHES:
            rows = [r for r in position_rows if r["budget"] == budget and r["engine"] == algorithm]
            timings = sorted(r["elapsed"] for r in rows)
            tactics = [r for r in rows if r["solved_mate"] is not None]
            games = [r for r in game_rows if r["budget"] == budget]
            finished = [r for r in games if r["alpha_score"] is not None]
            summary = {"budget": budget, "engine": algorithm, "position_searches": len(rows),
                       "mate_solve_rate": statistics.mean(r["solved_mate"] for r in tactics) if tactics else None,
                       "median_seconds": statistics.median(timings) if timings else None,
                       "p95_seconds": timings[math.ceil(len(timings) * .95) - 1] if timings else None,
                       "paired_games": len(games),
                       "game_score": statistics.mean(r["alpha_score"] if algorithm == "alphabeta" else
                                                     1-r["alpha_score"] for r in finished) if finished else None,
                       "finished_games": len(finished),
                       "unfinished_games": len(games) - len(finished)}
            certified = [r for r in rows if r["certified_success"] is not None]
            summary.update(variant=args.variant, certified_trials=len(certified),
                           certified_success_rate=statistics.mean(r["certified_success"] for r in certified) if certified else None)
            summaries.append(summary)
    (args.out / "summary.json").write_text(json.dumps(summaries, indent=2))
    metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Saved reproducible results to {args.out.resolve()}")


if __name__ == "__main__":
    main()
