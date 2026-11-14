"""tiny-chess-01 engine v4: piece-square tables, null move, LMR, killers and quiescence.

Board: 64-int list, a1=0, white positive. Tables are 448 signed bytes, offset by 128, base64.
"""

import json
import os
import sys
import urllib.request
from base64 import b64decode as bd

P, N, B, R, Q, K = 1, 2, 3, 4, 5, 6
V = (0, 100, 320, 330, 500, 900, 0)
MATE = 30000
LIMIT = 60000
KN = (17, 15, 10, 6, -6, -10, -15, -17)
KG = (9, 8, 7, 1, -1, -7, -8, -9)
DIAG = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))
ALL = DIAG + ORTH
FILES = "abcdefgh"
# pawn, knight, bishop, rook, queen, king middle, king end: a1 first, each value + 128
T = bd(
    "gICAgICAgICFiopsbIqKhYV7doCAdnuFgICAlJSAgICFhYqZmYqFhYqKlJ6elIqKsrKysrKysrKAgICAgICAgE5YYmJiYlhOWGyAhYWAbFhihYqPj4qFYmKAj5SUj4BiYoWPlJSPhWJigIqPj4qAYlhsgICAgGxYTlhiYmJiWE5sdnZ2dnZ2bHaFgICAgIV2doqKioqKinZ2gIqKioqAdnaFhYqKhYV2doCFioqFgHZ2gICAgICAdmx2dnZ2dnZsgICAhYWAgIB7gICAgICAe3uAgICAgIB7e4CAgICAgHt7gICAgICAe3uAgICAgIB7hYqKioqKioWAgICAgICAgGx2dnt7dnZsdoCFgICAgHZ2hYWFhYWAdoCAhYWFhYB7e4CFhYWFgHt2gIWFhYWAdnaAgICAgIB2bHZ2e3t2dmyUnoqAgIqelJSUgICAgJSUdmxsbGxsbHZsYmJYWGJibGJYWE5OWFhiYlhYTk5YWGJiWFhOTlhYYmJYWE5OWFhiTmJiYmJiYk5iYoCAgIBiYmJ2lJ6elHZiYnaeqKiedmJidp6oqJ52YmJ2lJ6elHZiYmx2gIB2bGJOWGJsbGJYTg=="
)
nodes = 0
KILL = [[None, None] for _ in range(64)]
HIST = [[0] * 64 for _ in range(64)]


class Cut(Exception):
    pass


