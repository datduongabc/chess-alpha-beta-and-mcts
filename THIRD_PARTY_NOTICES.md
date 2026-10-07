# Dependencies and references

`python-chess` 1.999 / `chess` 1.11.2 by Niklas Fiekas and contributors:
GPL-3.0-or-later. Installed through `requirements.txt`, not vendored into this
project. Its documentation: https://python-chess.readthedocs.io/ and source:
https://github.com/niklasf/python-chess . Observe its terms when redistributing
the library or distributing a combined application. `docs/python-chess-GPL-3.txt`
contains the dependency's GPL text for reference.

The assignment and these downloaded references were supplied locally:

- **Chess**: separation of GUI/state/search; algorithm selection and highlighting.
  Relevant files: `Chess/GUI/chess_gui.py`, `AI/Minimax/minimax.py`,
  `AI/MCTS/monte_carlo_tree_search.py`.
- **chessmc**: python-chess board wrapper; visits/value per MCTS root action.
  Relevant files: `chessmc/state.py`, `chessmc/mcts.py`, `static/index.html`.
- **Chess-engine**: readable alpha-beta structure and Tkinter interaction ideas.
  Relevant files: `chess_engine.py`, GUI in `chess.ipynb`.

No source code, model weights, or images from these repositories were copied.
No license file was present in any of the three supplied downloads; one README
claims MIT but omits its referenced license. Their original remote URLs were
not established by the downloads, so no upstream ownership/URL is invented.

The board uses CSS and Unicode chess characters; no chess.com or repository
piece-image assets are included. Screenshots are of this application.

## Report template

The report uses the user-supplied `HCMUT_Report_Template__3_` download of
`hoang-himself/hcmut-report`: https://github.com/hoang-himself/hcmut-report .
Its README identifies revision `350906b86be7adae1c953217029cbe12ad4f6ac5`.
The original class and university-logo files are copied without modification
to `docs/hcmut-report.cls` and `docs/graphics/hcmut.png`. The supplied licence
and source README are included as `docs/HCMUT_TEMPLATE_LICENSE.txt` and
`docs/HCMUT_TEMPLATE_README.txt`. The report replaces the demonstration text
with the homework content and suppresses the unspecified advisor row from
the document preamble. No support from the original template author is implied.
