#!/usr/bin/env python3
"""Standalone heuristic-free proof certificate verifier for 4x4x4 Qubic.

Certificate format (TSV; lines starting with '//' are ignored):
  <board_state>\t<move>[\t<refutation_sequences>]

where each of the 64 cells (index c = 16*z + 4*y + x in 0..63) is represented by
a single printable character from:
  0123456789#$ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz

- <board_state>: occupied cells listed in alternating Prover ('X') / Disprover
  ('O') order (e.g. '01#' means 'X' in cells 0 and '#' and 'O' in cell 1).
- <move>: a single character encoding Prover's strategic move.
- <refutation_sequences>: optional ' | '-separated list of forced threat
  refutation sequences, where each sequence is a string of single-character
  Prover moves.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

MASK64 = (1 << 64) - 1


def _in_bounds(x: int, y: int, z: int) -> bool:
  return 0 <= x < 4 and 0 <= y < 4 and 0 <= z < 4


def _build_win_lines() -> Tuple[Tuple[int, ...], Tuple[Tuple[int, ...], ...]]:
  """Precomputes all 76 winning line bitmasks and per-cell incident masks."""
  directions = (
      (1, 0, 0),
      (0, 1, 0),
      (0, 0, 1),
      (1, 1, 0),
      (-1, 1, 0),
      (1, 0, 1),
      (-1, 0, 1),
      (0, 1, 1),
      (0, -1, 1),
      (1, 1, 1),
      (-1, 1, 1),
      (1, -1, 1),
      (-1, -1, 1),
  )
  lines: List[int] = []
  cell_lines: List[List[int]] = [[] for _ in range(64)]
  for dx, dy, dz in directions:
    stride = 16 * dz + 4 * dy + dx
    for z in range(4):
      for y in range(4):
        for x in range(4):
          if not _in_bounds(x - dx, y - dy, z - dz) and _in_bounds(
              x + 3 * dx, y + 3 * dy, z + 3 * dz
          ):
            start = 16 * z + 4 * y + x
            mask = 0
            for t in range(4):
              c = start + t * stride
              mask |= 1 << c
            lines.append(mask)
            for t in range(4):
              c = start + t * stride
              cell_lines[c].append(mask)
  assert len(lines) == 76
  return tuple(lines), tuple(tuple(cl) for cl in cell_lines)


WIN_LINES, CELL_LINES = _build_win_lines()


def _swap_x03(b: int) -> int:
  t = ((b >> 3) ^ b) & 0x1111111111111111
  return b ^ t ^ (t << 3)


def _swap_x12(b: int) -> int:
  t = ((b >> 1) ^ b) & 0x2222222222222222
  return b ^ t ^ (t << 1)


def _swap_x01_23(b: int) -> int:
  t = ((b >> 1) ^ b) & 0x5555555555555555
  return b ^ t ^ (t << 1)


def _swap_y03(b: int) -> int:
  t = ((b >> 12) ^ b) & 0x000F000F000F000F
  return b ^ t ^ (t << 12)


def _swap_y12(b: int) -> int:
  t = ((b >> 4) ^ b) & 0x00F000F000F000F0
  return b ^ t ^ (t << 4)


def _swap_y01_23(b: int) -> int:
  t = ((b >> 4) ^ b) & 0x0F0F0F0F0F0F0F0F
  return b ^ t ^ (t << 4)


def _swap_z03(b: int) -> int:
  t = ((b >> 48) ^ b) & 0x000000000000FFFF
  return b ^ t ^ (t << 48)


def _swap_z12(b: int) -> int:
  t = ((b >> 16) ^ b) & 0x00000000FFFF0000
  return b ^ t ^ (t << 16)


def _swap_z01_23(b: int) -> int:
  t = ((b >> 16) ^ b) & 0x0000FFFF0000FFFF
  return b ^ t ^ (t << 16)


def _flip_y(b: int) -> int:
  return _swap_y03(_swap_y12(b))


def _flip_z(b: int) -> int:
  return _swap_z03(_swap_z12(b))


def _transpose_xy(b: int) -> int:
  t1 = ((b >> 3) ^ b) & 0x0A0A0A0A0A0A0A0A
  b ^= t1 ^ (t1 << 3)
  t2 = ((b >> 6) ^ b) & 0x00CC00CC00CC00CC
  b ^= t2 ^ (t2 << 6)
  return b


def _transpose_yz(b: int) -> int:
  t1 = ((b >> 12) ^ b) & 0x0000F0F00000F0F0
  b ^= t1 ^ (t1 << 12)
  t2 = ((b >> 24) ^ b) & 0x00000000FF00FF00
  b ^= t2 ^ (t2 << 24)
  return b


def _apply_axis_perm(b: int, ap: int) -> int:
  if ap == 0:
    return b
  if ap == 1:
    return _transpose_yz(b)
  if ap == 2:
    return _transpose_xy(b)
  if ap == 3:
    return _transpose_yz(_transpose_xy(b))
  if ap == 4:
    return _transpose_xy(_transpose_yz(b))
  return _transpose_xy(_transpose_yz(_transpose_xy(b)))


def _apply_coord_b(b: int, code: int) -> int:
  if code & 1:
    b = _swap_x03(_swap_y03(_swap_z03(b)))
  if code & 2:
    b = _swap_x12(_swap_y12(_swap_z12(b)))
  if code & 4:
    b = _swap_x01_23(_swap_y01_23(_swap_z01_23(b)))
  return b


def _build_sym_cell_bit_tables() -> Tuple[Tuple[int, ...], ...]:
  """Precomputes (1 << sym(c)) for each of the 192 symmetries and 64 cells."""
  c_s4 = [[0] * 4 for _ in range(8)]
  for b in range(8):
    for i in range(4):
      v = i
      if (b & 1) and (v == 0 or v == 3):
        v ^= 3
      if (b & 2) and (v == 1 or v == 2):
        v ^= 3
      if b & 4:
        v ^= 1
      c_s4[b][i] = v

  axis_perms = (
      (0, 1, 2),
      (0, 2, 1),
      (1, 0, 2),
      (1, 2, 0),
      (2, 0, 1),
      (2, 1, 0),
  )
  tables: List[Tuple[int, ...]] = []
  for ap in range(6):
    ax0, ax1, ax2 = axis_perms[ap]
    for b in range(8):
      cb = c_s4[b]
      for fy in range(2):
        for fz in range(2):
          row: List[int] = []
          for c in range(64):
            coords = (c & 3, (c >> 2) & 3, (c >> 4) & 3)
            nx = cb[coords[ax0]]
            ny = cb[coords[ax1]]
            nz = cb[coords[ax2]]
            if fy:
              ny = 3 - ny
            if fz:
              nz = 3 - nz
            nc = (nz << 4) | (ny << 2) | nx
            row.append(1 << nc)
          tables.append(tuple(row))
  assert len(tables) == 192
  return tuple(tables)


SYM_CELL_BITS = _build_sym_cell_bit_tables()


def all_192_transforms(b: int) -> List[int]:
  """Returns the 192 symmetry images of bitboard `b` in canonical sym_id order."""
  res: List[int] = []
  for ap in range(6):
    ab = _apply_axis_perm(b, ap)
    for code in range(8):
      cb = _apply_coord_b(ab, code)
      cb_fy = _flip_y(cb)
      res.append(cb)
      res.append(_flip_z(cb))
      res.append(cb_fy)
      res.append(_flip_z(cb_fy))
  return res


def canonicalize(p1: int, p2: int) -> Tuple[int, int]:
  """Returns the canonical (cp1, cp2) bitboard pair under the 192 symmetries."""
  best_p1 = p1
  best_p2 = p2
  for ap in range(6):
    ap1 = _apply_axis_perm(p1, ap)
    ap2 = _apply_axis_perm(p2, ap)
    for code in range(8):
      cp1 = _apply_coord_b(ap1, code)
      cp2 = _apply_coord_b(ap2, code)
      for fy in range(2):
        yp1 = _flip_y(cp1) if fy else cp1
        yp2 = _flip_y(cp2) if fy else cp2
        for fz in range(2):
          zp1 = _flip_z(yp1) if fz else yp1
          if zp1 > best_p1:
            continue
          zp2 = _flip_z(yp2) if fz else yp2
          if zp1 < best_p1 or zp2 < best_p2:
            best_p1 = zp1
            best_p2 = zp2
  return best_p1, best_p2


def has_won(p: int) -> bool:
  """Returns True if bitboard `p` contains any 4-in-a-row line."""
  if p.bit_count() < 4:
    return False
  for mask in WIN_LINES:
    if (p & mask) == mask:
      return True
  return False


def winning_moves(p: int, occ: int) -> int:
  """Returns bitmask of empty cells that immediately complete 4-in-a-row for `p`."""
  if p.bit_count() < 3:
    return 0
  empty = (~occ) & MASK64
  wins = 0
  for mask in WIN_LINES:
    rem = mask & ~p
    if rem and (rem & (rem - 1)) == 0 and (rem & empty):
      wins |= rem
  return wins


CELL_CHARS = "0123456789#$ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
assert len(CELL_CHARS) == 64
CHAR_TO_CELL: Dict[str, int] = {ch: idx for idx, ch in enumerate(CELL_CHARS)}


def format_board(p: int, o: int) -> str:
  """Formats (p, o) bitboards as alternating Prover/Disprover cell chars."""
  p_cells = [c for c in range(64) if (p >> c) & 1]
  o_cells = [c for c in range(64) if (o >> c) & 1]
  if len(p_cells) not in (len(o_cells), len(o_cells) + 1):
    raise ValueError(
        f"Invalid stone counts for alternating board: |X|={len(p_cells)},"
        f" |O|={len(o_cells)}."
    )
  out: List[str] = []
  for i in range(max(len(p_cells), len(o_cells))):
    if i < len(p_cells):
      out.append(CELL_CHARS[p_cells[i]])
    if i < len(o_cells):
      out.append(CELL_CHARS[o_cells[i]])
  return "".join(out)


def parse_board(board_str: str) -> Tuple[int, int]:
  """Parses an alternating Prover/Disprover cell string into (p, o) bitboards."""
  p = 0
  o = 0
  for idx, ch in enumerate(board_str):
    if ch not in CHAR_TO_CELL:
      raise ValueError(f"Invalid cell character {ch!r} in board {board_str!r}.")
    bit = 1 << CHAR_TO_CELL[ch]
    if (p | o) & bit:
      raise ValueError(f"Duplicate cell character {ch!r} in board {board_str!r}.")
    if idx % 2 == 0:
      p |= bit
    else:
      o |= bit
  return p, o


def format_move(cell: int) -> str:
  """Formats cell index 0..63 as a single character from CELL_CHARS."""
  if cell < 0 or cell >= 64:
    raise ValueError(f"Cell index out of range: {cell}")
  return CELL_CHARS[cell]


def parse_move(move_str: str) -> int:
  """Parses a single-character move string into cell index 0..63."""
  if len(move_str) == 1 and move_str in CHAR_TO_CELL:
    return CHAR_TO_CELL[move_str]
  raise ValueError(
      f"Expected single-character move in CELL_CHARS, got {move_str!r}."
  )


@dataclasses.dataclass
class CertificateNode:
  move: int
  refutations: List[List[int]] = dataclasses.field(default_factory=list)


def advance_forced_threat_sequence(
    p_start: int, o_start: int, seq: List[int]
) -> Tuple[bool, bool, int, int]:
  """Advances a forced-threat sequence from (p_start, o_start).

  Returns:
    (valid, is_terminal_win, end_p, end_o):
      - valid: True if every move in `seq` is a legal forcing move.
      - is_terminal_win: True if the final move completes 4-in-a-row or creates
        a double threat; False if the final move creates a single threat whose
        forced Disprover block leads to Prover-turn state (end_p, end_o).
  """
  if not seq:
    return False, False, 0, 0
  p = p_start
  o = o_start
  for step, m in enumerate(seq):
    if m < 0 or m >= 64:
      return False, False, 0, 0
    occ = p | o
    if (occ >> m) & 1:
      return False, False, 0, 0
    p_next = p | (1 << m)
    if has_won(p_next):
      if step + 1 == len(seq):
        return True, True, p_next, o
      return False, False, 0, 0
    occ_next = p_next | o
    opp_wins = winning_moves(o, occ)
    if (opp_wins & ~(1 << m)) != 0:
      return False, False, 0, 0
    p = p_next
    occ = occ_next
    p_wins = winning_moves(p, occ)
    p_win_cnt = p_wins.bit_count()
    if step + 1 == len(seq):
      if p_win_cnt >= 2:
        return True, True, p, o
      if p_win_cnt == 1:
        r = (p_wins & -p_wins).bit_length() - 1
        o |= 1 << r
        if has_won(o):
          return False, False, 0, 0
        return True, False, p, o
      return False, False, 0, 0
    if p_win_cnt != 1:
      return False, False, 0, 0
    r = (p_wins & -p_wins).bit_length() - 1
    o |= 1 << r
    if has_won(o):
      return False, False, 0, 0
  return False, False, 0, 0


def verify_forced_threat_sequence(
    p_start: int, o_start: int, seq: List[int]
) -> bool:
  """Verifies that `seq` is a valid terminal forced-threat win from (p_start, o_start)."""
  valid, is_win, _, _ = advance_forced_threat_sequence(p_start, o_start, seq)
  return valid and is_win


@dataclasses.dataclass
class VerificationResult:
  ok: bool
  error_msg: str = ""
  certificate_rows: int = 0
  verified_prover_states: int = 0
  disprover_branches_checked: int = 0
  root_p: int = 0


def load_tsv_certificate(path: str) -> Dict[Tuple[int, int], CertificateNode]:
  """Loads a tab-separated '<board_state>\\t<move>[\\t<refutations>]' certificate."""
  cert: Dict[Tuple[int, int], CertificateNode] = {}
  with open(path, "r", encoding="utf-8") as f:
    for line_num, raw_line in enumerate(f, start=1):
      line = raw_line.rstrip("\r\n")
      if not line or line.startswith("//"):
        continue
      parts = line.split("\t")
      if len(parts) == 2:
        board_str, move_str = parts[0], parts[1]
        seqs_str = ""
      elif len(parts) == 3:
        board_str, move_str, seqs_str = parts[0], parts[1], parts[2]
      else:
        raise ValueError(
            f"Line {line_num}: expected 2 or 3 tab-separated columns, got"
            f" {len(parts)}."
        )
      p, o = parse_board(board_str)
      if p.bit_count() != o.bit_count() or p == 0:
        raise ValueError(
            f"Line {line_num}: expected non-empty Prover-turn board with"
            f" |X| == |O|, got {board_str!r}."
        )
      m = parse_move(move_str)
      refutations: List[List[int]] = []
      if seqs_str.strip():
        for raw_seq in seqs_str.split("|"):
          raw_seq = raw_seq.strip()
          if not raw_seq:
            continue
          moves = [parse_move(ch) for ch in raw_seq]
          if moves:
            refutations.append(moves)
      key = (p, o)
      if key in cert:
        raise ValueError(
            f"Line {line_num}: duplicate board state {board_str!r}."
        )
      cert[key] = CertificateNode(move=m, refutations=refutations)
  return cert


def _parse_opening_arg(opening_move: str) -> int:
  """Parses --opening argument as either a single cell char or 'x,y,z'."""
  if len(opening_move) == 1 and opening_move in CHAR_TO_CELL:
    return CHAR_TO_CELL[opening_move]
  parts = opening_move.split(",")
  if len(parts) == 3:
    x, y, z = int(parts[0]), int(parts[1]), int(parts[2])
    if _in_bounds(x, y, z):
      return (z << 4) | (y << 2) | x
  raise ValueError(f"Invalid opening move specification: {opening_move!r}")


def infer_opening_root_p(cert: Dict[Tuple[int, int], CertificateNode]) -> int:
  """Infers the canonical Move-1 bitboard mask (1='0', 2='1', 3=both '0'&'1')."""
  two_stone_ps = {
      p for (p, o) in cert if (p | o).bit_count() == 2 and p.bit_count() == 1
  }
  if not two_stone_ps:
    raise ValueError(
        "Could not infer opening move: no 2-stone states found in certificate."
    )
  mask = 0
  for p in two_stone_ps:
    mask |= p
  return mask


def verify_certificate(
    cert: Dict[Tuple[int, int], CertificateNode],
    opening_move: Optional[str] = None,
) -> VerificationResult:
  """Verifies a Qubic TSV proof certificate dictionary."""
  if not cert:
    return VerificationResult(ok=False, error_msg="Certificate is empty.")

  try:
    if opening_move is not None:
      raw_root_p = 1 << _parse_opening_arg(opening_move)
      root_p, _ = canonicalize(raw_root_p, 0)
    else:
      root_p = infer_opening_root_p(cert)
  except ValueError as e:
    return VerificationResult(ok=False, error_msg=str(e))

  verified: Set[Tuple[int, int]] = set()
  visiting: Set[Tuple[int, int]] = set()
  branches_checked = 0

  # Iterative DFS stack to avoid Python recursion limits on deep lines.
  # Stack entries: (cp, co, child_iter_list, next_child_idx)
  def get_child_states(
      cp: int, co: int
  ) -> Tuple[bool, str, List[Tuple[int, int]], int]:
    """Validates Prover's move at (cp, co) and returns canonical child states."""
    bkey = (cp, co)
    if bkey not in cert:
      return (
          False,
          f"Missing Prover state in certificate: {format_board(cp, co)}",
          [],
          0,
      )
    node = cert[bkey]
    m = node.move
    occ = cp | co
    if (occ >> m) & 1:
      return (
          False,
          (
              f"Illegal move {format_move(m)} on occupied cell at"
              f" {format_board(cp, co)}"
          ),
          [],
          0,
      )

    cp_next = cp | (1 << m)
    if has_won(cp_next):
      return True, "", [], 0

    occ_next = cp_next | co
    if winning_moves(co, occ_next) != 0:
      return (
          False,
          (
              f"Disprover has immediate 4-in-a-row after move {format_move(m)}"
              f" at {format_board(cp, co)}"
          ),
          [],
          0,
      )

    p_wins = winning_moves(cp_next, occ_next)
    p_win_cnt = p_wins.bit_count()
    if p_win_cnt >= 2:
      return True, "", [], 0

    if p_win_cnt == 1:
      d = (p_wins & -p_wins).bit_length() - 1
      co_next = co | (1 << d)
      if has_won(co_next):
        return False, "Disprover forced reply completes 4-in-a-row.", [], 1
      for seq in node.refutations:
        if verify_forced_threat_sequence(cp_next, co_next, seq):
          return True, "", [], 1
      ck = canonicalize(cp_next, co_next)
      if ck in cert:
        return True, "", [ck], 1
      for seq in node.refutations:
        valid, is_win, end_p, end_o = advance_forced_threat_sequence(
            cp_next, co_next, seq
        )
        if valid and not is_win:
          target_ck = canonicalize(end_p, end_o)
          if target_ck in cert:
            return True, "", [target_ck], 1
      return True, "", [ck], 1

    empty_mask = (~occ_next) & MASK64
    if empty_mask == 0:
      return False, f"Board full without win at {format_board(cp, co)}", [], 0

    # Fast exact canonicalization of (cp_next, co | (1 << d)) for all empty d:
    # Only symmetries g in G_192 that minimize g(cp_next) can minimize
    # (g(cp_next), g(co | (1 << d))).
    p_imgs = all_192_transforms(cp_next)
    min_p = min(p_imgs)
    o_imgs = all_192_transforms(co)
    min_syms = [
        (o_imgs[s], SYM_CELL_BITS[s]) for s in range(192) if p_imgs[s] == min_p
    ]

    orbit_moves: Dict[int, List[int]] = {}
    n_branches = 0
    rem = empty_mask
    while rem:
      lsb = rem & -rem
      rem ^= lsb
      d = lsb.bit_length() - 1
      n_branches += 1
      co_next = co | lsb
      if has_won(co_next):
        return (
            False,
            (
                f"Disprover reply {format_move(d)} completes 4-in-a-row at"
                f" {format_board(cp, co)}"
            ),
            [],
            n_branches,
        )

      if len(min_syms) == 1:
        g_co, sym_bits = min_syms[0]
        min_o = g_co | sym_bits[d]
      else:
        min_o = min(g_co | sym_bits[d] for g_co, sym_bits in min_syms)

      if min_o not in orbit_moves:
        orbit_moves[min_o] = [d]
      else:
        orbit_moves[min_o].append(d)

    children: List[Tuple[int, int]] = []
    for min_o, moves in orbit_moves.items():
      refuted = False
      if node.refutations:
        for d in moves:
          co_d = co | (1 << d)
          for seq in node.refutations:
            if verify_forced_threat_sequence(cp_next, co_d, seq):
              refuted = True
              break
          if refuted:
            break
      if refuted:
        continue
      ck = (min_p, min_o)
      if ck in cert:
        children.append(ck)
        continue
      if node.refutations:
        for d in moves:
          co_d = co | (1 << d)
          for seq in node.refutations:
            valid, is_win, end_p, end_o = advance_forced_threat_sequence(
                cp_next, co_d, seq
            )
            if valid and not is_win:
              target_ck = canonicalize(end_p, end_o)
              if target_ck in cert:
                children.append(target_ck)
                refuted = True
                break
          if refuted:
            break
      if not refuted:
        children.append(ck)

    return True, "", children, n_branches

  # Collect all canonical Move-2 states after Disprover replies to each opening
  # bit in root_p.
  root_children: List[Tuple[int, int]] = []
  seen_root_children: Set[Tuple[int, int]] = set()
  rem_roots = root_p
  while rem_roots:
    single_root_p = rem_roots & -rem_roots
    rem_roots ^= single_root_p
    for d in range(64):
      if (single_root_p >> d) & 1:
        continue
      branches_checked += 1
      ck = canonicalize(single_root_p, 1 << d)
      if ck not in seen_root_children:
        seen_root_children.add(ck)
        root_children.append(ck)

  for root_ck in root_children:
    if root_ck in verified:
      continue
    ok, err, ch_list, nb = get_child_states(root_ck[0], root_ck[1])
    branches_checked += nb
    if not ok:
      return VerificationResult(
          ok=False,
          error_msg=err,
          certificate_rows=len(cert),
          verified_prover_states=len(verified),
          disprover_branches_checked=branches_checked,
          root_p=root_p,
      )
    if not ch_list:
      verified.add(root_ck)
      continue

    visiting.add(root_ck)
    stack: List[ List[object] ] = [[root_ck, ch_list, 0]]
    while stack:
      top = stack[-1]
      cur_key: Tuple[int, int] = top[0]  # type: ignore[assignment]
      cur_children: List[Tuple[int, int]] = top[1]  # type: ignore[assignment]
      idx: int = top[2]  # type: ignore[assignment]

      if idx >= len(cur_children):
        visiting.remove(cur_key)
        verified.add(cur_key)
        stack.pop()
        continue

      nxt_key = cur_children[idx]
      top[2] = idx + 1
      if nxt_key in verified:
        continue
      if nxt_key in visiting:
        return VerificationResult(
            ok=False,
            error_msg=f"Cycle detected at {format_board(nxt_key[0], nxt_key[1])}",
            certificate_rows=len(cert),
            verified_prover_states=len(verified),
            disprover_branches_checked=branches_checked,
            root_p=root_p,
        )

      ok, err, nxt_children, nb = get_child_states(nxt_key[0], nxt_key[1])
      branches_checked += nb
      if not ok:
        return VerificationResult(
            ok=False,
            error_msg=err,
            certificate_rows=len(cert),
            verified_prover_states=len(verified),
            disprover_branches_checked=branches_checked,
            root_p=root_p,
        )
      if not nxt_children:
        verified.add(nxt_key)
      else:
        visiting.add(nxt_key)
        stack.append([nxt_key, nxt_children, 0])

  return VerificationResult(
      ok=True,
      error_msg="",
      certificate_rows=len(cert),
      verified_prover_states=len(verified),
      disprover_branches_checked=branches_checked,
      root_p=root_p,
  )


