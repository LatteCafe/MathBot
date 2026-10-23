# Math Discord Bot

A modular, free-to-run Discord bot for mathematics, built with `discord.py` and SymPy.

**Status: Milestone 3 complete.** Implemented: project foundation, configuration, SQLite migrations, the symbolic
calculator (simplify, factor, expand, diff, integrate, limit, evaluate, solve, matrices), LaTeX rendering (`/latex`,
plus typeset calculator results), and the **Problem of the Day** (scheduled daily post, hints, private answer
checking, streaks, leaderboard, a bank of 42 university-level problems). Not yet implemented: contests, newsletter
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
| `/matrix operation a [b]` | `inverse` of `[[1,2],[3,4]]` | determinant, inverse, transpose, trace, rank, rref, eigenvalues, add, subtract, multiply (see "Matrices") |
| `/potd setup / status / post / stats / leaderboard` | | the daily problem (see "Problem of the Day") |
| `/latex expression` | `\int_0^1 x^2\,dx` | renders LaTeX math as an image (see "LaTeX syntax" below) |
| `/ping` | | liveness check |
| `/invite` | | the link that adds the bot to a server as a real member (see "Adding the bot to a server") |

Calculator results are typeset as an image when possible. The plain-text result stays in the message so it can be
copied, and if an image cannot be produced the bot sends text only; the command never fails because of rendering.

**Input syntax:** `+ - * / ^`, parentheses, implicit multiplication (`2x`, `(x+1)(x-1)`), constants `pi`, `e`, `oo`,
single-letter variables, and the functions `sin cos tan asin acos atan sinh cosh tanh exp log ln sqrt abs`.
Decimals are treated as exact fractions (`0.5` = `1/2`), so results stay exact. A decimal may have at most 15
significant digits: longer ones cannot be held exactly by Python's number parser and would be rounded without
warning, so they are rejected with a message (use a fraction such as `1/3` instead).

**Exact vs approximate:** exact results are always shown first; a decimal approximation is shown separately,
and only when it adds information (e.g. for `sqrt(2)`, not for `3/4`).

## Matrices (`/matrix`)

Write a matrix as a list of rows: `[[1, 2], [3, 4]]`. A row is `[[1, 2, 3]]` and a column is `[[1], [2], [3]]`.
Entries can be numbers, fractions, or expressions (`[[1/2, sqrt(2)], [x^2, 0]]`).

| Operation | Notes |
|---|---|
| determinant, inverse, trace, eigenvalues | square matrices only |
| transpose, rank, rref (reduced row echelon form, with pivot columns) | any shape |
| add, subtract | A and B must be the same size |
| multiply | A × B needs columns of A = rows of B; B may instead be a number or expression (scalar multiple) |

* **Results can be pasted straight back in.** The plain-text result of an operation (`[[-2, 1], [3/2, -1/2]]`) is a
  valid input to the next one, so operations chain: the inverse of the inverse is the original.
* **Limits:** numeric matrices up to 6×6; matrices containing variables up to 4×4 (a fully symbolic 5×5
  determinant takes seconds and a 6×6 takes minutes). Entries cannot contain infinity.
* **Inverse:** a singular matrix is reported as "not invertible" (determinant 0), not an error. For a symbolic
  matrix the result states the determinant it is valid for.
* **Eigenvalues** (over the complex numbers) come from the characteristic polynomial factored over the rationals.
  Factors of degree 1 and 2 give exact values, including multiplicities and `I` for complex ones. An irreducible
  factor of degree 3 or higher is shown as decimal approximations (`≈`) of the roots of that named polynomial,
  because SymPy's own closed form for those is unreadable (a cubic with three *real* roots comes back full of
  complex numbers). If the eigenvalues cannot be found at all (e.g. a 3×3 with a variable in it) the result is
  "not established", never a guess.
* **Rank and rref of a matrix with variables** hold for *generic* values of the variables; special values can
  change them, and the result says so.
