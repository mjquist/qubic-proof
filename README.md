# 4x4x4 Qubic First-Player Winning Strategy Certificate

This repository contains a standalone, machine-verifiable proof certificate (`opening_combined.tsv`) showing that the first player (`X`) has a forced win in Qubic ($4 \times 4 \times 4$ Tic-Tac-Toe in three dimensions) from every possible opening cell.

Under the full **192 combinatorial symmetries** of the $4 \times 4 \times 4$ Qubic board ($48$ geometric symmetries $\times 4$ inside-outside coordinate inversions), the 8 outer corners and 8 inner centers merge into one orbit (`0`), and the 24 edge cells and 24 face-center cells merge into a second orbit (`1`), leaving **2 symmetry-distinct opening moves**:

- **Opening `0` (`(0,0,0)`)**: 16 main-diagonal cells (corners and inner centers, 7 winning lines each)
- **Opening `1` (`(1,0,0)`)**: 48 off-diagonal cells (edge and face-center cells, 4 winning lines each)

`opening_combined.tsv` proves a forced first-player win from **both symmetry-distinct opening moves** (`0` and `1` — and therefore all 64 opening cells) in a single **`48,295`-row** table (`1.82 MB`).

## Files

- **`opening_combined.tsv`** (`48,295` rows, `1,816,414` bytes): Unified winning strategy dictionary covering both canonical opening moves (`0` and `1`).
- **`qubic_verifier.py`**: Standalone zero-dependency Python 3 script that parses `opening_combined.tsv` and exhaustively verifies that `X` forces a win against every legal reply by `O`.

## Quick Verification

Requires only Python 3 (standard library only, no external packages):

```bash
python3 qubic_verifier.py opening_combined.tsv
```

Expected output:

```text
[PASS] opening_combined.tsv
  opening_move=0,1
  certificate_rows=48295 verified_prover_states=48295
  disprover_branches=2443236
```

To verify a specific opening cell (any of the 64 cells, e.g. `0,0,0`, `1,1,1`, `1,0,0`, or `1,1,0`):

```bash
python3 qubic_verifier.py --opening 0,0,0 opening_combined.tsv
python3 qubic_verifier.py --opening 1,0,0 opening_combined.tsv
```

## Certificate Format

Lines starting with `//` are comments and are ignored by the verifier.

Each data line has 2 or 3 tab-separated columns:

```text
<board_state>	<move>[	<refutations>]
```

### Cell Encoding

Each of the 64 cells $(x, y, z) \in \{0, 1, 2, 3\}^3$ with index $c = 16z + 4y + x \in \{0, \dots, 63\}$ is represented by a single character from:

```text
0123456789#$ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz
```

Layered by $z$-plane (rows are $y = 0, 1, 2, 3$ from top to bottom; columns are $x = 0, 1, 2, 3$ from left to right):

```text
z=0:  0 1 2 3    z=1:  E F G H    z=2:  U V W X    z=3:  k l m n
      4 5 6 7          I J K L          Y Z a b          o p q r
      8 9 # $          M N O P          c d e f          s t u v
      A B C D          Q R S T          g h i j          w x y z
```

### Columns

1. **`<board_state>`**: Occupied cells listed by interleaving `X`'s moves and `O`'s moves in ascending character order (`X0 O0 X1 O1 ...`), canonicalized under the 192 symmetries of the $4 \times 4 \times 4$ cube. Because all rows represent positions on `X`'s turn after an equal number of `X` and `O` moves, `<board_state>` always has even length $2k$, where the even indices ($0, 2, \dots$) are `X`'s stones and the odd indices ($1, 3, \dots$) are `O`'s stones.
2. **`<move>`**: Single character indicating `X`'s chosen strategic move from `<board_state>`.
3. **`<refutations>`** *(optional)*: `' | '`-separated forced-threat sequences. Each sequence is a string of `X` moves in which every move plays on a line with 3 `X` stones and 0 `O` stones, forcing `O` to block the single remaining empty cell on that line. After `X` plays `<move>` and `O` plays any legal reply $r$:
   - If `O` has an immediate 3-in-a-row threat after `<move>`, `O` is forced to complete it (or block `X`'s immediate threat if `X` also threatened 4-in-a-row).
   - Otherwise, for each non-forced reply $r$ by `O`, either the resulting position canonicalizes directly to another row in the certificate, or at least one sequence in `<refutations>` is disjoint from $r$ and leads to an immediate 4-in-a-row / double-threat win for `X` or to another row in the certificate.
