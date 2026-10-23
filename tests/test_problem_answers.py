"""Independent verification of EVERY answer in data/problems.yaml.

A wrong "correct answer" is the worst bug this feature can have, so each check below recomputes the answer by a
route that differs from the worked solution: brute-force enumeration, exact linear algebra, NumPy, high-precision
numerics (mpmath), Monte Carlo with a fixed seed, or a numerical solution of an integral equation. A problem with
no check here fails `test_every_problem_has_a_check`, so new problems cannot skip verification.
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import mpmath
import numpy as np
import pytest
import sympy

from math_engine.convert import to_sympy
from math_engine.validate import validate_expression
from services.problem_bank import load_bank

BANK = load_bank(Path(__file__).resolve().parent.parent / "data" / "problems.yaml")
CHECKS: dict = {}


def check(problem_id):
    def register(fn):
        CHECKS[problem_id] = fn
        return fn
    return register


def exact(value):
    return ("exact", sympy.nsimplify(value) if not isinstance(value, sympy.Basic) else value)


def approx(value, tol):
    return ("approx", float(value), tol)


def choice(letter):
    return ("choice", letter)


# ----------------------------------------------------------------------------------------------- small helpers

def compose(p, q):
    return tuple(p[i] for i in q)          # (p after q)


def cycle_lengths(p):
    seen, lengths = set(), []
    for start in range(len(p)):
        if start not in seen:
            length, i = 0, start
            while i not in seen:
                seen.add(i)
                i = p[i]
                length += 1
            lengths.append(length)
    return lengths


def permutation_order(p):
    return math.lcm(*cycle_lengths(p))


def closure(generators, identity):
    group, frontier = {identity}, [identity]
    while frontier:
        nxt = []
        for g in frontier:
            for s in generators:
                h = compose(s, g)
                if h not in group:
                    group.add(h)
                    nxt.append(h)
        frontier = nxt
    return frozenset(group)


def topologies(n, t0=False):
    whole = frozenset(range(n))
    inner = [frozenset(s) for r in range(1, n) for s in itertools.combinations(range(n), r)]
    count = 0
    for mask in range(2 ** len(inner)):
        family = {frozenset(), whole} | {inner[i] for i in range(len(inner)) if mask >> i & 1}
        if all((a | b) in family and (a & b) in family for a in family for b in family):
            separated = all(any((x in U) != (y in U) for U in family) for x in range(n) for y in range(x + 1, n))
            if not t0 or separated:
                count += 1
    return count


def domino_tilings(rows, cols):
    """Column-by-column transfer: `mask` marks cells of the current column already covered from the left."""
    def transitions(mask):
        out = []

        def place(r, nxt):
            if r == rows:
                out.append(nxt)
            elif mask >> r & 1:
                place(r + 1, nxt)
            else:
                place(r + 1, nxt | (1 << r))                              # horizontal domino into the next column
                if r + 1 < rows and not mask >> (r + 1) & 1:
                    place(r + 2, nxt)                                     # vertical domino
        place(0, 0)
        return out

    states = {0: 1}
    for _ in range(cols):
        new = {}
        for mask, ways in states.items():
            for nxt in transitions(mask):
                new[nxt] = new.get(nxt, 0) + ways
        states = new
    return states.get(0, 0)


# ----------------------------------------------------------------------------------------------- core

@check("ana-factorial-root")
def _():
    n = 10**7
    return approx(math.exp(math.lgamma(n + 1) / n) / n, 5e-5)


@check("ana-radius-central")
def _():
    n, lg = 10**5, math.lgamma
    log_ratio = (lg(3 * n + 4) - 3 * lg(n + 2)) - (lg(3 * n + 1) - 3 * lg(n + 1))     # log(a_{n+1}/a_n)
    return approx(math.exp(-log_ratio), 1e-6)                                         # radius = lim a_n/a_{n+1}


@check("ana-l2-projection")
def _():
    x, a, b = sympy.symbols("x a b", real=True)
    f = sympy.integrate((x**2 - a - b * x) ** 2, (x, 0, 1))
    solution = sympy.solve([sympy.diff(f, a), sympy.diff(f, b)], [a, b])
    return exact(f.subs(solution))


@check("alg-order5-s7")
def _():
    return exact(sum(1 for p in itertools.permutations(range(7)) if permutation_order(p) == 5))


@check("alg-aut-z6z6")
def _():
    group = [(a, b) for a in range(6) for b in range(6)]
    count = 0
    for u in group:                    # an endomorphism is fixed by the images u, v of the two generators
        for v in group:
            image = {((a * u[0] + b * v[0]) % 6, (a * u[1] + b * v[1]) % 6) for a, b in group}
            count += len(image) == 36  # bijective
    return exact(count)


@check("alg-s4-false-statement")
def _():
    elements = list(itertools.permutations(range(4)))
    identity = tuple(range(4))
    subgroups = {closure([a, b], identity) for a in elements for b in elements}
    assert len(subgroups) == 30                                  # the well-known number of subgroups of S4
    inverse = {g: next(h for h in elements if compose(g, h) == identity) for g in elements}
    normal = lambda H: all(frozenset(compose(compose(g, h), inverse[g]) for h in H) == H for g in elements)  # noqa: E731
    abelian = lambda H: all(compose(a, b) == compose(b, a) for a in H for b in H)  # noqa: E731
    order6 = [H for H in subgroups if len(H) == 6]
    truth = {
        "A": sum(permutation_order(p) == 2 for p in elements) == 9,
        "B": any(len(H) == 4 and normal(H) for H in subgroups),
        "C": any(len(H) == 12 for H in subgroups),
        "D": any(len(H) == 8 and normal(H) for H in subgroups),
        "E": bool(order6) and not any(abelian(H) for H in order6),      # order 6 and non-abelian means S3
    }
    false = [k for k, v in truth.items() if not v]
    assert len(false) == 1
    return choice(false[0])


@check("la-path-eigenvalue")
def _():
    A = np.diag(np.ones(3), 1) + np.diag(np.ones(3), -1)
    return approx(np.linalg.eigvalsh(A).max(), 1e-12)


@check("nt-power-tower")
def _():
    order = next(k for k in range(1, 1000) if pow(7, k, 1000) == 1)
    assert order == 20
    exponent_mod = pow(7, 7**7, order)                 # 7^(7^7) mod 20
    return exact(pow(7, exponent_mod, 1000))


@check("prob-expected-cycles")
def _():
    from sympy.functions.combinatorial.numbers import stirling
    n = 10
    total = sum(k * stirling(n, k, kind=1, signed=False) for k in range(1, n + 1))
    return exact(sympy.Rational(total, math.factorial(n)))


@check("cx-residue-e")
def _():
    n = 4000
    z = 2 * np.exp(2j * np.pi * np.arange(n) / n)
    value = np.mean(z * np.exp(z) / (z**2 * (z - 1)))        # (1/2πi)∮ f dz = mean of z·f(z) on the circle
    assert abs(value.imag) < 1e-9
    return approx(value.real, 1e-9)


@check("cx-rouche-annulus")
def _():
    roots = np.roots([1, 0, 0, 0, -5, 0, 0, 12])
    moduli = np.abs(roots)
    assert np.all(np.abs(moduli - 1) > 1e-6) and np.all(np.abs(moduli - 2) > 1e-6)   # none on the circles
    return exact(int(np.sum((moduli > 1) & (moduli < 2))))


@check("top-topologies-3")
def _():
    return exact(topologies(3))


# ----------------------------------------------------------------------------------------------- advanced

@check("ana-arctan-telescoping")
def _():
    return approx(mpmath.nsum(lambda n: mpmath.atan(2 / n**2), [1, mpmath.inf]), 1e-10)


@check("ana-sinc-cubed")
def _():
    return approx(mpmath.quadosc(lambda x: mpmath.sinc(x) ** 3, [0, mpmath.inf], omega=1), 1e-8)


@check("ana-sine-iteration")
def _():
    a, n_max = 1.0, 3_000_000
    for _ in range(n_max - 1):
        a = math.sin(a)
    return approx(n_max * a * a, 1e-4)


@check("ana-x-cot-x")
def _():
    return approx(mpmath.quad(lambda x: x * mpmath.cot(x), [0, mpmath.pi / 2]), 1e-12)


@check("alg-units-involutions")
def _():
    return exact(sum(1 for x in range(2, 360) if math.gcd(x, 360) == 1 and x * x % 360 == 1))


@check("alg-gaussian-homs")
def _():
    # phi(a + b*i) = a + b*t must respect multiplication for all a, b, c, d.
    ok = lambda t: all(((a * c - b * d) + (a * d + b * c) * t) % 65 == ((a + b * t) * (c + d * t)) % 65  # noqa: E731
                       for a, b, c, d in itertools.product(range(4), repeat=4))
    return exact(sum(1 for t in range(65) if ok(t)))


@check("alg-gl2f5-order3")
def _():
    identity = (1, 0, 0, 1)
    mul = lambda m, n: ((m[0] * n[0] + m[1] * n[2]) % 5, (m[0] * n[1] + m[1] * n[3]) % 5,   # noqa: E731
                        (m[2] * n[0] + m[3] * n[2]) % 5, (m[2] * n[1] + m[3] * n[3]) % 5)
    count = 0
    for m in itertools.product(range(5), repeat=4):
        if (m[0] * m[3] - m[1] * m[2]) % 5 == 0:
            continue
        power, order = m, 1
        while power != identity:
            power, order = mul(power, m), order + 1
        count += order == 3
    return exact(count)


@check("alg-commuting-involutions")
def _():
    elements = list(itertools.permutations(range(5)))
    e = tuple(range(5))
    count = sum(1 for a in elements for b in elements
                if compose(a, a) == e and compose(b, b) == e and compose(a, b) == compose(b, a))
    return exact(count)


@check("la-hilbert-det")
def _():
    return exact(sympy.Matrix(5, 5, lambda i, j: sympy.Rational(1, i + j + 1)).det())


@check("la-gcd-det")
def _():
    return exact(sympy.Matrix(8, 8, lambda i, j: math.gcd(i + 1, j + 1)).det())


@check("la-idempotents-f2")
def _():
    mats = np.array(list(itertools.product(range(2), repeat=9))).reshape(-1, 3, 3)
    return exact(int(np.all((mats @ mats) % 2 == mats, axis=(1, 2)).sum()))


@check("la-nilpotent-f3")
def _():
    mats = np.array(list(itertools.product(range(3), repeat=9))).reshape(-1, 3, 3)
    return exact(int(np.all((mats @ mats @ mats) % 3 == 0, axis=(1, 2)).sum()))


@check("nt-two-squares-mod-65")
def _():
    return exact(sum(1 for x in range(65) for y in range(65) if (x * x + y * y) % 65 == 0))


@check("nt-consecutive-residues")
def _():
    squares = {x * x % 101 for x in range(1, 101)}
    return exact(sum(1 for a in range(1, 100) if a in squares and a + 1 in squares))


@check("nt-sum-phi-floor")
def _():
    phi = lambda n: sum(1 for k in range(1, n + 1) if math.gcd(k, n) == 1)  # noqa: E731
    return exact(sum(phi(n) * (200 // n) for n in range(1, 201)))


@check("nt-quartic-residue-primes")
def _():
    return exact(sum(p for p in sympy.primerange(3, 100) if any(pow(x, 4, p) == p - 1 for x in range(p))))


@check("comb-domino-3xn")
def _():
    assert domino_tilings(3, 2) == 3 and domino_tilings(2, 5) == 8 and domino_tilings(8, 8) == 12988816  # sanity
    return exact(domino_tilings(3, 10))


@check("comb-row-col-sums")
def _():
    pairs = list(itertools.combinations(range(5), 2))
    count = 0
    for rows in itertools.product(pairs, repeat=5):
        sums = [0] * 5
        for r in rows:
            sums[r[0]] += 1
            sums[r[1]] += 1
        count += sums == [2] * 5
    return exact(count)


@check("prob-hhthh")
def _():
    pattern = "HHTHH"
    nxt = lambda k, c: max(L for L in range(len(pattern) + 1)              # noqa: E731
                           if L <= k + 1 and (pattern[:k] + c).endswith(pattern[:L]))
    E = sympy.symbols("E0:5")
    equations = [sympy.Eq(E[k], 1 + sympy.Rational(1, 2) * sum(0 if nxt(k, c) == 5 else E[nxt(k, c)] for c in "HT"))
                 for k in range(5)]
    return exact(sympy.solve(equations, E)[E[0]])


@check("prob-floor-ratio-even")
def _():
    rng = np.random.default_rng(12345)
    x, y = rng.random(4_000_000), 1 - rng.random(4_000_000)               # y in (0, 1]
    return approx(np.mean(np.floor(x / y) % 2 == 0), 2e-3)


@check("cx-trig-integral")
def _():
    return approx(mpmath.quad(lambda t: 1 / (2 + mpmath.cos(t)) ** 2, [0, 2 * mpmath.pi]), 1e-12)


@check("top-t0-topologies")
def _():
    return exact(topologies(3, t0=True))


# ----------------------------------------------------------------------------------------------- challenge

@check("ana-recurrence-log")
def _():
    a, marks, n = 1.0, {}, 1
    targets = {10**5, 3 * 10**6}
    while n < 3 * 10**6:
        a, n = a + 1 / a, n + 1
        if n in targets:
            marks[n] = a * a - 2 * n
    (n1, d1), (n2, d2) = sorted(marks.items())
    return approx((d2 - d1) / (math.log(n2) - math.log(n1)), 1e-3)         # slope of a_n^2 - 2n against ln n


@check("la-max-det-pm1")
def _():
    bits = (np.arange(2**16)[:, None] >> np.arange(16)) & 1
    mats = np.ones((2**16, 5, 5))
    mats[:, 1:, 1:] = (1 - 2 * bits).reshape(-1, 4, 4)       # first row and column all +1: negating rows/columns only flips det's sign
    best = int(np.abs(np.round(np.linalg.det(mats))).max())
    assert round(np.linalg.det(np.ones((5, 5)) - 2 * np.eye(5))) == 48       # the explicit matrix J - 2I
    return exact(best)


@check("comb-spanning-trees-q4")
def _():
    n = 16
    L = [[0] * n for _ in range(n)]
    for v in range(n):
        for k in range(4):
            L[v][v] += 1
            L[v][v ^ (1 << k)] -= 1
    return exact(sympy.Matrix([row[1:] for row in L[1:]]).det())             # Kirchhoff's matrix-tree theorem


@check("comb-cube-edge-colorings")
def _():
    rot_x = ((1, 0, 0), (0, 0, -1), (0, 1, 0))
    rot_y = ((0, 0, 1), (0, 1, 0), (-1, 0, 0))
    flat = lambda m: tuple(v for row in m for v in row)  # noqa: E731
    mul = lambda a, b: tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # noqa: E731
    group, frontier = {((1, 0, 0), (0, 1, 0), (0, 0, 1))}, [((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    while frontier:
        nxt = []
        for g in frontier:
            for s in (rot_x, rot_y):
                h = mul(s, g)
                if h not in group:
                    group.add(h)
                    nxt.append(h)
        frontier = nxt
    assert len(group) == 24
    vertices = list(itertools.product((-1, 1), repeat=3))
    edges = sorted({tuple((a + b) // 2 for a, b in zip(u, v)) for u in vertices for v in vertices
                    if sum(x != y for x, y in zip(u, v)) == 1})              # edge midpoints, e.g. (1, 1, 0)
    assert len(edges) == 12
    total = 0
    for g in group:
        image = {m: tuple(sum(g[i][j] * m[j] for j in range(3)) for i in range(3)) for m in edges}
        seen, cycles = set(), 0
        for m in edges:
            if m not in seen:
                cycles += 1
                while m not in seen:
                    seen.add(m)
                    m = image[m]
        total += 3**cycles
    return exact(sympy.Rational(total, 24))


@check("prob-uniform-sum-exceeds-2")
def _():
    # Renewal equation M(t) = 1 + integral of M over (t-1, t) intersected with (0, t); trapezoid rule, step h.
    h, k, steps = 1e-3, 1000, 2000
    m, c = np.empty(steps + 1), np.empty(steps + 1)
    m[0], c[0] = 1.0, 0.0
    for i in range(1, steps + 1):
        m[i] = (1.0 + c[i - 1] + h / 2 * m[i - 1] - (c[i - k] if i >= k else 0.0)) / (1 - h / 2)
        c[i] = c[i - 1] + h / 2 * (m[i - 1] + m[i])
    rng = np.random.default_rng(2024)                       # and a direct simulation as a second opinion
    total, trials = 0, 0
    for _ in range(5):                                      # in chunks: low memory use
        sums = np.cumsum(rng.random((200_000, 30)), axis=1)
        total += int((np.argmax(sums > 2, axis=1) + 1).sum())
        trials += 200_000
    simulated = total / trials
    assert abs(simulated - m[steps]) < 0.01
    return approx(m[steps], 1e-5)


@check("top-3-sheeted-covers")
def _():
    perms = list(itertools.permutations(range(3)))
    inverse = lambda p: tuple(sorted(range(3), key=lambda i: p[i]))  # noqa: E731

    def transitive(s, t):
        seen, stack = {0}, [0]
        while stack:
            i = stack.pop()
            for g in (s, t):
                if g[i] not in seen:
                    seen.add(g[i])
                    stack.append(g[i])
        return len(seen) == 3

    orbits = {min((compose(compose(g, s), inverse(g)), compose(compose(g, t), inverse(g))) for g in perms)
              for s in perms for t in perms if transitive(s, t)}
    return exact(len(orbits))


@check("geo-tricylinder")
def _():
    s = mpmath.sqrt(2) / 2
    f = lambda x: mpmath.sqrt(1 - x**2) * x                      # on [0, 1/sqrt2], min(x, sqrt(1-x^2)) = x
    g = lambda x: 1 - x**2                                       # on [1/sqrt2, 1], it is sqrt(1-x^2)
    volume = 16 * (mpmath.quad(f, [0, s]) + mpmath.quad(g, [s, 1]))
    rng = np.random.default_rng(7)
    hits, trials = 0, 0
    for _ in range(10):                                          # in chunks: low memory use
        p = rng.uniform(-1, 1, (1_000_000, 3)) ** 2
        hits += int(((p[:, 0] + p[:, 1] <= 1) & (p[:, 1] + p[:, 2] <= 1) & (p[:, 0] + p[:, 2] <= 1)).sum())
        trials += 1_000_000
    assert abs(8 * hits / trials - volume) < 0.01                # Monte Carlo agrees with the 1-D integral
    return approx(volume, 1e-12)


@check("cx-sum-one-over-n2plus1")
def _():
    return approx(mpmath.nsum(lambda n: 1 / (n**2 + 1), [1, mpmath.inf]), 1e-12)


# ----------------------------------------------------------------------------------------------- the tests

def bank_value(problem):
    return to_sympy(validate_expression(problem.answer)[1])


def test_every_problem_has_a_check():
    missing = [p.id for p in BANK if p.id not in CHECKS]
    assert not missing, f"These problems have no independent verification: {missing}"
    assert not set(CHECKS) - {p.id for p in BANK}, "checks exist for problems that are not in the bank"


@pytest.mark.parametrize("problem", list(BANK), ids=lambda p: p.id)
def test_answer_is_independently_verified(problem):
    result = CHECKS[problem.id]()
    kind = result[0]
    if kind == "choice":
        assert problem.answer_type == "choice" and problem.answer == result[1]
    elif kind == "exact":
        assert sympy.simplify(bank_value(problem) - result[1]) == 0, (problem.answer, result[1])
    else:
        _, value, tol = result
        assert abs(float(sympy.N(bank_value(problem), 30)) - value) <= tol, (problem.answer, value, tol)
