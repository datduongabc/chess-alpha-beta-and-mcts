"""Own alpha-beta and UCT searches; python-chess owns standard chess rules.

Evaluation: White-relative centipawns. MCTS backup: root-relative utility.
All games automatically claim available threefold/fifty-move draws.
"""
import math
import random
import time
from dataclasses import dataclass, field

import chess

MATE = 100000
VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
          chess.ROOK: 500, chess.QUEEN: 900}


def evaluate(board, *, enhanced=True):
    """White-relative centipawns; both engines share the selected evaluator."""
    total = 0
    endgame = sum(len(board.pieces(kind, color)) * value
                  for kind, value in VALUES.items() if kind != chess.PAWN
                  for color in chess.COLORS) <= 2600
    for square, piece in board.piece_map().items():
        oriented = square if piece.color else chess.square_mirror(square)
        rank, file = chess.square_rank(oriented), chess.square_file(oriented)
        center = 7 - abs(2 * file - 7) / 2 - abs(2 * rank - 7) / 2
        bonus = 0
        if piece.piece_type == chess.PAWN:
            bonus = 8 * rank + 3 * center
        elif piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            bonus = 10 * center
        elif piece.piece_type == chess.KING:
            bonus = (10 if endgame else -8) * center
        total += (1 if piece.color else -1) * (VALUES.get(piece.piece_type, 0) + bonus)
    if enhanced:
        for color in chess.COLORS:
            sign = 1 if color else -1
            pawns = board.pieces_mask(chess.PAWN, color)
            enemy_pawns = board.pieces_mask(chess.PAWN, not color)
            files = [(pawns & mask).bit_count() for mask in chess.BB_FILES]
            bonus = 30 if len(board.pieces(chess.BISHOP, color)) >= 2 else 0
            bonus -= 12 * sum(max(0, count - 1) for count in files)
            for square in chess.scan_forward(pawns):
                file = chess.square_file(square)
                rank = chess.square_rank(square if color else chess.square_mirror(square))
                neighbors = range(max(0, file - 1), min(8, file + 2))
                if not any(files[f] for f in neighbors if f != file):
                    bonus -= 12
                enemies = enemy_pawns & sum(chess.BB_FILES[f] for f in neighbors)
                if not any((chess.square_rank(enemy) > chess.square_rank(square) if color else
                            chess.square_rank(enemy) < chess.square_rank(square))
                           for enemy in chess.scan_forward(enemies)):
                    bonus += 15 + 4 * rank * rank
            for kind, weight in ((chess.KNIGHT, 4), (chess.BISHOP, 4),
                                 (chess.ROOK, 2), (chess.QUEEN, 1)):
                for square in board.pieces(kind, color):
                    mobility = board.attacks_mask(square) & ~board.occupied_co[color]
                    bonus += weight * mobility.bit_count()
                    if kind == chess.ROOK:
                        mask = chess.BB_FILES[chess.square_file(square)]
                        if not pawns & mask:
                            bonus += 10 if enemy_pawns & mask else 18
            if not endgame:
                king = board.king(color)
                rank, file = chess.square_rank(king), chess.square_file(king)
                shield_rank = rank + (1 if color else -1)
                if 0 <= shield_rank < 8:
                    shield = sum(bool(pawns & chess.BB_SQUARES[chess.square(f, shield_rank)])
                                 for f in range(max(0, file - 1), min(8, file + 2)))
                    bonus += 12 * shield
                if file in (1, 2, 6, 7) and rank == (0 if color else 7):
                    bonus += 30
                bonus -= 8 * sum(board.is_attacked_by(not color, sq)
                                 for sq in board.attacks(king))
            total += sign * bonus
    return round(total)


class SearchStopped(Exception):
    pass


def check_stop(deadline, cancel):
    if time.perf_counter() >= deadline or (cancel is not None and cancel.is_set()):
        raise SearchStopped


def ordered_moves(board, preferred=None):
    def priority(move):
        victim = board.piece_at(move.to_square)
        attacker = board.piece_at(move.from_square)
        capture = (VALUES.get(victim.piece_type, 0) if victim else
                   100 if board.is_en_passant(move) else 0)
        return (move != preferred, -(10000 + capture * 10 -
                VALUES.get(attacker.piece_type, 0)) if capture else 0,
                -VALUES.get(move.promotion, 0), move.uci())
    return sorted(board.legal_moves, key=priority)


