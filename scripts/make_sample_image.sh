#!/usr/bin/env bash
# Build a small ext4 image, put files on it, delete them, and leave the image
# behind. No root, no mounting, no loop devices: everything goes through
# mkfs.ext4 + debugfs, which is also why this is reproducible in CI.
#
#   ./scripts/make_sample_image.sh --photos ~/Pictures/holiday --out sample/ghost.img
#   ./scripts/make_sample_image.sh                  # generates placeholder photos
#
# Then:
#   PYTHONPATH=src .venv/bin/python -m palimpsest run sample/ghost.img --out out
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/sample/ghost.img"
SIZE_MB=128
PHOTOS=""
FS="ext4"
SIMULATE_LOSS=2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --photos) PHOTOS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --size) SIZE_MB="$2"; shift 2 ;;
    --fs) FS="$2"; shift 2 ;;
    --simulate-loss) SIMULATE_LOSS="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for tool in mkfs.ext4 debugfs fls icat; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/photos"

if [[ -n "$PHOTOS" ]]; then
  [[ -d "$PHOTOS" ]] || { echo "not a directory: $PHOTOS" >&2; exit 1; }
  echo "using photos from $PHOTOS"
  copied=0
  while IFS= read -r f; do
    cp "$f" "$WORK/photos/"
    copied=$((copied + 1))
    [[ $copied -ge 12 ]] && break
  done < <(find "$PHOTOS" -maxdepth 2 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) -print)
else
  echo "no --photos given; generating placeholders (no personal data involved)"
  python3 "$ROOT/scripts/gen_photos.py" "$WORK/photos"
fi

if ! find "$WORK/photos" -maxdepth 1 -type f -print -quit | grep -q .; then
  echo "no usable photos found; generating placeholders"
  python3 "$ROOT/scripts/gen_photos.py" "$WORK/photos"
fi

# The letter is the emotional payload of the demo: a real document, deleted,
# recovered with its text intact.
cat > "$WORK/letter.txt" <<'EOF'
Mum,

I found the box of photographs in the hall cupboard, the ones from the summer
we drove to the coast. I am keeping the one of you by the blue door.

I will come down on the 14th. Do not wait up.

— J.
EOF

cat > "$WORK/notes.md" <<'EOF'
# things to do before the move
- cancel the broadband
- box the books
- ask about the box in the loft
EOF

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
echo "creating ${SIZE_MB}MB ${FS} image at $OUT"
dd if=/dev/zero of="$OUT" bs=1M count="$SIZE_MB" status=none

if [[ "$FS" == "ext4" ]]; then
  mkfs.ext4 -q -F -L PALIMPSEST "$OUT"

  : > "$WORK/create.cmd"
  echo "mkdir /DCIM" >> "$WORK/create.cmd"
  echo "mkdir /Documents" >> "$WORK/create.cmd"
  echo "mkdir /Documents/2021" >> "$WORK/create.cmd"

  : > "$WORK/delete.cmd"
  for f in "$WORK"/photos/*; do
    [[ -e "$f" ]] || continue
    name="$(basename "$f")"
    echo "write $f /DCIM/$name" >> "$WORK/create.cmd"
    echo "rm /DCIM/$name" >> "$WORK/delete.cmd"
  done
  echo "write $WORK/letter.txt /Documents/2021/letter.txt" >> "$WORK/create.cmd"
  echo "rm /Documents/2021/letter.txt" >> "$WORK/delete.cmd"
  echo "write $WORK/notes.md /Documents/notes.md" >> "$WORK/create.cmd"

  debugfs -w -f "$WORK/create.cmd" "$OUT" >/dev/null 2>&1
  debugfs -w -f "$WORK/delete.cmd" "$OUT" >/dev/null 2>&1

  # Simulate a partial overwrite: the directory entry survives, the blocks do
  # not. These are the files the tool will report as "provably existed, gone".
  if [[ "$SIMULATE_LOSS" -gt 0 ]]; then
    mapfile -t LOSERS < <(fls -r -d -p "$OUT" | sed -n 's/.*\* \([0-9][0-9]*\):.*/\1/p' | head -n "$SIMULATE_LOSS")
    for ino in "${LOSERS[@]:-}"; do
      [[ -n "$ino" ]] && debugfs -w -R "set_inode_field <$ino> size 0" "$OUT" >/dev/null 2>&1 || true
    done
  fi

elif [[ "$FS" == "fat32" ]]; then
  for tool in mkfs.vfat mcopy mdel mmd; do
    command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
  done
  mkfs.vfat -F 32 -n PALIMPSEST "$OUT" >/dev/null
  mmd -i "$OUT" ::/DCIM ::/Documents ::/Documents/2021
  for f in "$WORK"/photos/*; do
    [[ -e "$f" ]] || continue
    mcopy -i "$OUT" "$f" ::/DCIM/
  done
  mcopy -i "$OUT" "$WORK/letter.txt" ::/Documents/2021/
  mcopy -i "$OUT" "$WORK/notes.md" ::/Documents/
  mdel -i "$OUT" "::/DCIM/*" 2>/dev/null || true
  mdel -i "$OUT" "::/Documents/2021/*" 2>/dev/null || true
else
  echo "unknown filesystem: $FS" >&2
  exit 2
fi

echo
echo "deleted entries still visible to the filesystem:"
fls -r -d -p "$OUT" | head -20
echo
echo "done. next:"
echo "  PYTHONPATH=src .venv/bin/python -m palimpsest run $OUT --out out"