def main(argv: List[str]) -> int:
  opening_move: Optional[str] = None
  paths: List[str] = []
  i = 1
  while i < len(argv):
    if argv[i] == "--opening" and i + 1 < len(argv):
      opening_move = argv[i + 1]
      i += 2
    else:
      paths.append(argv[i])
      i += 1

  if not paths:
    sys.stderr.write(
        "Usage: qubic_verifier.py [--opening x,y,z] <cert1.tsv> [cert2.tsv ...]\n"
    )
    return 2

  for path in paths:
    t0 = time.monotonic()
    try:
      cert = load_tsv_certificate(path)
    except Exception as e:  # pylint: disable=broad-exception-caught
      sys.stderr.write(f"[FAIL] {path}: failed to load TSV ({e})\n")
      return 1
    t1 = time.monotonic()
    res = verify_certificate(cert, opening_move=opening_move)
    t2 = time.monotonic()
    load_ms = (t1 - t0) * 1000.0
    verify_ms = (t2 - t1) * 1000.0
    if not res.ok:
      sys.stderr.write(
          f"[FAIL] {path}: {res.error_msg} (rows={res.certificate_rows},"
          f" verified={res.verified_prover_states})\n"
      )
      return 1
    openings_str = ",".join(
        format_move(c) for c in range(64) if (res.root_p >> c) & 1
    )
    print(
        f"[PASS] {path}\n"
        f"  opening_move={openings_str}\n"
        f"  certificate_rows={res.certificate_rows}"
        f" verified_prover_states={res.verified_prover_states}\n"
        f"  disprover_branches={res.disprover_branches_checked}\n"
        f"  time: load={load_ms:.1f}ms, verify={verify_ms:.1f}ms"
    )
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv))