def quiescence(board, alpha, beta, *, ply=0, remaining=6,
               deadline=math.inf, cancel=None, stats=None, evaluation_enhanced=True):
    """Resolve captures/promotions; search every evasion when in check."""
    check_stop(deadline, cancel)
    if stats is None:
        stats = {"evaluations": 0, "cutoffs": 0}
    stats["qnodes"] = stats.get("qnodes", 0) + 1
    outcome = board.outcome(claim_draw=True)
    if outcome:
        return (-MATE + ply if outcome.winner is not None else 0), []
    stats["evaluations"] += 1
    stand_pat = evaluate(board, enhanced=evaluation_enhanced) * (1 if board.turn else -1)
    if remaining == 0:
        return stand_pat, []
    checked = board.is_check()
    best, line = (-math.inf if checked else stand_pat), []
    if not checked:
        if stand_pat >= beta:
            return stand_pat, []
        alpha = max(alpha, stand_pat)
    for move in ordered_moves(board):
        if not checked and not (board.is_capture(move) or move.promotion):
            continue
        board.push(move)
        try:
            score, continuation = quiescence(board, -beta, -alpha, ply=ply + 1,
                                            remaining=remaining - 1, deadline=deadline,
                                            cancel=cancel, stats=stats,
                                            evaluation_enhanced=evaluation_enhanced)
            score = -score
        finally:
            board.pop()
        if score > best:
            best, line = score, [move.uci(), *continuation]
        alpha = max(alpha, score)
        if alpha >= beta:
            stats["cutoffs"] += 1
            break
    return best, line


def negamax(board, depth, alpha=-math.inf, beta=math.inf, *, ply=0,
            deadline=math.inf, cancel=None, stats=None, preferred=None, enhanced=True,
            evaluation_enhanced=None, use_quiescence=None):
    """Return side-to-move score and principal variation; always undo pushes."""
    check_stop(deadline, cancel)
    evaluation_enhanced = enhanced if evaluation_enhanced is None else evaluation_enhanced
    use_quiescence = enhanced if use_quiescence is None else use_quiescence
    if stats is None:
        stats = {"nodes": 0, "evaluations": 0, "cutoffs": 0}
    stats["nodes"] += 1
    outcome = board.outcome(claim_draw=True)
    if outcome:
        return (-MATE + ply if outcome.winner is not None else 0), []
    if depth == 0:
        if use_quiescence:
            return quiescence(board, alpha, beta, ply=ply, deadline=deadline,
                              cancel=cancel, stats=stats, evaluation_enhanced=evaluation_enhanced)
        stats["evaluations"] += 1
        return evaluate(board, enhanced=evaluation_enhanced) * (1 if board.turn else -1), []
    best, line = -math.inf, []
    for move in ordered_moves(board, preferred):
        board.push(move)
        try:
            score, child_line = negamax(board, depth - 1, -beta, -alpha,
                                       ply=ply + 1, deadline=deadline,
                                       cancel=cancel, stats=stats, enhanced=enhanced,
                                       evaluation_enhanced=evaluation_enhanced,
                                       use_quiescence=use_quiescence)
            score = -score
        finally:
            board.pop()
        if score > best:
            best, line = score, [move.uci(), *child_line]
        alpha = max(alpha, score)
        if alpha >= beta:
            stats["cutoffs"] += 1
            break
    return best, line