* Matrices are drawn with this project's own layout code (`rendering/draw.py`), so results come back as proper
  bracketed matrices. Brackets remain invalid in every other command; those point you to `/matrix`.

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
* **Very large results are recognised, not dumped into the chat.** A result longer than 600 characters (for example
  `999^999`, an integer with 2,997 digits) is replaced by a short summary (digit count, scientific notation and the
  last digits for integers; term count for a long sum; size for a matrix) and the complete value is attached as
  `result.txt`. Integers with more than about 30 digits show that summary line even when they fit. Results beyond
  100,000 characters are cut off, say so, and are not attached. (Python normally refuses to print integers of more
  than 4,300 digits, which used to crash the calculation; inside the sandboxed worker that limit is raised to the
  bot's own explicit 100,000.)
* Heavy expansions, integrals and limits that exceed the time limit are stopped and reported as such.

Deliberately **not** implemented: a numerical fallback for integrals SymPy cannot solve. Numerical integration
returned garbage for divergent integrals and false alarms for correct ones in testing, so a "cross-check" would
have been less trustworthy than saying nothing.

**Variables:** `/diff` treats variables as real numbers (so d/dx |x| is `sign(x)`). `/solve` and `/simplify`
use SymPy's default assumptions.

**Honest failures:** if SymPy cannot solve an equation in closed form, the bot says the result is
*not established*. It never reports "no solutions" unless that was actually established.

## Problem of the Day

A university-level problem posted once a day in a channel you choose. Everything private (hints, answer checking,
solutions) happens in replies only the person who clicked can see, so nothing is ever spoiled in the channel.

**Difficulty levels** (none is school-level; there are no "simple polynomial" questions):

| Level | What it is | In the bank |
|---|---|---|
| `core` | upper-division course material (analysis, algebra, linear algebra, ...); 10-20 minutes for someone who took the course | 12 |
| `advanced` | competition-style: needs a real idea or a careful multi-step argument | 22 |
| `challenge` | hard (Putnam-hard or graduate flavoured); may take hours | 8 |

Subjects: analysis, abstract algebra, linear algebra, number theory, combinatorics, probability, complex analysis,
topology, geometry. Subjects rotate (the one posted longest ago comes next), and the default `any` difficulty mixes
the levels 40% core / 40% advanced / 20% challenge. All problems are original or classical results written for this
bot, with exact answers such as `3*pi/4`, `1/e` or `7381/2520`.

**Setting it up** (needs the *Manage Server* permission):

1. `/potd setup channel:#problem-of-the-day hour:9 timezone:America/Toronto enabled:True`
   (timezone names autocomplete as you type; difficulty and "no repeats within N days" are optional).
2. `/potd post` posts today's problem immediately, which is handy for a first test. `replace:True` discards
   today's post, *and everyone's progress on it*, and posts a new one.
3. `/potd status` shows the settings, the next post time and the bank size.

Every setting is per server, and `/potd setup` only changes what you pass.

**What members see:** each post has three buttons.

| Button | What it does |
|---|---|
| 💡 Hint | the next hint (1-3 per problem), shown privately; hints never block credit |
| ✏️ Submit answer | opens a form; the answer is graded symbolically, so `2*pi/8`, `pi/4` and `0.25*pi` all match `pi/4`; decimal approximations of irrational answers do not. Multiple-choice problems take a letter |
| 📖 Solution | the worked solution, privately. Before you have solved the problem it asks for confirmation, because viewing it forfeits credit |

`/potd stats [user]` shows solves, current and best streak, solves without hints, and a per-subject breakdown.
`/potd leaderboard` shows the top ten; ties share a rank.

**Rules:**

* **Answers are open during the problem's own local day** (in the server's timezone). After midnight, submissions are
  closed, but hints and the solution stay available. There are no late solves.
* **Attempts** are unlimited for value answers, with a 10-second cooldown per person; multiple-choice problems allow
  2 attempts. An answer that cannot be read (bad syntax, too many digits) does not count as an attempt, and neither does
  a grading failure such as a timeout.
* **Viewing the solution before solving** forfeits credit for that problem (no solve, no streak). Viewing it after
  solving, or after the day ends, costs nothing.
* **Streaks count consecutive posts, not calendar days**, so a day on which the bot posted nothing (an outage) never
  breaks anyone's streak. Today's still-open problem neither extends nor breaks your streak until it is solved or the
  day ends.
* A problem is not repeated within the server's repeat window (default 60 days). The bank is finite, so once every
  problem is inside the window the least recently posted ones are reused; add problems to extend it.

**Scheduling and restarts.** A once-a-minute loop checks each enabled server. State lives in SQLite, not memory:

* A post is **claimed in the database before it is sent** (one row per server per local day), so two overlapping runs
  cannot both post. If sending fails (channel deleted, missing permissions) the claim is released and retried after a
  15-minute back-off. If the bot crashes between claiming and sending, the claim is taken over after 10 minutes, so
  the result is a late post, never a duplicate or a missing one.
* If the bot was down at the scheduled time it posts when it returns, up to 6 hours late (same local day). Beyond that
  the day is skipped rather than posting a backlog.
* The buttons use fixed IDs and look the problem up by message, so they keep working after a restart.
* Daylight-saving transitions are handled (a time that does not exist, such as 02:30 on a spring-forward night, still
  posts once that day).

