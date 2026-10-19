"""Local browser GUI. Start: python -m chess_duel.app, then http://127.0.0.1:8765."""
import argparse
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import chess
import chess.pgn

from chess_duel.engine import SEARCHES


def build_board(payload):
    fen = payload.get("fen", chess.STARTING_FEN)
    moves = payload.get("moves", [])
    if not isinstance(fen, str) or len(fen) > 160:
        raise ValueError("Provide a valid FEN position.")
    if not isinstance(moves, list) or len(moves) > 1024:
        raise ValueError("Move history must be a list of at most 1024 UCI moves.")
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("FEN does not describe a valid chess position.")
    for text in moves:
        if not isinstance(text, str) or len(text) not in (4, 5):
            raise ValueError("Invalid UCI move.")
        move = chess.Move.from_uci(text)
        if board.outcome(claim_draw=True) or move not in board.legal_moves:
            raise ValueError(f"Illegal move: {text}")
        board.push(move)
    return board


def board_data(board):
    replay = board.root()
    history = []
    numbered = []
    for move in board.move_stack:
        san = replay.san(move)
        history.append(san)
        prefix = f"{replay.fullmove_number}. " if replay.turn else (f"{replay.fullmove_number}... " if not numbered else "")
        numbered.append(prefix + san)
        replay.push(move)
    outcome = board.outcome(claim_draw=True)
    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = "Chess Search Duel"
    game.headers["Site"] = "Local"
    game.headers["White"] = "White player"
    game.headers["Black"] = "Black player"
    if outcome:
        game.headers["Result"] = outcome.result()
    last = board.peek().uci() if board.move_stack else None
    return {"fen": board.fen(), "turn": "white" if board.turn else "black",
            "pieces": {chess.square_name(sq): piece.symbol()
                       for sq, piece in board.piece_map().items()},
            "legal": [] if outcome else [move.uci() for move in board.legal_moves],
            "history_text": " ".join(numbered), "history": history, "last": last, "check": board.is_check(),
            "result": outcome.result() if outcome else None,
            "termination": outcome.termination.name.replace("_", " ").title() if outcome else None,
            "pgn": str(game)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value, status=200):
        data = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def local_request(self):
        host = self.headers.get("Host", "")
        parsed = urlsplit("http://" + host)
        if parsed.hostname not in ("127.0.0.1", "localhost"):
            self.reply({"error": "Use the local app address."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            self.reply({"error": "Cross-origin requests are not allowed."}, 403)
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        if self.path not in ("/", "/index.html"):
            self.reply({"error": "Not found"}, 404)
            return
        data = Path(__file__).with_name("index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Send application/json.")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError("Request body must be 1–65536 bytes.")
            self.connection.settimeout(10)
            body = self.rfile.read(size)
            if not self.local_request():
                return
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Request must be a JSON object.")
            if self.path == "/api/cancel":
                with self.server.events_lock:
                    event = self.server.events.get(str(payload.get("id", "")))
                    if event:
                        event.set()
                self.reply({"cancelled": event is not None})
                return
            if self.path not in ("/api/state", "/api/search"):
                self.reply({"error": "Not found"}, 404)
                return
            board = build_board(payload)
            if self.path == "/api/state":
                self.reply(board_data(board))
                return
            algorithm = payload.get("algorithm")
            variant = payload.get("variant", "enhanced")
            if variant not in ("enhanced", "baseline"):
                raise ValueError("Choose enhanced or baseline variant.")
            seconds, seed = payload.get("seconds", 0.5), payload.get("seed", 0)
            request_id = payload.get("id", "")
            if not isinstance(algorithm, str) or algorithm not in SEARCHES:
                raise ValueError("Choose alphabeta or mcts.")
            if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                    or not 0.01 <= seconds <= 5):
                raise ValueError("Thinking time must be between 0.01 and 5 seconds.")
            if type(seed) is not int or not 0 <= seed <= 2147483647:
                raise ValueError("Seed must be an integer from 0 to 2147483647.")
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
                raise ValueError("Provide a search request id.")
            if not self.server.search_slot.acquire(blocking=False):
                self.reply({"error": "Another search is finishing. Try again shortly."}, 409)
                return
            event = threading.Event()
            with self.server.events_lock:
                self.server.events[request_id] = event
            try:
                kwargs = {"cancel": event, "enhanced": variant == "enhanced"}
                if algorithm == "mcts":
                    kwargs["seed"] = seed
                result = SEARCHES[algorithm](board, seconds, **kwargs)
                if result["move"]:
                    result["san"] = board.san(chess.Move.from_uci(result["move"]))
                if algorithm == "alphabeta":
                    replay, san_line = board.copy(stack=True), []
                    for text in result["pv"]:
                        move = chess.Move.from_uci(text)
                        san_line.append(replay.san(move))
                        replay.push(move)
                    result["pv_san"] = san_line
                else:
                    for row in result["root_moves"]:
                        row["san"] = board.san(chess.Move.from_uci(row["move"]))
                result["cancelled"] = event.is_set()
                self.reply(result)
            finally:
                with self.server.events_lock:
                    self.server.events.pop(request_id, None)
                self.server.search_slot.release()
        except (ValueError, TypeError, OverflowError, TimeoutError) as error:
            self.reply({"error": str(error)}, 400)


def make_server(port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.events, server.events_lock = {}, threading.Lock()
    server.search_slot = threading.Semaphore(1)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with make_server(args.port) as server:
        print(f"Chess Search Duel: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
