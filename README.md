# Math Discord Bot

A modular, free-to-run Discord bot for mathematics, built with `discord.py` and SymPy.

**Status: Milestone 2b (part 1).** Implemented: project foundation, configuration, SQLite migrations, the symbolic
calculator (simplify, factor, expand, diff, integrate, limit, evaluate, solve), and LaTeX rendering (`/latex`, plus
typeset calculator results). Not yet implemented: matrix operations, Problem of the Day, contests, newsletter
(see the roadmap below).

## Commands

| Command | Example | Notes |
|---|---|---|
| `/simplify expression` | `(x^2 - 1)/(x - 1)` | |
| `/factor expression` | `x^3 - 6x^2 + 11x - 6` | over the rational numbers |
| `/expand expression` | `(x+1)^3` | |
| `/diff expression [variable] [order]` | `x^3 * sin(x)` | order 1–5; variable optional if only one |
| `/integrate expression [variable] [lower] [upper]` | `exp(-x^2)`, lower `-oo`, upper `oo` | indefinite, or definite when both bounds are given |
| `/limit expression point [variable] [direction]` | `sin(x)/x`, point `0` | direction: both sides (default), right, or left |
| `/evaluate expression [digits]` | `sqrt(2) + pi` | numeric value, 1–50 significant digits; no variables allowed |
| `/solve equation [variable] [domain]` | `x^2 - 4 = 0` | `real` (default) or `complex`; no `=` means "= 0" |
| `/latex expression` | `\int_0^1 x^2\,dx` | renders LaTeX math as an image (see "LaTeX syntax" below) |
| `/ping` | | liveness check |

Calculator results are typeset as an image when possible. The plain-text result stays in the message so it can be
copied, and if an image cannot be produced the bot sends text only; the command never fails because of rendering.

**Input syntax:** `+ - * / ^`, parentheses, implicit multiplication (`2x`, `(x+1)(x-1)`), constants `pi`, `e`, `oo`,
single-letter variables, and the functions `sin cos tan asin acos atan sinh cosh tanh exp log ln sqrt abs`.
Decimals are treated as exact fractions (`0.5` = `1/2`), so results stay exact.

**Exact vs approximate:** exact results are always shown first; a decimal approximation is shown separately,
and only when it adds information (e.g. for `sqrt(2)`, not for `3/4`).

**How the new operations report their results**

* `oo` means infinity (`-oo` for minus infinity); use it for bounds and limit points.
* **Integrals.** Indefinite results are antiderivatives (add `+ C`; where a `log` argument is negative, use
  `ln|argument|`). A definite integral that SymPy cannot evaluate, or that has a singularity inside the interval
  (e.g. 1/x on [-1, 1]), is reported as **not established**, never guessed. A divergent integral is reported as
  diverging. If a *real* integrand produces a *complex* answer, the result carries a branch-cut warning.
* **Limits.** Two-sided limits compute both sides: if they disagree the bot says the limit does not exist and shows
  both one-sided values (e.g. 1/x at 0). Oscillating limits (e.g. sin x as x → oo) are reported as not existing.
  An infinite limit (1/x² at 0) is reported as infinite. Direction is ignored at ±oo.
* **`/evaluate`** is always labelled approximate, except integers, which are shown as exact.
* **`/factor`** works over the rationals and says when nothing factors (x² − 2 still factors over the reals).
* Results that are too long to display are truncated and not typeset. Heavy expansions, integrals and limits that
  exceed the time limit are stopped and reported as such.

Deliberately **not** implemented: a numerical fallback for integrals SymPy cannot solve. Numerical integration
returned garbage for divergent integrals and false alarms for correct ones in testing, so a "cross-check" would
have been less trustworthy than saying nothing.

**Variables:** `/diff` treats variables as real numbers (so d/dx |x| is `sign(x)`). `/solve` and `/simplify`
use SymPy's default assumptions.

**Honest failures:** if SymPy cannot solve an equation in closed form, the bot says the result is
*not established*. It never reports "no solutions" unless that was actually established.

## LaTeX syntax (`/latex`)

