"""Rebuild the extended analysis from recorded searches; Python standard library only."""
import argparse
import collections
import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, min(len(values) - 1, math.ceil(len(values) * fraction) - 1))]


def paired_interval(rows, repeats=5000):
    """Resample whole starting positions, keeping both colors together."""
    groups = collections.defaultdict(list)
    for row in rows:
        groups[row["position"]].append(float(row["alpha_score"]))
    if any(len(scores) != 2 for scores in groups.values()):
        raise ValueError("Each starting position must contain exactly two color-swapped games.")
    scores = [statistics.mean(group) for group in groups.values()]
    if len(scores) < 4:
        return None
    rng = random.Random(2352344)
    sampled = [statistics.mean(rng.choices(scores, k=len(scores))) for _ in range(repeats)]
    return [percentile(sampled, .025), percentile(sampled, .975)]


def rate(rows):
    return statistics.mean(r["certified_success"] == "True" for r in rows)


def tex_escape(text):
    for char, escaped in (("_", r"\_"), ("%", r"\%"), ("&", r"\&"), ("#", r"\#")):
        text = text.replace(char, escaped)
    return text


def analyze_followup_games(folder):
    """Keep unfinished games censored; show score bounds instead of fake draws."""
    rows = read_csv(folder / "games.csv")
    output = []
    tex = [r"\begin{center}\small\setlength{\tabcolsep}{4pt}",
           r"\begin{tabular}{rrrrrrr}\toprule",
           r"Seconds & Games & AB wins & Draws & AB losses & Unfinished & Score range\%\\\midrule"]
    for budget in sorted({float(row["budget"]) for row in rows}):
        group = [row for row in rows if float(row["budget"]) == budget]
        finished = [row for row in group if row["result"] != "*"]
        wins = sum(float(row["alpha_score"]) == 1 for row in finished)
        draws = sum(float(row["alpha_score"]) == .5 for row in finished)
        losses = len(finished) - wins - draws
        unfinished = len(group) - len(finished)
        lower = (wins + .5 * draws) / len(group)
        upper = (wins + .5 * draws + unfinished) / len(group)
        output.append(dict(budget=budget, games=len(group), starts=len(group)//2,
            alpha_wins=wins, draws=draws, alpha_losses=losses, unfinished=unfinished,
            score_bounds=[lower, upper],
            completed_score=(wins + .5*draws)/len(finished) if finished else None))
        tex.append(f"{budget:g} & {len(group)} & {wins} & {draws} & {losses} & {unfinished} & {100*lower:.1f}--{100*upper:.1f} " + r"\\")
    tex.extend([r"\bottomrule\end{tabular}\end{center}",
        "The range assigns every unfinished game first a loss and then a win for Alpha-beta. It is a censoring bound, not a confidence interval."])
    (folder / "analysis.json").write_text(json.dumps(output, indent=2) + "\n")
    Path("docs/followup_games.tex").write_text("\n".join(tex) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("extended_results"))
    parser.add_argument("--followup-games", type=Path, help="Analyze a completed current-engine game run instead")
    args = parser.parse_args()
    if args.followup_games:
        meta = json.loads((args.followup_games / "metadata.json").read_text())
        if not meta.get("completed_utc"):
            raise ValueError("Incomplete follow-up game run.")
        for name, key in (("engine.py", "engine_sha256"), ("experiments.py", "runner_sha256")):
            if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != meta[key]:
                raise ValueError(f"Follow-up source changed: {name}")
        print(json.dumps(analyze_followup_games(args.followup_games), indent=2))
        return
    root = args.results
    names = ("tactics-enhanced", "tactics-baseline", "games-broad", "games-5s")
    metadata = {name: json.loads((root / name / "metadata.json").read_text()) for name in names}
    # Historical runs retain their exact source when the playable engine changes.
    source = root / "source" if (root / "source").is_dir() else Path(__file__).parent
    current_hash = hashlib.sha256((source / "engine.py").read_bytes()).hexdigest()
    runner_hash = hashlib.sha256((source / "experiments.py").read_bytes()).hexdigest()
    for name, meta in metadata.items():
        if (not meta.get("completed_utc") or meta["engine_sha256"] != current_hash
                or meta["runner_sha256"] != runner_hash):
            raise ValueError(f"Incomplete run or engine hash mismatch: {name}")
    tactics = {name: read_csv(root / name / "positions.csv") for name in names[:2]}
    details = {name: [json.loads(line) for line in (root / name / "searches.jsonl").read_text().splitlines()]
               for name in names}
    references = json.loads((root / "tactics-enhanced" / "reference_answers.json").read_text())
    summary = {"engine_sha256": current_hash, "tactical_groups": [], "stability": [], "games": []}
    for name, rows in tactics.items():
        for budget in sorted({float(r["budget"]) for r in rows}):
            for engine in ("alphabeta", "mcts"):
                for objective in ("force_mate", "avoid_mate"):
                    group = [r for r in rows if float(r["budget"]) == budget and r["engine"] == engine
                             and r["objective"] == objective]
                    per_position = collections.defaultdict(list)
                    for row in group:
                        per_position[row["position"]].append(row)
                    summary["tactical_groups"].append({"variant": name.removeprefix("tactics-"),
                        "budget": budget, "engine": engine, "objective": objective,
                        "successes": sum(r["certified_success"] == "True" for r in group),
                        "trials": len(group), "rate": rate(group),
                        "position_rate_min": min(rate(g) for g in per_position.values()),
                        "position_rate_max": max(rate(g) for g in per_position.values())})
                group = [r for r in rows if float(r["budget"]) == budget and r["engine"] == engine]
                selected = [r["search"] for r in details[name]
                            if r["budget"] == budget and r["engine"] == engine]
                stability = {"variant": name.removeprefix("tactics-"), "budget": budget, "engine": engine,
                             "median_seconds": statistics.median(float(r["elapsed"]) for r in group),
                             "p95_seconds": percentile([float(r["elapsed"]) for r in group], .95),
                             "max_overrun_ms": 1000 * max(float(r["overrun"]) for r in group)}
                if engine == "alphabeta":
                    stability.update(median_depth=statistics.median(r["depth"] for r in selected),
                                     median_nodes=statistics.median(r["nodes"] for r in selected),
                                     median_qnodes=statistics.median(r["qnodes"] for r in selected),
                                     median_cutoffs=statistics.median(r["cutoffs"] for r in selected))
                else:
                    grouped = collections.defaultdict(list)
                    for row in group:
                        grouped[row["position"]].append(row)
                    stability.update(median_simulations=statistics.median(r["simulations"] for r in selected),
                        mean_distinct_moves=statistics.mean(len({r["move"] for r in g}) for g in grouped.values()),
                        mean_modal_share=statistics.mean(max(collections.Counter(r["move"] for r in g).values()) / len(g)
                                                         for g in grouped.values()),
                        agreement_with_alpha=statistics.mean(r["agrees_with_alpha"] == "True" for r in group))
                summary["stability"].append(stability)
    for name in names[2:]:
        rows = read_csv(root / name / "games.csv")
        records = details[name]
        summary["games"].append({"run": name, "budget": float(rows[0]["budget"]),
            "starts": len(rows)//2, "games": len(rows),
            "alpha_wins": sum(float(r["alpha_score"]) == 1 for r in rows),
            "draws": sum(float(r["alpha_score"]) == .5 for r in rows),
            "alpha_losses": sum(float(r["alpha_score"]) == 0 for r in rows),
            "terminations": dict(collections.Counter(r["termination"] for r in rows)),
            "capped_draws": sum(r["termination"] == "Ply cap (adjudicated draw)" for r in rows),
            "alpha_score": statistics.mean(float(r["alpha_score"]) for r in rows),
            "paired_resampling_interval": paired_interval(rows),
            "median_plies": statistics.median(int(r["plies"]) for r in rows),
            "searches": len(records),
            "max_overrun_ms": 1000 * max(max(0, r["elapsed"] - float(rows[0]["budget"])) for r in records),
            "per_start": [{"position": pos, "alpha_score": statistics.mean(float(r["alpha_score"]) for r in rows if r["position"] == pos)}
                          for pos in dict.fromkeys(r["position"] for r in rows)]})
    summary["examples"] = []
    for reference in references:
        if "/ original" not in reference["position"]:
            continue
        rows = [r for r in details["tactics-enhanced"] if r["position"] == reference["position"]
                and r["budget"] == 5 and (r["engine"] == "alphabeta" or r["seed"] == 7)]
        summary["examples"].append({"reference": reference, "choices": [{"engine": r["engine"],
            "move": r["move"], "correct": r["certified_success"],
            "elapsed": r["elapsed"], "search": r["search"]} for r in rows]})
    (root / "analysis.json").write_text(json.dumps(summary, indent=2))
    markdown = ["# Extended experiment analysis", "", "All values below are computed from recorded results.", "",
                "## Certified tactics", "", "| Variant | Budget | Engine | Objective | Successes / trials | Rate |",
                "|---|---:|---|---|---:|---:|"]
    tex = [r"\begin{center}\small", r"\begin{tabular}{llrrrr}\toprule",
           r"Variant & Engine & Budget & Mate / trials & Defense / trials & Overall\%\\\midrule"]
    for group in summary["tactical_groups"]:
        markdown.append(f"| {group['variant']} | {group['budget']:g}s | {group['engine']} | {group['objective']} | {group['successes']} / {group['trials']} | {100*group['rate']:.1f}% |")
        if group["objective"] != "force_mate":
            continue
        defense = next(g for g in summary["tactical_groups"] if all(g[k] == group[k] for k in ("variant", "engine", "budget")) and g["objective"] == "avoid_mate")
        overall = (group["successes"] + defense["successes"]) / (group["trials"] + defense["trials"])
        engine = "Alpha-beta" if group["engine"] == "alphabeta" else "MCTS"
        tex.append(f"{group['variant'].title()} & {engine} & {group['budget']:g}s & {group['successes']}/{group['trials']} & {defense['successes']}/{defense['trials']} & {100*overall:.1f} " + r"\\")
    tex.extend([r"\bottomrule\end{tabular}\end{center}", r"\subsubsection*{Search cost and MCTS stability}",
                r"\begin{center}\small\begin{tabular}{llrrrr}\toprule",
                r"Variant & Budget & AB depth & AB tactical nodes & MCTS simulations & Distinct moves\\\midrule"])
    for a in summary["stability"]:
        if a["engine"] != "alphabeta": continue
        m = next(r for r in summary["stability"] if r["engine"] == "mcts" and r["variant"] == a["variant"] and r["budget"] == a["budget"])
        tex.append(f"{a['variant'].title()} & {a['budget']:g}s & {a['median_depth']:g} & {a['median_qnodes']:g} & {m['median_simulations']:g} & {m['mean_distinct_moves']:.2f} " + r"\\")
    tex.extend([r"\bottomrule\end{tabular}\end{center}",
                "Depth, tactical nodes and simulations are medians. Distinct moves is the mean number",
                "of different suggestions across five seeds per position; it ranges from 1 to 5.",
                "These work counters measure different operations and must not be compared as equivalent nodes.",
                r"\subsubsection*{Wall-clock measurements}",
                r"\begin{center}\small\setlength{\tabcolsep}{4pt}\begin{tabular}{lrrrrr}\toprule",
                r"Variant & Budget & AB median (s) & MCTS median (s) & MCTS p95 (s) & Max overrun (ms)\\\midrule"])
    for a in summary["stability"]:
        if a["engine"] != "alphabeta": continue
        m = next(r for r in summary["stability"] if r["engine"] == "mcts" and r["variant"] == a["variant"] and r["budget"] == a["budget"])
        tex.append(f"{a['variant'].title()} & {a['budget']:g}s & {a['median_seconds']:.4f} & {m['median_seconds']:.4f} & {m['p95_seconds']:.4f} & {max(a['max_overrun_ms'],m['max_overrun_ms']):.3f} " + r"\\")
    tex.extend([r"\bottomrule\end{tabular}\end{center}",
                "Small overrun is measured and retained, not scored as a time-forfeit loss. Early proven mates can leave allocated time unused.",
                r"\subsubsection*{Color-swapped games}",
                r"\begin{center}\small\begin{tabular}{rrrrrrr}\toprule",
                r"Budget & Starts & Games & AB wins & Draws & AB losses & AB score\%\\\midrule"])
    markdown.extend(["", "## Paired games", "", "| Budget | Starts | Games | Alpha wins / draws / losses | Score | Capped draws |", "|---:|---:|---:|---|---:|---:|"])
    for g in summary["games"]:
        markdown.append(f"| {g['budget']:g}s | {g['starts']} | {g['games']} | {g['alpha_wins']} / {g['draws']} / {g['alpha_losses']} | {100*g['alpha_score']:.1f}% | {g['capped_draws']} |")
        tex.append(f"{g['budget']:g}s & {g['starts']} & {g['games']} & {g['alpha_wins']} & {g['draws']} & {g['alpha_losses']} & {100*g['alpha_score']:.1f} " + r"\\")
    tex.extend([r"\bottomrule\end{tabular}\end{center}"])
    for g in summary["games"]:
        interval = g["paired_resampling_interval"]
        if interval:
            tex.append(f"For {g['budget']:g}s, resampling the {g['starts']} paired starts 5,000 times gives a descriptive 95\\% percentile interval [{100*interval[0]:.1f}\\%, {100*interval[1]:.1f}\\%] for Alpha-beta's score.")
    tex.extend(["This resampling keeps both colors together and uses seed 2352344. It reflects",
                "variation among the selected starts, not a representative chess population.",
                "No interval is reported for the two-start 5s subset: it is too small to support a useful precision claim."])
    tex.extend([r"\begin{figure}[ht]\centering",
                r"\begin{tikzpicture}\begin{axis}[width=.94\textwidth,height=6cm,xmode=log,",
                r"xlabel={Allocated seconds per search},ylabel={Certified objective success (\%)},",
                r"xtick={.1,1,5},xticklabels={0.1,1,5},ymin=0,ymax=105,grid=major,",
                r"legend style={at={(.5,-.25)},anchor=north,legend columns=2,font=\small}]"])
    for variant, engine, style in (("enhanced", "alphabeta", "teal,mark=*"),
                                   ("enhanced", "mcts", "orange,mark=square*"),
                                   ("baseline", "alphabeta", "teal,dashed,mark=o"),
                                   ("baseline", "mcts", "orange,dashed,mark=square")):
        coordinates = []
        for budget in sorted({g["budget"] for g in summary["tactical_groups"] if g["variant"] == variant}):
            selected = [g for g in summary["tactical_groups"] if g["variant"] == variant and g["engine"] == engine and g["budget"] == budget]
            success = sum(g["successes"] for g in selected) / sum(g["trials"] for g in selected)
            coordinates.append(f"({budget},{100*success:.3f})")
        tex.append(r"\addplot[" + style + "] coordinates {" + " ".join(coordinates) + "};")
        tex.append(r"\addlegendentry{" + variant.title() + " " + ("Alpha-beta" if engine == "alphabeta" else "MCTS") + "}")
    tex.extend([r"\end{axis}\end{tikzpicture}",
                r"\caption{Success on the fixed certified corpus, combining attack and defense objectives. Baseline was tested at 0.1 and 1 seconds only. Lines connect measured budgets and do not predict intermediate performance.}\end{figure}"])
    discussion = [
        "The certified test answers a limited, objective question about each selected move.",
        "It does not use agreement between the two engines as a correctness label.",
        "A high agreement rate can reflect the same mistake; different suggestions can both satisfy the objective."]
    for engine in ("alphabeta", "mcts"):
        name = "Alpha-beta" if engine == "alphabeta" else "MCTS"
        groups = [g for g in summary["tactical_groups"] if g["variant"] == "enhanced" and g["engine"] == engine and g["budget"] == 5]
        attack = next(g for g in groups if g["objective"] == "force_mate")
        defense = next(g for g in groups if g["objective"] == "avoid_mate")
        discussion.append(f"At 5s, enhanced {name} succeeds on {attack['successes']}/{attack['trials']} attacking trials and {defense['successes']}/{defense['trials']} defensive trials. "
                          + ("The MCTS denominators include five seeds on each of six cases." if engine == "mcts" else "Alpha-beta runs once on each of six cases per objective."))
    discussion.extend([r"\paragraph{Configuration and cost tradeoff.}"])
    for engine in ("alphabeta", "mcts"):
        def combined(variant):
            groups = [g for g in summary["tactical_groups"] if g["variant"] == variant and g["engine"] == engine and g["budget"] == 1]
            return sum(g["successes"] for g in groups) / sum(g["trials"] for g in groups)
        name = "Alpha-beta" if engine == "alphabeta" else "MCTS"
        discussion.append(f"At 1s, {name}'s combined certified success is {100*combined('baseline'):.1f}\\% for baseline and {100*combined('enhanced'):.1f}\\% for enhanced.")
    m1 = next(r for r in summary["stability"] if r["engine"] == "mcts" and r["variant"] == "baseline" and r["budget"] == 1)
    m2 = next(r for r in summary["stability"] if r["engine"] == "mcts" and r["variant"] == "enhanced" and r["budget"] == 1)
    discussion.append(f"Median completed MCTS simulations at 1s are {m1['median_simulations']:g} baseline versus {m2['median_simulations']:g} enhanced. These differ because both rollout length and per-action policy cost changed.")
    discussion.extend(["Quiescence extends tactical lines but consumes work that could otherwise increase nominal depth.",
                       "Guided simulations introduce useful tactical bias and additional move-scoring cost.",
                       "A configuration's effect is therefore a measured cost/quality tradeoff, not a guarantee that more features improve every position.",
                       r"\paragraph{Seed variation and agreement.}"])
    m5 = next(r for r in summary["stability"] if r["engine"] == "mcts" and r["variant"] == "enhanced" and r["budget"] == 5)
    discussion.append(f"At 5s, MCTS chooses {m5['mean_distinct_moves']:.2f} distinct moves on average across five seeds per case; its average modal share is {100*m5['mean_modal_share']:.1f}\\%, and agreement with Alpha-beta is {100*m5['agreement_with_alpha']:.1f}\\%.")
    discussion.extend(["Low variation is repeatability, not proof of correctness. With multiple certified answers, disagreement is not automatically an error.",
                       "Completed-visit counts and sampled utility should be inspected together; root utility is not a calibrated win probability.",
                       "Alpha-beta centipawns and MCTS utility remain different units and are not ranked on a common score scale.",
                       r"\paragraph{Concrete, auditable examples.}",
                       "Examples use seed 7, the first scheduled seed; aggregate tables include all five seeds and both colors."])
    for example in summary["examples"]:
        ref = example["reference"]
        discussion.append(r"\begin{quote}\small\textbf{" + tex_escape(ref["position"]) + "}. " +
                          "Accepted UCI moves: " + ", ".join(r"\texttt{" + move + "}" for move in ref["accepted_moves"]) + ".")
        for choice in example["choices"]:
            name = "Alpha-beta" if choice["engine"] == "alphabeta" else "MCTS (seed 7)"
            result = "satisfies" if choice["correct"] else "fails"
            search = choice["search"]
            counter = f"completed depth {search['depth']}" if choice["engine"] == "alphabeta" else f"{search['simulations']} completed simulations"
            discussion.append(f"{name} selects \\texttt{{{choice['move']}}}, {result} the certified objective, and reports {counter} in {choice['elapsed']:.3f}s.")
        discussion.append(r"\end{quote}")
    maneuver = next(e for e in summary["examples"] if e["reference"]["position"] == "Unique queen maneuver / force_mate / original")
    sampled = next(c for c in maneuver["choices"] if c["engine"] == "mcts")
    roots = {r["move"]: r for r in sampled["search"]["root_moves"]}
    if sampled["move"] == "e3g1" and "e3e7" in roots:
        chosen, certified = roots["e3g1"], roots["e3e7"]
        discussion.extend([r"\paragraph{Why the fast-mate metric is not a strength verdict.}",
            r"In the unique queen maneuver, the certified line is \texttt{e3e7 d8c8 e7c7}: Qe7+, Kc8, Qc7 mate. There is only one legal defensive reply after Qe7+.",
            f"MCTS instead captures the rook with \\texttt{{e3g1}} (Qxg1), giving it {chosen['visits']} visits and mean utility {chosen['value']:.3f}; the certified first move gets {certified['visits']} visits and utility {certified['value']:.3f}.",
            "The capture improves material but does not force mate within the benchmark's three-ply bound. This measurement alone does not establish that the capture loses or is globally inferior.",
            "Alpha-beta's mate score favors a shorter forced win. MCTS gives every terminal win the same utility and its cutoff rewards material; it has no explicit mate-speed reward.",
            "Those scoring choices and sampled continuations can favor a slower material gain. The observed visit/utility allocation is evidence of the choice; attributing all failures to this mechanism would require further controlled tests.",
            "Increasing computation can reinforce a policy's preferred objective instead of improving a different diagnostic score. Full-game outcomes must therefore accompany the tactical table."])
    discussion.extend([r"\paragraph{Game results and practical meaning.}",
                       "A color-swapped game tests the full decision sequence, while a certified tactic tests one bounded decision. Neither substitutes for the other.",
                       "The 0.5s and 5s studies use different sets of starts. Their aggregate game scores therefore cannot isolate the causal effect of increasing time."])
    for game in summary["games"]:
        discussion.append(f"At {game['budget']:g}s, {game['capped_draws']} of {game['games']} games reached the cap and {game['draws'] - game['capped_draws']} were natural draws. Alpha-beta's score is {100*game['alpha_score']:.1f}\\%; the median game length is {game['median_plies']:g} plies.")
    discussion.extend(["Report wins, natural draws and capped draws separately before treating a score as playing strength.",
                       "The selected endgames and opening positions are convenience starts, not a random chess population.",
                       "The first move of a fixture may belong to Black; swapping engine colors preserves that same starting state.",
                       r"\paragraph{What remains unproven.}",
                       "The three constructed placement families are low-material diagnostic tasks. Mirror cases and repeated seeds are correlated, and five seeds do not resolve rare failures.",
                       "No reference engine evaluates arbitrary middlegame moves, no external puzzle corpus is held out, and no Elo estimate is justified.",
                       "Longer simulations and more visits do not guarantee an optimal chess move. The contribution is transparent, independently checked bounded tactics and reproducible comparison of these implementations."])
    Path("docs/extended_discussion.tex").write_text("\n".join(discussion) + "\n")
    markdown.extend(["", "## Interpretation", "",
        "The certified objective measures fast forced mate or survival within a short bound. Failure is not proof that a move loses the full game.", "",
        "Alpha-beta prefers shorter proven mates. MCTS rewards terminal wins equally and uses a material-sensitive cutoff, so a slower material gain may score well in simulations.", "",
        "Baseline/enhanced changes several features together. The budget series, seeds and mirrors are repeated diagnostics, not independent population samples.", "",
        "The 0.5s and 5s game subsets use different starts; their aggregate scores do not isolate the effect of thinking time.", "",
        "## Auditable 5s examples (MCTS seed 7)", "",
        "| Position | Accepted UCI moves | Alpha-beta | MCTS |",
        "|---|---|---|---|"])
    for example in summary["examples"]:
        choices = {c["engine"]: c for c in example["choices"]}
        def label(choice):
            return choice["move"] + (" (passes)" if choice["correct"] else " (fails bounded objective)")
        markdown.append("| " + example["reference"]["position"] + " | " + ", ".join(example["reference"]["accepted_moves"]) + " | " + label(choices["alphabeta"]) + " | " + label(choices["mcts"]) + " |")
    (root / "analysis.md").write_text("\n".join(markdown) + "\n")
    Path("docs/extended_results.tex").write_text("\n".join(tex) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
