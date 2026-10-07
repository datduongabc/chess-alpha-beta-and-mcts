# Homework submission

Run the packaging command below from the repository root after updating and
compiling the report. The GitHub repository keeps source and completed
measurements; virtual environments, scratch runs, LaTeX intermediates and ZIP
archives remain local.

Before LMS submission, verify the group information in `docs/report.tex` and rename the
zip to `HW2_YOURNAME.zip` as the assignment requires. After editing group details,
recreate the archive so it contains the updated PDF and source:

```sh
python -m zipfile -c HW2_YOURNAME.zip README.md .gitignore docs/GROUP.md docs/SUBMISSION.md THIRD_PARTY_NOTICES.md homework_2_spec.md requirements.txt engine.py app.py index.html experiments.py analyze_results.py positions.json tactics.json test_homework.py followup_experiments.py followup_positions.json followup_game_starts.json followup_results/ablation followup_results/games-matched followup_results/study_protocol.json docs/followup_results.tex docs/followup_games.tex docs/report.pdf docs/report.tex docs/hcmut-report.cls docs/graphics docs/HCMUT_TEMPLATE_LICENSE.txt docs/HCMUT_TEMPLATE_README.txt docs/measured_results.tex docs/enhanced_results.tex docs/extended_results.tex docs/extended_discussion.tex docs/gui.png docs/python-chess-GPL-3.txt sample_results enhanced_results extended_results/tactics-enhanced extended_results/tactics-baseline extended_results/games-broad extended_results/games-5s extended_results/analysis.json extended_results/analysis.md extended_results/study_protocol.json extended_results/source
```

The supplied deadline is 8 November 2026 at 23:59. Confirm the course timezone on LMS.
Only one submission is required per group.