Type the math itself, without `$` signs (they are stripped if you include them). Rendering is done locally with
matplotlib's math engine, so nothing is sent to a third-party service and no TeX installation is needed.

| Supported | Examples |
|---|---|
| Fractions, roots, binomials | `\frac{a}{b}` `\dfrac{1}{2}` `\sqrt{x}` `\sqrt[3]{x}` `\binom{n}{k}` |
| Integrals, sums, products | `\int_0^1 x^2\,dx` `\sum_{n=1}^{\infty} \frac{1}{n^2}` `\prod_{k=1}^n k` |
| Limits and functions | `\lim_{x \to 0} \frac{\sin x}{x}` `\sin` `\cos` `\log` `\arctan` |
| Greek and symbols | `\alpha` `\beta` `\Omega` `\pi` `\infty` `\partial` `\nabla` `\pm` `\leq` `\neq` `\approx` |
| Fonts and accents | `\mathbb{R}` `\mathcal{L}` `\mathrm{d}` `\text{if }` `\hat{x}` `\vec{v}` `\overline{z}` |
| Delimiters | `\left( ... \right)` `\left\{ ... \right\}` `\left| ... \right|` |
| **Matrices** | `\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}`, also `bmatrix`, `vmatrix`, `matrix`; up to 10x10 |

**Not supported:** other environments (`cases`, `align`, ...), nested matrices, custom macros/packages, multi-line
equations. Matplotlib has no matrix support of its own, so matrices are laid out by this project's own code
(`rendering/draw.py`); they can sit inside a larger expression (`A = \begin{pmatrix}...\end{pmatrix}^{-1}`)
but not inside one another. Malformed input gets a short error message, not a stack trace. Limits: 300 characters
(`LATEX_MAX_LENGTH`) and a maximum image size; images are drawn black on white so they read on dark and light themes.

## Quick start (local)

Requires Python 3.10+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt     # re-run this after pulling updates: dependencies change
cp .env.example .env          # then set DISCORD_TOKEN (and DEV_GUILD_ID for instant command updates)
python -m pytest              # run the tests
python bot.py                 # start the bot
```

**Discord setup:** in the [Developer Portal](https://discord.com/developers/applications) create an application →
*Bot* → copy the token into `.env`. No privileged intents are needed. Invite the bot using
*OAuth2 → URL Generator* with scopes `bot` and `applications.commands`.

## Configuration

All via environment variables (or `.env`). See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | *(required)* | Bot token. Never commit it. |
| `DEV_GUILD_ID` | *(none)* | Sync commands to one server instantly (development) |
| `DATABASE_PATH` | `data/mathbot.sqlite3` | SQLite file |
| `LOG_LEVEL` | `INFO` | |
| `MATH_TIMEOUT_SECONDS` | `15` | Wall-clock limit per calculation (includes SymPy start-up) |
| `MATH_MEMORY_LIMIT_MB` | `512` | Address-space cap for the calculation process |
| `MATH_MAX_INPUT_LENGTH` | `200` | Max characters per expression |
| `MATH_MAX_CONCURRENT` | `2` | Worker processes (calculations and renders together) running at once |
| `LATEX_MAX_LENGTH` | `300` | Max characters per `/latex` expression |

## How the calculator stays safe

User input is **never** passed to `eval()`, `exec()` or `sympify()`.

1. `math_engine/validate.py` parses text into a Python AST (parsing runs no code) and accepts only a whitelist of
   node types: numbers, single-letter names, `+ - * / ^`, and an allow-list of functions. Attribute access,
   subscripts, strings, lambdas, comparisons, etc. are rejected. Input length and expression size are capped, and
   huge powers such as `9^9^9` are rejected up front.
2. Invalid input is rejected in the bot process, so it never spawns a worker.
3. Valid input runs in a **separate worker process** (`math_engine/worker.py`) with a wall-clock timeout (the process
   is killed on expiry), a memory cap, and a CPU-time cap. The worker's environment contains no secrets.
   LaTeX rendering uses the same sandbox (`rendering/worker.py`). matplotlib's math parser never executes user
   input, but rendering is still isolated and size-limited.
4. The worker converts the validated AST to SymPy objects explicitly (`math_engine/convert.py`).

Known limit: the up-front power bounds are a first line of defence, not a proof that no expression can be slow.
The timeout and memory cap are the real guarantee. Memory/CPU caps use POSIX `resource` limits, so on Windows
only the timeout applies (fine for development; deploy on Linux).

## Project layout

```
bot.py                 entry point
config.py              environment -> Settings
cogs/                  Discord layer only (slash commands, message formatting)
math_engine/           NO Discord imports
  validate.py            safety gate (stdlib only)
  convert.py, operations.py, worker.py   SymPy side, runs in the worker process
  engine.py              async facade: pre-check, call the sandbox, parse result
  sandbox.py, limits.py  run a worker process with timeout, memory cap, minimal environment (shared with rendering)