**The problem bank** is `data/problems.yaml` (see the header of that file for every field). To add a problem, append an
entry, then **add an independent check for it in `tests/test_problem_answers.py`**: a function that recomputes the
answer by a different route from the worked solution (brute force, exact arithmetic, high-precision numerics, a
simulation). The test suite fails if any problem lacks a check, and fails if a check disagrees with the stated
answer. The loader validates the file at start-up and reports every error at once, so a typo stops the bot with a
clear message instead of surfacing at 9 a.m. Problem statements are plain text/Unicode; an optional `display` field
holds LaTeX that is typeset as an image (the same renderer as `/latex`).

**Known limitations.** One bot process per database (there is no cross-process locking beyond the unique post row).
The 42-problem bank repeats after about six weeks at one problem a day. Problems are posted at one time per server (no
per-subject channels). If the bot crashes in the instant between Discord accepting a message and the database
recording its ID, that post's buttons stop working and the next scheduler pass may post again.

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
*Bot* → copy the token into `.env`. No privileged intents are needed.

### Adding the bot to a server

The bot must be added **with the `bot` scope**, which makes it a real member of the server. When it starts, the log
prints a ready-made link (`Invite link (adds the bot as a real server member): ...`), and `/invite` shows the same
link. Use that link, or in OAuth2 → URL Generator tick the scopes `bot` **and** `applications.commands` and the
permissions *View Channels*, *Send Messages*, *Embed Links* and *Attach Files*.

**Permissions the bot needs** (the generated link asks for exactly these; permission value `52224`):

| Permission | Why it is needed |
|---|---|
| View Channels | to see the channel the daily problem is posted in |
| Send Messages | to post the daily problem |
| Embed Links | the problem is posted as an embed |
| Attach Files | the typeset formula image on the daily problem (a normal channel message); keep it on so image and file replies from commands also work in channels where Discord applies it |

Not needed, so do not grant them: Administrator, Manage Server/Channels/Messages/Roles, Read Message History, Add
Reactions, Mention Everyone, Use External Emojis, Create Invite. The bot reads no messages (slash commands only), so it
needs no privileged intent. Slash-command replies and buttons work with no extra permission.

**Fixing the Developer Portal's default install link.** In the [Developer Portal](https://discord.com/developers/applications)
open your application's *Installation* page (the layout changes from time to time, so look for the equivalent):

1. *Installation Contexts*: tick **Guild Install**. Untick **User Install** unless you want it: a user-installed app is
   never a member of any server, which causes exactly the problems in the table below.
2. *Install Link*: choose the Discord-provided link.
3. *Default Install Settings* → *Guild Install* → **Scopes**: `applications.commands` **and `bot`**.
4. Same place → **Permissions**: View Channels, Send Messages, Embed Links, Attach Files.
5. On the *Bot* page, **Public Bot** must be on if anyone other than you will add it.

If the bot was added with only the `applications.commands` scope (an easy mistake with an install link that lacks
`bot`), slash commands still answer, but:

| Symptom | Cause | Fix |
|---|---|---|
| the bot is not in the member list, and has no online status there | it is not a member | re-authorise with the link above (this adds it; nothing is lost) |
| you cannot give it permissions or a role | no member means no managed role | same fix |
| the daily problem only works in public channels | a non-member can only use what `@everyone` can | same fix, then allow the bot's role in any private channel |

`/potd setup` and `/potd status` detect this situation and say so, along with the link. After re-adding it, a
**private channel** needs the bot's role (named after the bot) allowed to *View Channel* there, plus
*Send Messages*, *Embed Links* and *Attach Files*. `/potd status` shows the last reason a post failed (a missing
permission, an invisible channel, a refusal from Discord), and a missing permission is reported before any send is
attempted.

### Online status and the activity

The bot logs in already **online** (a green dot in the member list, as long as it is a real member), with an activity,
and then rotates through 26 maths-themed lines every 10 minutes.

How Discord displays them shapes the wording: in the member list a *Playing* activity appears as bare text with no
"Playing" in front, while *Watching*, *Listening to* and *Competing in* keep their prefix, and the list is narrow and
cuts text off. So the "playing" lines are written like game titles (*Nim (XOR the piles)*, *Hanoi, 10 discs: 1,023
moves*, *Euler: e^(iπ) + 1 = 0*), the others follow their prefix (*Watching the primes thin out*, *Listening to the
harmonic series*, *Competing in an unofficial Putnam*), and the key words come first. Some lines are live: the number of
servers, the size of the problem bank, and **today's problem title** once one has been posted (the title never gives
anything away). Every factual claim in the lines is checked by the tests, including an exhaustive search that proves
the Nim line.

