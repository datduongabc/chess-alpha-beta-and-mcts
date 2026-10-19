"""Small controlled ablations; reuse the existing engines and exact diagnostics."""
import argparse
import collections
import hashlib
import json
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path

import chess

from engine import SEARCHES
from experiments import load_positions, certify_tactic, certify_material


CONFIGS = {
    "AB basic": ("alphabeta", dict(evaluation_enhanced=False, use_quiescence=False)),
    "AB evaluation only": ("alphabeta", dict(evaluation_enhanced=True, use_quiescence=False)),
    "AB quiescence only": ("alphabeta", dict(evaluation_enhanced=False, use_quiescence=True)),
    "AB both": ("alphabeta", dict(evaluation_enhanced=True, use_quiescence=True)),
    "MC random basic 12": ("mcts", dict(evaluation_enhanced=False, guided=False, rollout_limit=12, tactical_guard=False)),
    "MC random enhanced 12": ("mcts", dict(evaluation_enhanced=True, guided=False, rollout_limit=12, tactical_guard=False)),
    "MC guided 12": ("mcts", dict(evaluation_enhanced=True, guided=True, rollout_limit=12, tactical_guard=False)),
    "MC guided 40": ("mcts", dict(evaluation_enhanced=True, guided=True, rollout_limit=40, tactical_guard=False)),
    "MC guided 12 guard": ("mcts", dict(evaluation_enhanced=True, guided=True, rollout_limit=12, tactical_guard=True)),
}


def analyze(folder):
    metadata = json.loads((folder / "metadata.json").read_text())
    if not metadata.get("completed_utc"):
        raise ValueError("The ablation run is incomplete.")
    for name, expected in metadata["source_sha256"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Run source changed: {name}")
    rows = [json.loads(line) for line in (folder / "searches.jsonl").read_text().splitlines()]
    groups = collections.defaultdict(list)
    for row in rows:
        groups[row["config"], row["budget"], row["objective"]].append(row)
    summary = []
    for (config, budget, objective), group in groups.items():
        summary.append(dict(config=config, budget=budget, objective=objective,
            trials=len(group), successes=sum(r["success"] for r in group),
            rate=statistics.mean(r["success"] for r in group),
            median_elapsed=statistics.median(r["search"]["elapsed"] for r in group),
            median_work=statistics.median(r["search"].get("simulations", r["search"].get("nodes", 0)) for r in group)))
    output = dict(metadata=metadata, searches=len(rows), groups=summary)
    (folder / "analysis.json").write_text(json.dumps(output, indent=2) + "\n")
    md = ["# Follow-up ablations", "", "Computed from the completed serial run. No external engine is used.", "",
          "| Configuration | Seconds | Objective | Success / trials | Rate |", "|---|---:|---|---:|---:|"]
    for g in summary:
        md.append(f"| {g['config']} | {g['budget']:g} | {g['objective']} | {g['successes']}/{g['trials']} | {100*g['rate']:.1f}% |")
    (folder / "analysis.md").write_text("\n".join(md) + "\n")
    tex = [r"\begin{center}\small\setlength{\tabcolsep}{4pt}",
           r"\begin{tabular}{lrrrrr}\toprule",
           r"Configuration & Seconds & Mate & Defense & Material & Combined\%\\\midrule"]
    for config, budget in dict.fromkeys((r["config"], r["budget"]) for r in rows):
        selected = [g for g in summary if g["config"] == config and g["budget"] == budget]
        labels = {g["objective"]: f"{g['successes']}/{g['trials']}" for g in selected}
        overall = sum(g["successes"] for g in selected) / sum(g["trials"] for g in selected)
        tex.append(f"{config} & {budget:g} & {labels['force_mate']} & {labels['avoid_mate']} & {labels['material_after_reply']} & {100*overall:.1f} " + r"\\")
    tex.extend([r"\bottomrule\end{tabular}\end{center}",
        "Combined percentages describe this fixed diagnostic mix. They are not playing-strength ratings."])
    Path("docs/followup_results.tex").write_text("\n".join(tex) + "\n")
    print(f"Analyzed {len(rows)} follow-up searches.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("followup_results/ablation"))
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    if args.analyze_only:
        analyze(args.out)
        return
    if args.out.exists():
        parser.error("Output exists; choose a new --out to preserve measured data.")
    fixtures = load_positions("followup_positions.json")
    certificates = {f["name"]: (certify_material(f) if f["objective"] == "material_after_reply"
                                else certify_tactic(f)) for f in fixtures}
    args.out.mkdir(parents=True)
    sources = ("engine.py", "experiments.py", "followup_experiments.py", "followup_positions.json")
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(), platform=platform.platform(), chess_version=chess.__version__,
        source_sha256={name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sources},
        budgets=[0.1, 0.5], seeds=[7, 8, 9], configs=CONFIGS, positions=len(fixtures),
        timing_policy="Serial searches; preprocessing, root guard and state copying included in the same deadline.",
        scope="Constructed diagnostics, correlated mirrors and repeated seeds; no population ranking.")
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (args.out / "reference_answers.json").write_text(json.dumps(list(certificates.values()), indent=2))
    with (args.out / "searches.jsonl").open("w") as stream:
        for budget in metadata["budgets"]:
            for fixture in fixtures:
                board = fixture["board"]
                for config, (algorithm, kwargs) in CONFIGS.items():
                    for seed in metadata["seeds"] if algorithm == "mcts" else [7]:
                        search = SEARCHES[algorithm](board, budget, **kwargs,
                            **({"seed": seed} if algorithm == "mcts" else {}))
                        move = chess.Move.from_uci(search["move"])
                        if move not in board.legal_moves:
                            raise RuntimeError("Illegal benchmark move.")
                        row = dict(position=fixture["name"], fen=board.fen(), config=config,
                            engine=algorithm, budget=budget, seed=seed, objective=fixture["objective"],
                            success=search["move"] in certificates[fixture["name"]]["accepted_moves"], search=search)
                        stream.write(json.dumps(row) + "\n")
                stream.flush()
                print(f"Ablation {budget:g}s: {fixture['name']}", flush=True)
    metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    analyze(args.out)


if __name__ == "__main__":
    main()