def search_setup(board, seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Thinking time must be finite and nonnegative.")
    if not board.is_valid():
        raise ValueError("Invalid chess position.")
    start = time.perf_counter()
    copy = board.copy(stack=True)
    moves = sorted(copy.legal_moves, key=lambda m: m.uci())
    terminal = copy.outcome(claim_draw=True)
    result = {"move": moves[0].uci() if moves and not terminal else None,
              "budget": seconds, "elapsed": 0.0,
              "terminal": terminal.result() if terminal else None}
    return start, start + seconds, copy, result


def alphabeta(board, seconds, *, cancel=None, max_depth=64, enhanced=True,
              evaluation_enhanced=None, use_quiescence=None):
    start, deadline, position, result = search_setup(board, seconds)
    evaluation_enhanced = enhanced if evaluation_enhanced is None else evaluation_enhanced
    use_quiescence = enhanced if use_quiescence is None else use_quiescence
    result.update(algorithm="Alpha-beta", depth=0, score=None, pv=[],
                  nodes=0, evaluations=0, cutoffs=0, qnodes=0,
                  variant="enhanced" if enhanced else "baseline",
                  evaluation_enhanced=evaluation_enhanced, use_quiescence=use_quiescence)
    if result["move"] is not None:
        stats = {"nodes": 0, "evaluations": 0, "cutoffs": 0, "qnodes": 0}
        try:
            for depth in range(1, max_depth + 1):
                score, line = negamax(position, depth, deadline=deadline,
                                      cancel=cancel, stats=stats,
                                      preferred=chess.Move.from_uci(result["move"]),
                                      enhanced=enhanced, evaluation_enhanced=evaluation_enhanced,
                                      use_quiescence=use_quiescence)
                result.update(move=line[0], score=score, pv=line, depth=depth)
                if abs(score) >= MATE - depth:
                    break
        except SearchStopped:
            pass
        result.update(stats)
    result["elapsed"] = time.perf_counter() - start
    return result


@dataclass
class Node:
    turn: bool
    untried: list
    move: str | None = None
    visits: int = 0
    value: float = 0.0
    children: list = field(default_factory=list)


def select_child(node, root_player, exploration):
    """The opponent MINIMIZES root utility, but still explores."""
    sign = 1 if node.turn == root_player else -1
    def uct(child):
        if child.visits == 0:
            return math.inf
        return (sign * child.value / child.visits + exploration *
                math.sqrt(math.log(max(1, node.visits)) / child.visits))
    return max(node.children, key=uct)


def policy_move(board, moves, rng, *, random_rate=0.15, deadline=math.inf, cancel=None):
    """Cheap tactical rollout/expansion policy, without another search engine."""
    if rng.random() < random_rate:
        return rng.choice(moves)
    best, choices = -math.inf, []
    for move in moves:
        check_stop(deadline, cancel)
        attacker = board.piece_at(move.from_square)
        victim = board.piece_at(move.to_square)
        capture = VALUES.get(victim.piece_type, 0) if victim else (
            100 if board.is_en_passant(move) else 0)
        score = capture + (VALUES.get(move.promotion, 0) - 100 if move.promotion else 0)
        if board.is_attacked_by(not board.turn, move.to_square):
            score -= VALUES.get(attacker.piece_type, 0) * (1 if capture else 0.5)
        if board.is_castling(move):
            score += 50
        if attacker.piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP):
            file, rank = chess.square_file(move.to_square), chess.square_rank(move.to_square)
            score += 5 * (7 - abs(2 * file - 7) / 2 - abs(2 * rank - 7) / 2)
        if board.gives_check(move):
            board.push(move)
            try:
                score += MATE if board.is_checkmate() else 25
            finally:
                board.pop()
        if score > best:
            best, choices = score, [move]
        elif score == best:
            choices.append(move)
    return rng.choice(choices)


def screen_root_moves(board, *, deadline=math.inf, cancel=None):
    """Exact mate-in-one checks, including the opponent's immediate reply.

    This bounded guard cannot prove safety beyond one reply. Apply its filter
    only after the whole scan completes; always undo moves on interruption.
    """
    moves = sorted(board.legal_moves, key=lambda move: move.uci())
    for move in moves:
        check_stop(deadline, cancel)
        board.push(move)
        try:
            if board.is_checkmate():
                return [move], move, 0
        finally:
            board.pop()
    safe = []
    for move in moves:
        check_stop(deadline, cancel)
        board.push(move)
        loses = False
        try:
            if not board.outcome(claim_draw=True):
                for reply in list(board.legal_moves):
                    check_stop(deadline, cancel)
                    if not board.gives_check(reply):
                        continue
                    board.push(reply)
                    try:
                        loses = board.is_checkmate()
                    finally:
                        board.pop()
                    if loses:
                        break
        finally:
            board.pop()
        if not loses:
            safe.append(move)
    return safe or moves, None, len(moves) - len(safe)


