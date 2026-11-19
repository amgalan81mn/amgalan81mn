#!/usr/bin/env bash
# Алхам хадгалах, сэргээх хэрэгсэл (TTS гэх мэт олон файлтай төсөлд).
#
#   tools/checkpoint.sh save "Юу хийснээ бичнэ"   алхмаа хадгалж GitHub руу илгээнэ (step-001, step-002 ...)
#   tools/checkpoint.sh list                      хадгалсан алхмуудыг харуулна
#   tools/checkpoint.sh show step-003             тухайн алхамд юу өөрчлөгдсөнийг харуулна
#   tools/checkpoint.sh restore step-003          бүх төслийг тэр алхмаар шинэ branch дээр сэргээнэ
#   tools/checkpoint.sh restore step-003 зам...   зөвхөн заасан файл/хавтсыг тэр алхмаар сэргээнэ
#   tools/checkpoint.sh verify                    git-д ороогүй том файлууд (загвар, өгөгдөл) бүрэн эсэхийг шалгана
#
# Windows дээр "Git Bash"-аар ажиллуулна.
set -euo pipefail

BIG_LIMIT_MB="${BIG_LIMIT_MB:-50}"           # үүнээс том файлыг git-д оруулахгүй
MANIFEST=".checkpoint/large-files.tsv"       # том файлуудын жагсаалт, хэмжээ, sha256

die() { echo "Алдаа: $*" >&2; exit 1; }
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || die "git repo дотор ажиллуулна уу"

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
fsize() { wc -c <"$1" | tr -d ' '; }

push_retry() {
  local i
  for i in 1 2 3 4; do git push "$@" && return 0; echo "push амжилтгүй, дахин оролдоно ($i)..."; sleep $((2 ** i)); done
  die "GitHub руу илгээж чадсангүй. Интернэтээ шалгаад 'git push --follow-tags' дахин ажиллуулна уу. Алхам компьютер дээр хадгалагдсан."
}

write_manifest() {
  # git-д ороогүй (ignore хийсэн) файлуудын жагсаалт: дараа нь бусад газраас (Drive, HF Hub) сэргээхэд хэрэгтэй
  mkdir -p .checkpoint
  { printf 'size\tsha256\tpath\n'
    git ls-files --others --ignored --exclude-standard -z \
      | while IFS= read -r -d '' f; do
          case "$f" in .venv/*|venv/*|*/__pycache__/*|node_modules/*|*/node_modules/*|.git/*) continue;; esac
          [ -f "$f" ] || continue
          [ "$(fsize "$f")" -ge $((1024 * 1024)) ] || continue   # 1MB-аас доош бол алгасна
          printf '%s\t%s\t%s\n' "$(fsize "$f")" "$(sha "$f")" "$f"
        done | sort -t$'\t' -k3
  } >"$MANIFEST"
}

check_big_staged() {
  local limit=$((BIG_LIMIT_MB * 1024 * 1024)) bad=0 f
  while IFS= read -r -d '' f; do
    [ -f "$f" ] || continue
    if [ "$(fsize "$f")" -gt "$limit" ]; then echo "  ТОМ ФАЙЛ: $f ($(( $(fsize "$f") / 1024 / 1024 ))MB)"; bad=1; fi
  done < <(git diff --cached --name-only -z --diff-filter=AM)
  if [ $bad = 1 ]; then
    git reset -q
    die "${BIG_LIMIT_MB}MB-аас том файл байна. .gitignore-д нэмээд (загвар, аудио, датасет) Drive/HF Hub-д хадгална уу."
  fi
}

next_step() {
  local last
  last=$(git tag -l 'step-*' | sed 's/^step-//' | sort -n | tail -1)
  printf 'step-%03d' $(( 10#${last:-0} + 1 ))
}

cmd="${1:-}"; shift || true
case "$cmd" in
  save)
    msg="${1:-}"; [ -n "$msg" ] || die 'тайлбар бичнэ үү: tools/checkpoint.sh save "Юу хийсэн"'
    write_manifest
    git add -A
    check_big_staged
    step=$(next_step)
    if git diff --cached --quiet; then echo "Шинэ өөрчлөлт алга. Сүүлийн commit-д $step тэмдэг тавина."
    else git commit -q -m "$step: $msg"; fi
    git tag -a "$step" -m "$msg"
    branch=$(git rev-parse --abbrev-ref HEAD)
    push_retry -u origin "$branch" "refs/tags/$step"
    echo "✅ $step хадгалагдаж GitHub руу илгээгдлээ: $msg"
    ;;
  list)
    git tag -l 'step-*' --sort=v:refname --format='%(refname:short)  %(creatordate:short)  %(contents:subject)'
    ;;
  show)
    [ -n "${1:-}" ] || die "алхмын нэр: tools/checkpoint.sh show step-003"
    git show --stat "$1"
    ;;
  restore)
    step="${1:-}"; [ -n "$step" ] || die "алхмын нэр: tools/checkpoint.sh restore step-003 [файл...]"
    shift
    git rev-parse -q --verify "refs/tags/$step" >/dev/null || git fetch -q origin "refs/tags/$step:refs/tags/$step" || die "$step олдсонгүй"
    if [ $# -gt 0 ]; then
      git checkout "$step" -- "$@"
      echo "✅ $* -> $step хувилбараар сэргээгдлээ. Шалгаад зөв бол: tools/checkpoint.sh save \"$step-аас сэргээв\""
    else
      git diff --quiet && git diff --cached --quiet || die "хадгалаагүй өөрчлөлт байна. Эхлээд save хийнэ үү (эсвэл зөвхөн файл заан сэргээнэ үү)"
      git switch -c "restore-$step-$(date +%Y%m%d%H%M%S)" "$step"
      echo "✅ Төсөл $step хувилбараар шинэ branch дээр сэргээгдлээ. Хуучин ажил устаагүй."
      echo "   Том файлуудыг шалгах: tools/checkpoint.sh verify"
    fi
    ;;
  verify)
    [ -f "$MANIFEST" ] || die "$MANIFEST алга (save хийгээгүй байна)"
    missing=0
    while IFS=$'\t' read -r size hash path; do
      [ "$size" = size ] && continue
      if [ ! -f "$path" ]; then echo "  АЛГА:     $path"; missing=1
      elif [ "$(sha "$path")" != "$hash" ]; then echo "  ӨӨР:      $path (агуулга өөрчлөгдсөн)"; missing=1
      fi
    done <"$MANIFEST"
    [ $missing = 0 ] && echo "✅ Бүх том файл байрандаа, бүрэн." || echo "Дээрх файлуудыг Drive/HF Hub нөөцөөсөө буцааж хуулна уу."
    ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