rendering/             NO Discord imports
  parse.py               LaTeX validation and splitting into math/matrix segments (stdlib only)
  draw.py, worker.py     matplotlib drawing + matrix layout; runs in the worker process
  renderer.py            async facade used by the cogs
database/              SQLite connection + versioned migrations (database/migrations/NNN_*.sql)
tests/                 pytest suite
deploy/mathbot.service systemd unit
```

Rule of thumb: cogs call services/engines; they never run SQL or SymPy themselves. To change the database schema,
add a new `NNN_description.sql` migration file; never edit one that has already been applied.

## Deploying on Oracle Cloud Always Free

Oracle's free-tier limits have changed without notice before, so **check the current limits in the OCI console**
before relying on them. This bot is light: a small VM is enough. The bot only makes outbound connections to Discord,
so you do not need to open any inbound ports besides SSH.

1. Create an Always Free-eligible Ubuntu VM and SSH in.
2. Install and set up:
   ```bash
   sudo apt update && sudo apt install -y python3-venv git
   git clone <your-repo-url> mathbot && cd mathbot
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp .env.example .env && nano .env      # set DISCORD_TOKEN; leave DEV_GUILD_ID empty for global commands
   ```
3. Edit `deploy/mathbot.service` (`User`, paths, `MemoryMax` — lower it on a 1 GB VM), then:
   ```bash
   sudo cp deploy/mathbot.service /etc/systemd/system/
   sudo systemctl enable --now mathbot
   journalctl -u mathbot -f              # live logs
   ```
4. **Back up the database** (it holds streaks and contests from Phase 3 on), e.g. a daily cron job:
   `sqlite3 data/mathbot.sqlite3 ".backup '/home/ubuntu/backup/mathbot-$(date +%F).sqlite3'"`.
5. Free VMs may be reclaimed if they sit idle, so keep the bot running and check on it occasionally.

If every calculation fails with "stopped unexpectedly" on a small or ARM VM, try raising `MATH_MEMORY_LIMIT_MB`
(the cap is on virtual address space, which can be larger than real memory use). This is untested on ARM.

## Tests

```bash
python -m pytest              # whole suite (about 20 seconds)
python -m pytest -k validate  # just the input-validation tests
```

Covered: input validation (accept/reject lists), SymPy operations, the subprocess sandbox (timeout, memory limit,
secret-free environment), LaTeX parsing and rendering (including every kind of result the calculator can produce),
database migrations, configuration, message formatting, and the slash-command handlers driven with a stand-in
interaction (real engine, real renderer).
**Not covered:** behaviour against the live Discord API (needs a real token; test by hand).

The first matplotlib run on a machine builds a font cache, which can take a while. The test suite and the bot's
start-up each do this once with a long timeout; later runs are fast. The cache lives in `data/.cache/` (git-ignored).

## Roadmap

1. ✅ Foundation + calculator (simplify, diff, solve)
2. ✅ (2a) LaTeX rendering and `/latex`, including matrices. ✅ (2b, part 1) factor, expand, integrate, limit,
   evaluate. Next (2b, part 2): matrix operations (determinant, inverse, transpose, products, rank, eigenvalues)
3. Problem of the Day (question bank, hints, spoilers, streaks, restart-safe scheduler)
4. Contests (individual first; answers never exposed before close)
5. Newsletter (arXiv, dedupe, ranking, clearly labelled preprints vs. verified items)
6. Optional: AI summaries, team contests
