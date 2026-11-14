# tiny-chess-01 entry

A 4 KB Python chess engine for the tiny-chess-01 bounty. `main.py` is the whole
engine: legal move generation, iterative-deepening alpha-beta, quiescence on
captures, null-move pruning, late-move reductions, killer and history ordering,
and a piece-square evaluation read from 448 packed bytes.

It plays the house gauntlet through the env at `MAKEFUN_ENV_URL`:

    POST /game {}                        the game in play
    POST /move {"game": n, "move": uci}  your move, the house answers

Search stops on a fixed node budget, never a clock, so a replay plays the same
moves. Python 3.13 standard library only; at run time it reads, imports or
execs no other file in this repository.

`main.py` is packed by `makefun compress` from `engine_src.py`. The readable
source travels with the transcripts and is not part of the commit.

MIT licence, see LICENSE.