def mcts(board, seconds, *, seed=0, cancel=None, iterations=None,
         rollout_limit=None, exploration=math.sqrt(2), enhanced=True,
         evaluation_enhanced=None, guided=None, tactical_guard=None):
    evaluation_enhanced = enhanced if evaluation_enhanced is None else evaluation_enhanced
    guided = enhanced if guided is None else guided
    tactical_guard = enhanced if tactical_guard is None else tactical_guard
    if rollout_limit is None:
        rollout_limit = 12 if enhanced else 40
    start, deadline, position, result = search_setup(board, seconds)
    result.update(algorithm="MCTS", simulations=0, rollout_plies=0,
                  expanded_nodes=0, root_moves=[], seed=seed,
                  rollout_limit=rollout_limit, exploration=exploration,
                  variant="enhanced" if enhanced else "baseline",
                  rollout_policy="guided (15% random)" if guided else "random",
                  evaluation_enhanced=evaluation_enhanced, tactical_guard=tactical_guard,
                  guard_complete=False, rejected_immediate_losses=0, tactical_proof=None)
    if result["move"] is None:
        result["elapsed"] = time.perf_counter() - start
        return result
    rng = random.Random(seed)
    root_player = position.turn
    root = Node(position.turn, sorted(position.legal_moves, key=lambda m: m.uci()))
    try:
        if tactical_guard:
            moves, mate, rejected = screen_root_moves(position, deadline=deadline, cancel=cancel)
            root.untried = moves
            result.update(guard_complete=True, rejected_immediate_losses=rejected,
                          move=moves[0].uci())
            if mate:
                result.update(move=mate.uci(), tactical_proof="mate in one",
                              elapsed=time.perf_counter() - start)
                return result
        while iterations is None or root.visits < iterations:
            check_stop(deadline, cancel)
            state = position.copy(stack=True)
            node, path = root, [root]
            # Selection and expansion: each legal action appears once.
            while True:
                check_stop(deadline, cancel)
                outcome = state.outcome(claim_draw=True)
                if outcome:
                    break
                if node.untried:
                    if guided:
                        move = policy_move(state, node.untried, rng, random_rate=0,
                                           deadline=deadline, cancel=cancel)
                        node.untried.remove(move)
                    else:
                        move = node.untried.pop(rng.randrange(len(node.untried)))
                    state.push(move)
                    child = Node(state.turn, sorted(state.legal_moves,
                                 key=lambda m: m.uci()), move.uci())
                    node.children.append(child)
                    result["expanded_nodes"] += 1
                    node = child
                    path.append(node)
                    break
                node = select_child(node, root_player, exploration)
                state.push_uci(node.move)
                path.append(node)
            # Simulation: terminal result or a bounded heuristic cutoff.
            for _ in range(rollout_limit):
                check_stop(deadline, cancel)
                outcome = state.outcome(claim_draw=True)
                if outcome:
                    break
                moves = list(state.legal_moves)
                move = (policy_move(state, moves, rng, deadline=deadline, cancel=cancel)
                        if guided else rng.choice(moves))
                state.push(move)
                result["rollout_plies"] += 1
            outcome = state.outcome(claim_draw=True)
            if outcome:
                reward = 0.0 if outcome.winner is None else (
                    1.0 if outcome.winner == root_player else -1.0)
            else:
                reward = math.tanh(evaluate(state, enhanced=evaluation_enhanced) *
                                   (1 if root_player else -1) / 400)
            # Backup stays root-relative at every node.
            for visited in path:
                visited.visits += 1
                visited.value += reward
    except SearchStopped:
        pass
    result["simulations"] = root.visits
    completed = [child for child in root.children if child.visits]
    if completed:
        completed.sort(key=lambda child: (-child.visits,
                       -child.value / child.visits, child.move))
        result["move"] = completed[0].move
        result["root_moves"] = [
            {"move": child.move, "visits": child.visits,
             "value": child.value / child.visits} for child in completed]
    result["elapsed"] = time.perf_counter() - start
    return result


SEARCHES = {"alphabeta": alphabeta, "mcts": mcts}
