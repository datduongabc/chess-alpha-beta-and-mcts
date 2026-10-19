"""Run with: python -m unittest discover -s tests -v. No test dependencies."""
import threading
import unittest
import json
from pathlib import Path
import urllib.request
import urllib.error

import chess

from chess_duel.engine import alphabeta, mcts, evaluate, negamax, Node, select_child


class SearchTests(unittest.TestCase):
    def test_alpha_beta_finds_mate_for_both_colors(self):
        for fen in ("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
                    "8/8/8/8/8/6k1/5q2/7K b - - 0 1"):
            board = chess.Board(fen)
            result = alphabeta(board, 0.15, max_depth=3)
            self.assertIn(chess.Move.from_uci(result["move"]), board.legal_moves)
            board.push_uci(result["move"])
            self.assertTrue(board.is_checkmate())

    def test_searches_preserve_board_and_repetition_history(self):
        board = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
        before = board.fen(), list(board.move_stack)
        for search in (alphabeta, mcts):
            result = search(board, 0.03)
            self.assertIn(chess.Move.from_uci(result["move"]), board.legal_moves)
            self.assertEqual(before, (board.fen(), list(board.move_stack)))

    def test_terminal_roots_and_claimable_draws_have_no_move(self):
        boards = [chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"),
                  chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")]
        repetition = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
            repetition.push_uci(move)
        boards.append(repetition)
        for board in boards:
            for search in (alphabeta, mcts):
                self.assertIsNone(search(board, 0.02)["move"])

    def test_zero_budget_and_cancel_return_legal_fallback(self):
        event = threading.Event()
        event.set()
        for search in (alphabeta, mcts):
            for budget, cancel in ((0, None), (10, event)):
                result = search(chess.Board(), budget, cancel=cancel)
                self.assertIn(chess.Move.from_uci(result["move"]), chess.Board().legal_moves)
                self.assertLess(result["elapsed"], 0.1)

    def test_negamax_matches_unpruned_minimax(self):
        def plain(board, depth, ply=0):
            outcome = board.outcome(claim_draw=True)
            if outcome:
                return -100000 + ply if outcome.winner is not None else 0
            if depth == 0:
                return evaluate(board, enhanced=False) * (1 if board.turn else -1)
            values = []
            for move in list(board.legal_moves):
                board.push(move)
                values.append(-plain(board, depth - 1, ply + 1))
                board.pop()
            return max(values)

        for fen in ("8/8/8/4k3/8/4K3/4P3/8 w - - 0 1",
                    "8/8/8/4k3/8/4K3/4P3/8 b - - 0 1"):
            board = chess.Board(fen)
            score, _ = negamax(board, 3, enhanced=False)
            self.assertEqual(score, plain(board, 3))

    def test_mcts_unique_actions_and_fixed_seed(self):
        kwargs = dict(seed=7, iterations=80, rollout_limit=4)
        first = mcts(chess.Board(), 20, **kwargs)
        second = mcts(chess.Board(), 20, **kwargs)
        rows = first["root_moves"]
        self.assertEqual(len(rows), len({r["move"] for r in rows}))
        self.assertEqual(sum(r["visits"] for r in rows), 80)
        self.assertEqual(first["move"], second["move"])
        self.assertEqual(rows, second["root_moves"])

    def test_mcts_chooses_mate(self):
        board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        result = mcts(board, 20, seed=2, iterations=800, rollout_limit=4)
        board.push_uci(result["move"])
        self.assertTrue(board.is_checkmate())

    def test_mcts_opponent_prefers_root_loss(self):
        node = Node(chess.BLACK, [], visits=20)
        favorable = Node(chess.WHITE, [], visits=10, value=8)
        refutation = Node(chess.WHITE, [], visits=10, value=-8)
        node.children = [favorable, refutation]
        self.assertIs(select_child(node, chess.WHITE, 0), refutation)
        node.turn = chess.WHITE
        self.assertIs(select_child(node, chess.WHITE, 0), favorable)


class EnhancedSearchTests(unittest.TestCase):
    def test_quiescence_can_be_isolated_from_enhanced_evaluation(self):
        board = chess.Board("3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1")
        result = alphabeta(board, 5, max_depth=1, evaluation_enhanced=False,
                           use_quiescence=True)
        self.assertNotEqual(result["move"], "d1d5")
        self.assertGreater(result["qnodes"], 0)
        self.assertFalse(result["evaluation_enhanced"])

    def test_mcts_guard_proves_immediate_mate_without_samples(self):
        for board in (chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"),
                      chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1").mirror()):
            before = board.fen()
            result = mcts(board, 1, iterations=0, tactical_guard=True)
            self.assertEqual(result["tactical_proof"], "mate in one")
            self.assertEqual(result["simulations"], 0)
            self.assertEqual(board.fen(), before)
            board.push_uci(result["move"])
            self.assertTrue(board.is_checkmate())

    def test_mcts_guard_rejects_proven_immediate_loss(self):
        from chess_duel.engine import screen_root_moves
        board = chess.Board("7r/8/8/8/Q7/8/5K2/7k b - - 0 1")
        # Find the safe moves independently by enumerating all replies.
        safe = []
        for move in list(board.legal_moves):
            child = board.copy(stack=True)
            child.push(move)
            loses = False
            for reply in list(child.legal_moves):
                child.push(reply)
                loses |= child.is_checkmate()
                child.pop()
            if not loses:
                safe.append(move.uci())
        before = board.fen()
        moves, mate, rejected = screen_root_moves(board)
        self.assertIsNone(mate)
        self.assertTrue(safe)
        self.assertGreater(rejected, 0)
        self.assertEqual(sorted(m.uci() for m in moves), sorted(safe))
        self.assertEqual(board.fen(), before)

    def test_quiescence_avoids_poisoned_pawn_at_depth_one(self):
        board = chess.Board("3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1")
        before = board.fen(), list(board.move_stack)
        baseline = alphabeta(board, 5, max_depth=1, enhanced=False)
        improved = alphabeta(board, 5, max_depth=1, enhanced=True)
        self.assertEqual(baseline["move"], "d1d5")
        self.assertNotEqual(improved["move"], "d1d5")
        self.assertGreater(improved["qnodes"], 0)
        self.assertEqual(before, (board.fen(), list(board.move_stack)))

    def test_shared_evaluation_rewards_pawn_structure_and_king_safety(self):
        supported = chess.Board("r2q2k1/8/8/8/8/8/5PPP/3Q1RK1 w - - 0 1")
        exposed = chess.Board("r2q2k1/8/8/8/8/6K1/5PPP/3Q1R2 w - - 0 1")
        gain = evaluate(supported, enhanced=True) - evaluate(supported, enhanced=False)
        loss = evaluate(exposed, enhanced=True) - evaluate(exposed, enhanced=False)
        self.assertGreater(gain, loss)
        connected = chess.Board("6k1/8/8/8/8/8/4PP2/6K1 w - - 0 1")
        doubled = chess.Board("6k1/8/8/8/8/4P3/4P3/6K1 w - - 0 1")
        self.assertGreater(evaluate(connected) - evaluate(connected, enhanced=False),
                           evaluate(doubled) - evaluate(doubled, enhanced=False))
        for board in (supported, exposed, chess.Board()):
            self.assertEqual(evaluate(board), -evaluate(board.mirror()))

    def test_guided_policy_avoids_hanging_queen_and_finds_mate(self):
        from chess_duel.engine import policy_move
        import random
        poison = chess.Board("3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1")
        before = poison.fen()
        move = policy_move(poison, list(poison.legal_moves), random.Random(7), random_rate=0)
        self.assertNotEqual(move.uci(), "d1d5")
        self.assertEqual(poison.fen(), before)
        mate = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        move = policy_move(mate, list(mate.legal_moves), random.Random(7), random_rate=0)
        mate.push(move)
        self.assertTrue(mate.is_checkmate())

    def test_variants_record_their_configuration(self):
        for enhanced in (False, True):
            for search in (alphabeta, mcts):
                result = search(chess.Board(), 0.02, enhanced=enhanced)
                self.assertEqual(result["variant"], "enhanced" if enhanced else "baseline")
                self.assertIn(chess.Move.from_uci(result["move"]), chess.Board().legal_moves)


class AppTests(unittest.TestCase):
    def test_moves_and_pgn_preserve_history(self):
        from chess_duel.app import build_board, board_data
        board = build_board({"moves": ["e2e4", "e7e5", "g1f3"]})
        data = board_data(board)
        self.assertEqual(data["turn"], "black")
        self.assertEqual(data["history"], ["e4", "e5", "Nf3"])
        self.assertIn("1. e4 e5 2. Nf3", data["pgn"])

    def test_rejects_illegal_and_invalid_positions(self):
        from chess_duel.app import build_board
        for payload in ({"moves": ["e2e5"]}, {"fen": "invalid"},
                        {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"},
                        {"moves": "e2e4"}):
            with self.assertRaises(ValueError):
                build_board(payload)

    def test_standard_special_moves(self):
        from chess_duel.app import build_board
        castle = build_board({"fen": "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
                              "moves": ["e1g1"]})
        self.assertEqual(castle.piece_at(chess.F1).symbol(), "R")
        ep = build_board({"moves": ["e2e4", "a7a6", "e4e5", "d7d5", "e5d6"]})
        self.assertIsNone(ep.piece_at(chess.D5))
        for promotion in "qrbn":
            promoted = build_board({"fen": "7k/P7/8/8/8/8/8/7K w - - 0 1",
                                    "moves": ["a7a8" + promotion]})
            self.assertEqual(promoted.piece_at(chess.A8).symbol().lower(), promotion)

    def test_benchmark_positions_and_paired_games(self):
        from benchmarks.experiments import load_positions, run_game
        fixtures = load_positions()
        self.assertEqual(len(fixtures), 12)
        for fixture in fixtures:
            if fixture.get("mate_in_one"):
                board = fixture["board"]
                self.assertTrue(any(board.gives_check(move) and
                                    self.is_mate_after(board, move)
                                    for move in board.legal_moves))
        game = run_game(fixtures[4], 0.01, "alphabeta", 7, 4)
        self.assertEqual(game["plies"], 4)
        self.assertEqual(game["termination"], "Ply cap (unfinished)")
        self.assertIn('[Result "*"]', game["pgn"])
        self.assertEqual(len(game["searches"]), 4)

    def test_material_certificate_checks_recapture_and_promotion(self):
        from benchmarks.experiments import certify_material
        board = chess.Board("3r2k1/8/8/3p4/8/8/8/3Q2K1 w - - 0 1")
        before = board.fen()
        certificate = certify_material({"name": "poison", "board": board})
        self.assertNotIn("d1d5", certificate["accepted_moves"])
        self.assertEqual(certificate["best_gain"], 0)
        self.assertEqual(board.fen(), before)
        promotion = certify_material({"name": "promotion", "board": chess.Board(
            "7k/P7/8/8/8/8/8/7K w - - 0 1")})
        self.assertEqual(promotion["accepted_moves"], ["a7a8q"])
        self.assertEqual(promotion["best_gain"], 800)
        capture = certify_material({"name": "capture", "board": chess.Board(
            "6k1/8/8/8/4q3/2N5/4P3/6K1 w - - 0 1")})
        self.assertEqual(capture["accepted_moves"], ["c3e4"])
        self.assertEqual(capture["best_gain"], 900)

    @staticmethod
    def is_mate_after(board, move):
        child = board.copy(stack=True)
        child.push(move)
        return child.is_checkmate()


class ReferenceTests(unittest.TestCase):
    def test_unfinished_games_are_not_counted_as_draws(self):
        import tempfile
        from unittest.mock import patch
        from benchmarks.analyze_results import analyze_followup_games
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "games.csv").write_text(
                "budget,result,alpha_score\n0.1,1-0,1\n0.1,1/2-1/2,0.5\n0.1,*,\n0.1,0-1,0\n")
            with patch("benchmarks.analyze_results.Path.write_text"):
                summary = analyze_followup_games(folder)[0]
            self.assertEqual(summary["draws"], 1)
            self.assertEqual(summary["unfinished"], 1)
            self.assertEqual(summary["score_bounds"], [.375, .625])
            self.assertEqual(summary["completed_score"], .5)

    def test_exhaustive_mate_and_defense_answers(self):
        from benchmarks.experiments import certify_tactic
        attack = {"name": "Unique mate", "objective": "force_mate", "mate_plies": 3,
                  "board": chess.Board("3k4/8/3K4/8/8/4Q3/8/6r1 w - - 0 1")}
        before = attack["board"].fen()
        answers = certify_tactic(attack)
        self.assertEqual(answers["accepted_moves"], ["e3e7"])
        self.assertEqual(attack["board"].fen(), before)
        attack["board"] = attack["board"].mirror()
        self.assertEqual(certify_tactic(attack)["accepted_moves"], ["e6e2"])
        defense = {"name": "Narrow defense", "objective": "avoid_mate", "mate_plies": 3,
                   "board": chess.Board("8/3r4/8/8/2Q5/6K1/8/6k1 b - - 0 1")}
        self.assertEqual(certify_tactic(defense)["accepted_moves"], ["d7d1", "d7g7"])

    def test_paired_interval_keeps_colors_together(self):
        from benchmarks.analyze_results import paired_interval
        rows = [{"position": str(i), "alpha_score": score}
                for i in range(4) for score in ("1", "0")]
        self.assertEqual(paired_interval(rows, repeats=100), [.5, .5])
        self.assertIsNone(paired_interval(rows[:4]))
        with self.assertRaises(ValueError):
            paired_interval(rows[:-1])

    def test_extended_corpus_certifies_every_label(self):
        from benchmarks.experiments import load_positions, certify_tactic
        fixtures = load_positions(Path(__file__).resolve().parents[1] / "fixtures/tactics.json")
        self.assertEqual(len(fixtures), 12)
        for fixture in fixtures:
            certificate = certify_tactic(fixture)
            self.assertTrue(certificate["accepted_moves"])
            self.assertLess(len(certificate["accepted_moves"]), certificate["legal_moves"])
            self.assertEqual(certificate["accepted_moves"], sorted(fixture["expected_moves"]))


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chess_duel.app import make_server
        cls.server = make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, path, value, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(self.url + path, json.dumps(value).encode(), headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def test_page_and_search_end_to_end(self):
        with urllib.request.urlopen(self.url, timeout=5) as response:
            self.assertIn(b"Chess Search Duel", response.read())
        for algorithm, variant in (("alphabeta", "enhanced"), ("mcts", "baseline")):
            result = self.post("/api/search", {"moves": ["e2e4"], "algorithm": algorithm,
                              "seconds": 0.02, "seed": 7, "id": algorithm, "variant": variant})
            board = chess.Board()
            board.push_uci("e2e4")
            self.assertIn(chess.Move.from_uci(result["move"]), board.legal_moves)

    def test_invalid_payload_and_foreign_origin(self):
        for payload in ({"algorithm": "unknown", "id": "x"},
                        {"algorithm": "mcts", "variant": "invalid", "id": "x"},
                        {"algorithm": "mcts", "seconds": float("nan"), "id": "x"},
                        {"algorithm": "mcts", "seconds": True, "id": "x"}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post("/api/search", payload)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post("/api/state", {}, origin="https://foreign.example")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_cancellation_releases_search_slot(self):
        results = []
        worker = threading.Thread(target=lambda: results.append(self.post(
            "/api/search", {"algorithm": "mcts", "seconds": 5, "id": "cancel-me"})))
        worker.start()
        import time
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.post("/api/cancel", {"id": "cancel-me"})["cancelled"]:
                break
            time.sleep(0.01)
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]["cancelled"])
        self.assertLess(results[0]["elapsed"], 2)


if __name__ == "__main__":
    unittest.main()
