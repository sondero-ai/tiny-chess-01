"""tiny-chess-01 engine (development source; shipped packed into main.py).

Board: 64-int list, a1=0, white pieces positive (1 P, 2 N, 3 B, 4 R, 5 Q, 6 K), black negative.
Search: iterative deepening alpha-beta with quiescence, fixed node budget, never a clock.
"""

import json
import os
import sys
import urllib.request

P, N, B, R, Q, K = 1, 2, 3, 4, 5, 6
V = (0, 100, 320, 330, 500, 900, 0)
MATE = 30000
LIMIT = 120000
KN = (17, 15, 10, 6, -6, -10, -15, -17)
KG = (9, 8, 7, 1, -1, -7, -8, -9)
DIAG = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))
ALL = DIAG + ORTH
FILES = "abcdefgh"

nodes = 0


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
                            if nr in (0, 7):
                                out.append((i, tgt, 5))
                            else:
                                out.append((i, tgt, 0))
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
            if cast & 1 and b[5] == 0 and b[6] == 0 and b[4] == K and not attacked(b, 4, -1) and not attacked(b, 5, -1):
                out.append((4, 6, 0))
            if cast & 2 and b[3] == 0 and b[2] == 0 and b[1] == 0 and b[4] == K and not attacked(b, 4, -1) and not attacked(b, 3, -1):
                out.append((4, 2, 0))
        else:
            if cast & 4 and b[61] == 0 and b[62] == 0 and b[60] == -K and not attacked(b, 60, 1) and not attacked(b, 61, 1):
                out.append((60, 62, 0))
            if cast & 8 and b[59] == 0 and b[58] == 0 and b[57] == 0 and b[60] == -K and not attacked(b, 60, 1) and not attacked(b, 59, 1):
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
    return nb, -side, nc, ne, cap


def piece_sq(t, i, eg):
    f, r = i % 8, i // 8
    c = abs(f - 3.5) + abs(r - 3.5)
    if t == P:
        return r * 9 + (0, 0, 5, 10, 10, 5, 0, 0)[f]
    if t == N:
        return int(34 - 8 * c)
    if t == B:
        return int(24 - 5 * c)
    if t == R:
        return (r - 3) * 2 + (6 if r == 6 else 0)
    if t == Q:
        return int(12 - 3 * c)
    if eg:
        return int(24 - 6 * c)
    return int(26 - 10 * c) if r > 0 else 10


def evaluate(b, side):
    sc = 0
    mat = 0
    bishops = [0, 0]
    counts = [0, 0]
    pawns = [[0] * 8, [0] * 8]
    for i in range(64):
        p = b[i]
        if not p:
            continue
        t = abs(p)
        sgn = 1 if p > 0 else -1
        if t != P and t != K:
            mat += V[t]
        if t == B:
            bishops[0 if p > 0 else 1] += 1
        if t == P:
            pawns[0 if p > 0 else 1][i % 8] += 1
        counts[0 if p > 0 else 1] += 1
    eg = mat < 1600
    for i in range(64):
        p = b[i]
        if p:
            t = abs(p)
            sgn = 1 if p > 0 else -1
            sqi = i if p > 0 else (7 - i // 8) * 8 + i % 8
            sc += sgn * (V[t] + piece_sq(t, sqi, eg))
    if bishops[0] > 1:
        sc += 24
    if bishops[1] > 1:
        sc -= 24
    for col in (0, 1):
        sgn = 1 if col == 0 else -1
        for f in range(8):
            n = pawns[col][f]
            if n > 1:
                sc -= sgn * 14 * (n - 1)
            if n and not (f and pawns[col][f - 1]) and not (f < 7 and pawns[col][f + 1]):
                sc -= sgn * 12
    return sc * side + 4


def order(b, moves):
    def key(m):
        t = m[1]
        victim = b[t]
        score = 0
        if victim:
            score = 10 * V[abs(victim)] - V[abs(b[m[0]])]
        if m[2]:
            score += 800
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
    moves = order(b, gen(b, side, cast, ep, not check))
    for m in moves:
        victim = b[m[1]]
        if not check and not victim and not m[2]:
            continue
        if not check and victim and evaluate(b, side) + V[abs(victim)] + 150 < alpha:
            continue
        nb, ns, nc, ne, cap = child(b, m, side, cast, ep)
        if attacked(nb, king_sq(nb, side), -side):
            continue
        v = -qs(nb, ns, nc, ne, -beta, -alpha, ply + 1)
        if v >= beta:
            return beta
        if v > alpha:
            alpha = v
    return alpha


def ab(b, side, cast, ep, depth, alpha, beta, ply):
    global nodes
    nodes += 1
    if nodes > LIMIT:
        raise Cut
    if ply > 40:
        return evaluate(b, side)
    if depth <= 0:
        return qs(b, side, cast, ep, alpha, beta, ply)
    moves = order(b, gen(b, side, cast, ep))
    legal = 0
    best = -MATE
    for m in moves:
        nb, ns, nc, ne, cap = child(b, m, side, cast, ep)
        if attacked(nb, king_sq(nb, side), -side):
            continue
        legal += 1
        v = -ab(nb, ns, nc, ne, depth - 1, -beta, -alpha, ply + 1)
        if v > best:
            best = v
        if v > alpha:
            alpha = v
        if alpha >= beta:
            break
    if legal == 0:
        return -MATE + ply if attacked(b, king_sq(b, side), -side) else 0
    return best


def pick(fen, legal):
    global nodes
    nodes = 0
    b, side, cast, ep = parse(fen)
    roots = [from_uci(u) for u in legal]
    if not roots:
        return legal[0]
    best = roots[0]
    for d in range(1, 6):
        try:
            alpha = -MATE
            local = None
            for m in order(b, list(roots)):
                nb, ns, nc, ne, cap = child(b, m, side, cast, ep)
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
    return uci(best) if uci(best) in legal else legal[0]


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