def build_tables():
    global KT, KGT
    KT = [[] for _ in range(64)]
    KGT = [[] for _ in range(64)]
    for s in range(64):
        f, r = s % 8, s // 8
        for d in KN:
            t = s + d
            if 0 <= t < 64 and abs(t % 8 - f) <= 2 and abs(t // 8 - r) <= 2:
                KT[s].append(t)
        for d in KG:
            t = s + d
            if 0 <= t < 64 and abs(t % 8 - f) <= 1 and abs(t // 8 - r) <= 1:
                KGT[s].append(t)


build_tables()


def parse(fen):
    parts = fen.split()
    b = [0] * 64
    r, c = 7, 0
    for ch in parts[0]:
        if ch == "/":
            r -= 1
            c = 0
        elif ch.isdigit():
            c += int(ch)
        else:
            t = "pnbrqk".index(ch.lower()) + 1
            b[r * 8 + c] = t if ch.isupper() else -t
            c += 1
    side = 1 if parts[1] == "w" else -1
    cast = 0
    for i, ch in enumerate("KQkq"):
        if ch in parts[2]:
            cast |= 1 << i
    ep = -1 if parts[3] == "-" else FILES.index(parts[3][0]) + (int(parts[3][1]) - 1) * 8
    return b, side, cast, ep


def uci(m):
    f, t, pr = m
    s = FILES[f % 8] + str(f // 8 + 1) + FILES[t % 8] + str(t // 8 + 1)
    return s + ("nbrq"[pr - 2] if pr else "")


def from_uci(s):
    f = FILES.index(s[0]) + (int(s[1]) - 1) * 8
    t = FILES.index(s[2]) + (int(s[3]) - 1) * 8
    return (f, t, "nbrq".index(s[4]) + 2 if len(s) > 4 else 0)


def king_sq(b, side):
    return b.index(K * side)


def attacked(b, s, by):
    f, r = s % 8, s // 8
    pr = r - by
    if 0 <= pr < 8:
        for df in (-1, 1):
            pf = f + df
            if 0 <= pf < 8 and b[pr * 8 + pf] == P * by:
                return True
    for j in KT[s]:
        if b[j] == N * by:
            return True
    for j in KGT[s]:
        if b[j] == K * by:
            return True
    for df, dr in ALL:
        ff, rr = f + df, r + dr
        while 0 <= ff < 8 and 0 <= rr < 8:
            q = b[rr * 8 + ff]
            if q:
                if q * by > 0:
                    t = abs(q)
                    if t == Q or (t == R and df * dr == 0) or (t == B and df * dr != 0):
                        return True
                break
            ff += df
            rr += dr
    return False


def gen(b, side, cast, ep, caps=False):
    out = []
    for i in range(64):
        p = b[i]
        if p * side <= 0:
            continue
        t = abs(p)
        f, r = i % 8, i // 8
        if t == P:
            nr = r + side
            if 0 <= nr < 8:
                one = nr * 8 + f
                if b[one] == 0:
                    if nr in (0, 7):
                        out.append((i, one, 5))
                    elif not caps:
                        out.append((i, one, 0))
                        dbl = r + 2 * side
                        if r == (1 if side > 0 else 6) and b[dbl * 8 + f] == 0:
                            out.append((i, dbl * 8 + f, 0))
                for df in (-1, 1):
                    nf = f + df
                    if 0 <= nf < 8:
                        tgt = nr * 8 + nf
                        q = b[tgt]
                        if q * side < 0:
                            out.append((i, tgt, 5 if nr in (0, 7) else 0))
                        elif tgt == ep:
                            out.append((i, tgt, 0))
        elif t == N or t == K:
            for j in (KT[i] if t == N else KGT[i]):
                q = b[j]
                if q * side <= 0 and (q or not caps):
                    out.append((i, j, 0))
        else:
            dirs = DIAG if t == B else ORTH if t == R else ALL
            for df, dr in dirs:
                ff, rr = f + df, r + dr
                while 0 <= ff < 8 and 0 <= rr < 8:
                    j = rr * 8 + ff
                    q = b[j]
                    if q * side > 0:
                        break
                    if q * side < 0:
                        out.append((i, j, 0))
                        break
                    if not caps:
                        out.append((i, j, 0))
                    ff += df
                    rr += dr
    if not caps:
        if side > 0:
            if cast & 1 and b[5] == 0 and b[6] == 0 and not attacked(b, 4, -1) and not attacked(b, 5, -1):
                out.append((4, 6, 0))
            if cast & 2 and b[3] == 0 and b[2] == 0 and b[1] == 0 and not attacked(b, 4, -1) and not attacked(b, 3, -1):
                out.append((4, 2, 0))
        else:
            if cast & 4 and b[61] == 0 and b[62] == 0 and not attacked(b, 60, 1) and not attacked(b, 61, 1):
                out.append((60, 62, 0))
            if cast & 8 and b[59] == 0 and b[58] == 0 and b[57] == 0 and not attacked(b, 60, 1) and not attacked(b, 59, 1):
                out.append((60, 58, 0))
    return out


def child(b, m, side, cast, ep):
    f, t, pr = m
    p = b[f]
    nb = b[:]
    cap = nb[t]
    if abs(p) == P and t == ep and cap == 0 and f % 8 != t % 8:
        nb[t - 8 * side] = 0
        cap = P * -side
    nb[t] = pr * side if pr else p
    nb[f] = 0
    nc = cast
    if abs(p) == K:
        nc &= 0xC if side > 0 else 0x3
    if abs(cap) == R:
        nc &= 0xF & ~(1 if t == 7 else 2 if t == 0 else 4 if t == 63 else 8 if t == 56 else 0)
    ne = -1
    if abs(p) == P and abs(t - f) == 16:
        ne = (f + t) // 2
    if abs(p) == K and abs(t - f) == 2:
        if t > f:
            nb[f + 1] = nb[f + 3]
            nb[f + 3] = 0
        else:
            nb[f - 1] = nb[f - 4]
            nb[f - 4] = 0
    return nb, -side, nc, ne


def evaluate(b, side):
    sc = 0
    mat = 0
    bishops = [0, 0]
    for i in range(64):
        p = b[i]
        if p:
            t = abs(p)
            if t == B:
                bishops[0 if p > 0 else 1] += 1
            if t != P and t != K:
                mat += V[t]
    eg = mat < 1500
    for i in range(64):
        p = b[i]
        if p:
            t = abs(p)
            sgn = 1 if p > 0 else -1
            idx = i if p > 0 else (7 - i // 8) * 8 + i % 8
            tt = (6 if eg else 5) if t == K else t - 1
            sc += sgn * (V[t] + T[tt * 64 + idx] - 128)
    if bishops[0] > 1:
        sc += 20
    if bishops[1] > 1:
        sc -= 20
    return sc * side + 4


def order(b, moves, ply):
    killers = KILL[ply]

    def key(m):
        victim = b[m[1]]
        score = 0
        if victim:
            score = 10 * V[abs(victim)] - V[abs(b[m[0]])]
        if m[2]:
            score += 800
        if m == killers[0]:
            score += 700
        elif m == killers[1]:
            score += 600
        elif not victim:
            score += HIST[m[0]][m[1]]
        return -score

    moves.sort(key=key)
    return moves


def qs(b, side, cast, ep, alpha, beta, ply):
    global nodes
    nodes += 1
    if nodes > LIMIT:
        raise Cut
    if ply > 10:
        return evaluate(b, side)
    check = attacked(b, king_sq(b, side), -side)
    if not check:
        stand = evaluate(b, side)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
    if check and ply > 4:
        return evaluate(b, side)
    moves = order(b, gen(b, side, cast, ep, not check), ply)
    for m in moves:
        victim = b[m[1]]
        if not check and not victim and not m[2]:
            continue
        nb, ns, nc, ne = child(b, m, side, cast, ep)
        if attacked(nb, king_sq(nb, side), -side):
            continue
        v = -qs(nb, ns, nc, ne, -beta, -alpha, ply + 1)
        if v >= beta:
            return beta
        if v > alpha:
            alpha = v
    return alpha


def ab(b, side, cast, ep, depth, alpha, beta, ply, nulled=False):
    global nodes
    nodes += 1
    if nodes > LIMIT:
        raise Cut
    if ply > 40:
        return evaluate(b, side)
    if depth <= 0:
        return qs(b, side, cast, ep, alpha, beta, ply)
    in_check = attacked(b, king_sq(b, side), -side)
    if not in_check and not nulled and depth >= 3 and ep < 0:
        if any(abs(p) not in (P, K) and p * side > 0 for p in b):
            v = -ab(b, -side, cast, -1, depth - 3, -beta, -beta + 1, ply + 1, True)
            if v >= beta:
                return beta
    moves = order(b, gen(b, side, cast, ep), ply)
    static = evaluate(b, side) if depth == 1 and not in_check else None
    legal = 0
    best = -MATE
    index = 0
    searched = 0
    for m in moves:
        nb, ns, nc, ne = child(b, m, side, cast, ep)
        if attacked(nb, king_sq(nb, side), -side):
            continue
        legal += 1
        index += 1
        if static is not None and legal > 1 and not b[m[1]] and not m[2] and static + 180 <= alpha:
            continue
        searched += 1
        if index > 3 and depth >= 3 and not in_check and not b[m[1]] and not m[2]:
            red = 1 + (index > 8) + (depth > 6)
            v = -ab(nb, ns, nc, ne, depth - 1 - red, -alpha - 1, -alpha, ply + 1, False)
            if v > alpha:
                v = -ab(nb, ns, nc, ne, depth - 1, -beta, -alpha, ply + 1, False)
        else:
            v = -ab(nb, ns, nc, ne, depth - 1, -beta, -alpha, ply + 1, False)
        if v > best:
            best = v
        if v > alpha:
            alpha = v
        if alpha >= beta:
            if not b[m[1]] and not m[2]:
                if KILL[ply][0] != m:
                    KILL[ply][1] = KILL[ply][0]
                    KILL[ply][0] = m
                HIST[m[0]][m[1]] += depth * depth
            break
    if legal == 0:
        return -MATE + ply if in_check else 0
    if searched == 0:
        return static if static is not None else best
    return best


def pick(fen, legal):
    global nodes
    nodes = 0
    for row in HIST:
        for i in range(64):
            row[i] = 0
    for k in KILL:
        k[0] = k[1] = None
    b, side, cast, ep = parse(fen)
    roots = [from_uci(u) for u in legal]
    if not roots:
        return legal[0]
    best = roots[0]
    for d in range(1, 8):
        try:
            alpha = -MATE
            local = None
            for m in order(b, list(roots), 0):
                nb, ns, nc, ne = child(b, m, side, cast, ep)
                if attacked(nb, king_sq(nb, side), -side):
                    continue
                v = -ab(nb, ns, nc, ne, d - 1, -MATE, -alpha, 0)
                if v > alpha or local is None:
                    alpha = v
                    local = m
            if local:
                best = local
                roots.remove(local)
                roots.insert(0, local)
        except Cut:
            break
    out = uci(best)
    return out if out in legal else legal[0]


def post(url, path, body):
    req = urllib.request.Request(
        url + path,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        return json.load(res)


def main():
    url = os.environ.get("MAKEFUN_ENV_URL")
    if not url:
        sys.exit("MAKEFUN_ENV_URL is not set")
    while True:
        g = post(url, "/game", {})
        if g["status"] == "done":
            break
        while g["status"] == "your_move":
            g = post(url, "/move", {"game": g["game"], "move": pick(g["fen"], g["legal_moves"])})
        print(f"game {g['game']}: {g['outcome']} by {g['reason']}", file=sys.stderr)
    print(f"done: {g.get('wins')} won, {g.get('draws')} drawn, {g.get('losses')} lost", file=sys.stderr)


if __name__ == "__main__":
    main()
