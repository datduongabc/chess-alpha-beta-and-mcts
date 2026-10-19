# Homework submission

Run the packaging command below from the repository root after updating and
compiling the report. The GitHub repository keeps source and completed
measurements; virtual environments, scratch runs, LaTeX intermediates and ZIP
archives remain local.

Before LMS submission, verify the group information in `docs/report.tex` and rename the
zip to `HW2_YOURNAME.zip` as the assignment requires. After editing group details,
commit the updated group details, PDF and source, then recreate the archive.
The command archives committed `HEAD`; uncommitted edits are omitted. Tracked
paths are preserved, while local caches, environments and scratch runs are excluded:

```sh
git archive --format=zip --output=HW2_YOURNAME.zip HEAD README.md .gitignore THIRD_PARTY_NOTICES.md homework_2_spec.md requirements.txt chess_duel benchmarks fixtures tests results docs
```

The supplied deadline is 8 November 2026 at 23:59. Confirm the course timezone on LMS.
Only one submission is required per group.