Settings (in `.env`): `BOT_STATUS` (`online`, `idle`, `dnd` or `invisible`), `PRESENCE_ENABLED` (`false` removes the
activity), `PRESENCE_INTERVAL_MINUTES`, and `PRESENCE_STYLE`:

* `activity` (default): the typed activities above. These are known to work for bots.
* `custom`: the same lines sent as a *custom status* (an emoji plus text, with the words "Playing", "Watching" and so
  on written out, e.g. "🎮 Playing Nim (XOR the piles)"). The library supports it, but whether Discord displays a custom
  status for bots is not something I could verify, so try it and switch back to `activity` if the sidebar shows nothing.

Discord's richer "Rich Presence" (timestamps, buttons, images) is not available to bots.

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
| `PROBLEMS_PATH` | `data/problems.yaml` | The Problem of the Day bank |
| `BOT_STATUS` | `online` | `online`, `idle`, `dnd` or `invisible` |
| `PRESENCE_ENABLED` | `true` | Show the rotating maths-themed "Playing ..." activity |
| `PRESENCE_INTERVAL_MINUTES` | `10` | How often the activity changes |
| `PRESENCE_STYLE` | `activity` | `activity` (Playing/Watching/...) or `custom` (emoji + text status) |

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
cogs/                  Discord layer only (slash commands, message formatting, membership checks, presence)
math_engine/           NO Discord imports
  validate.py            safety gate (stdlib only)
  convert.py, operations.py, worker.py   SymPy side, runs in the worker process
  engine.py              async facade: pre-check, call the sandbox, parse result
  sandbox.py, limits.py  run a worker process with timeout, memory cap, minimal environment (shared with rendering)
rendering/             NO Discord imports
  parse.py               LaTeX validation and splitting into math/matrix segments (stdlib only)
  draw.py, worker.py     matplotlib drawing + matrix layout; runs in the worker process
  renderer.py            async facade used by the cogs
services/              problem bank loader, answer grading, Problem of the Day rules (no Discord imports)
  potd_logic.py          pure scheduling, problem selection and streak functions
database/              SQLite connection + versioned migrations (database/migrations/NNN_*.sql), potd_repo.py
data/problems.yaml     the problem bank
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
4. **Back up the database** (it holds Problem of the Day settings, solves and streaks, and later contests), e.g. a daily cron job:
   `sqlite3 data/mathbot.sqlite3 ".backup '/home/ubuntu/backup/mathbot-$(date +%F).sqlite3'"`.
5. Free VMs may be reclaimed if they sit idle, so keep the bot running and check on it occasionally.

If every calculation fails with "stopped unexpectedly" on a small or ARM VM, try raising `MATH_MEMORY_LIMIT_MB`
(the cap is on virtual address space, which can be larger than real memory use). This is untested on ARM.

## Tests

```bash
python -m pytest              # whole suite (about 45 seconds)
python -m pytest -k validate  # just the input-validation tests
```

Covered: input validation (accept/reject lists), SymPy operations (matrix results are additionally checked
against NumPy's eigenvalue solver and against identities such as A·A⁻¹ = I and det(AB) = det(A)·det(B)), the subprocess sandbox (timeout, memory limit,
secret-free environment), LaTeX parsing and rendering (including every kind of result the calculator can produce),
database migrations, configuration, message formatting, and the slash-command handlers driven with a stand-in
interaction (real engine, real renderer).
Problem of the Day is covered at every layer: the bank format; **an independent recomputation of all 42 answers**
(checked by tests that deliberately swap in wrong answers to prove the checks can fail); scheduling across time zones
and daylight-saving changes; problem selection; streaks; every rule above; crash recovery; and the Discord handlers
and scheduler, including each failure path.
**Not covered:** behaviour against the live Discord API (needs a real token; test by hand).

The first matplotlib run on a machine builds a font cache, which can take a while. The test suite and the bot's
start-up each do this once with a long timeout; later runs are fast. The cache lives in `data/.cache/` (git-ignored).

## Roadmap

1. ✅ Foundation + calculator (simplify, diff, solve)
2. ✅ LaTeX rendering and `/latex` (incl. matrices); ✅ factor, expand, integrate, limit, evaluate; ✅ `/matrix`
3. ✅ Problem of the Day (bank, scheduler, hints, grading, streaks, leaderboard)
4. Contests (individual first; answers never exposed before close)
5. Newsletter (arXiv, dedupe, ranking, clearly labelled preprints vs. verified items)
6. Optional: AI summaries, team contests
