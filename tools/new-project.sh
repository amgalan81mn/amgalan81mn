#!/usr/bin/env bash
# Шинэ (эсвэл одоо байгаа) төслийг нэг командаар GitHub-тай холбож, алхам хадгалах тохиргоо хийнэ.
#
#   new-project.sh [хавтас] [--type tts|python|node|flutter|general] [--name repo-нэр] [--no-github]
#
# Жишээ (Windows, Git Bash):
#   new-project.sh /d/TTS --type tts
#   new-project.sh .                       # одоогийн хавтас, төрлийг автоматаар таньна
#
# Юу хийх вэ:
#   1. git init (branch: main)
#   2. Төслийн төрөлд тохирсон .gitignore (нууц, том файл, орчныг GitHub-д оруулахгүй)
#   3. tools/checkpoint.sh — алхам хадгалах, сэргээх хэрэгсэл
#   4. CLAUDE.md — Claude-д зориулсан дүрэм (алхам бүрийг хадгалах, монголоор)
#   5. TTS бол СУРГАЛТ.md — сургалтын жорын загвар
#   6. GitHub дээр private repo үүсгэж холбоно ("gh" суусан бол)
#   7. Анхны алхмыг (step-001) хадгалж GitHub руу илгээнэ
#
# Дахин ажиллуулахад аюулгүй: байгаа файлыг дарж бичихгүй.
set -euo pipefail

TOOLKIT_RAW="${TOOLKIT_RAW:-https://raw.githubusercontent.com/amgalan81mn/amgalan81mn/main}"
GITHUB_OWNER="${GITHUB_OWNER:-amgalan81mn}"

die() { echo "Алдаа: $*" >&2; exit 1; }
say() { echo "▶ $*"; }

dir="."; type=""; name=""; github=1
while [ $# -gt 0 ]; do
  case "$1" in
    --type) type="${2:-}"; shift 2 ;;
    --name) name="${2:-}"; shift 2 ;;
    --no-github) github=0; shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) dir="$1"; shift ;;
  esac
done

# Загваруудыг энэ скриптийн хажуугийн хавтаснаас, байхгүй бол GitHub-аас авна
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
toolkit=""
[ -n "$here" ] && [ -d "$here/../templates" ] && toolkit="$(cd "$here/.." && pwd)"
fetch() { # fetch <toolkit дахь зам> <хадгалах газар>
  if [ -n "$toolkit" ]; then cp "$toolkit/$1" "$2"
  else curl -fsSL "$TOOLKIT_RAW/$1" -o "$2" || die "$1 татаж чадсангүй"; fi
}

mkdir -p "$dir" && cd "$dir"
[ -n "$name" ] || name="$(basename "$(pwd)" | tr '[:upper:] ' '[:lower:]-')"

# Төрлийг автоматаар таних
if [ -z "$type" ]; then
  if ls ./*.pth ./*.ckpt configs 2>/dev/null | grep -q . || grep -rqiE 'tts|vits|tacotron|piper|coqui' --include='*.py' --include='*.txt' --include='*.yaml' . 2>/dev/null; then type=tts
  elif [ -f pubspec.yaml ]; then type=flutter
  elif [ -f package.json ]; then type=node
  elif ls ./*.py requirements*.txt pyproject.toml 2>/dev/null | grep -q .; then type=python
  else type=general; fi
fi
case "$type" in tts|python|node|flutter|general) ;; *) die "--type: tts, python, node, flutter, general-ийн нэг" ;; esac
say "Төсөл: $(pwd)  (төрөл: $type, repo: $name)"

# 1. git
if [ ! -d .git ]; then git init -q -b main 2>/dev/null || { git init -q; git checkout -q -b main; }; say "git init"; fi

# 2. .gitignore — байгаа мөрүүдийг давтахгүйгээр нэмнэ
parts="base"
case "$type" in tts) parts="base python tts" ;; python) parts="base python" ;; node) parts="base node" ;; flutter) parts="base flutter" ;; esac
tmp="$(mktemp)"; touch .gitignore
for p in $parts; do
  fetch "templates/gitignore/$p.gitignore" "$tmp"
  added=0
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    grep -qxF -- "$line" .gitignore || { [ $added = 0 ] && printf '\n# --- %s ---\n' "$p" >>.gitignore; echo "$line" >>.gitignore; added=1; }
  done <"$tmp"
done
rm -f "$tmp"; say ".gitignore ($parts)"

# 3. checkpoint.sh — байнга шинэ хувилбар
mkdir -p tools
fetch tools/checkpoint.sh tools/checkpoint.sh && chmod +x tools/checkpoint.sh
say "tools/checkpoint.sh"

# 4. CLAUDE.md
if [ ! -f CLAUDE.md ]; then
  cat >CLAUDE.md <<EOF
# CLAUDE.md

## Дүрэм
- Хэрэглэгчтэй монгол хэлээр харилцана.
- Эх код, баримт бичиг бүгд GitHub дээр хадгалагдана. Компьютерийн диск эвдэрч болзошгүй.
- Ажлын алхам бүр дуусахад: \`tools/checkpoint.sh save "юу хийснийг товч"\`
  (commit + step-NNN tag + GitHub руу push). Push амжилттай болсныг шалгана.
- 50MB-аас том файл (загварын жин, аудио, датасет) git-д оруулахгүй, .gitignore-д нэмнэ.
- Нууц үг, токен, .env-ийг хэзээ ч commit хийхгүй.
- Алдсан/эвдэрсэн үед: \`tools/checkpoint.sh list\`, \`restore step-NNN [файл]\`, \`verify\`.
EOF
  [ "$type" = tts ] && cat >>CLAUDE.md <<'EOF'
- Сургалтын алхам бүрийг (команд, тохиргоо, seed, үр дүн, step-NNN) `СУРГАЛТ.md`-д бичнэ.
  Тохиргоо, seed-ийг `configs/*.yaml` файлд бичнэ, командын мөрөнд биш.
EOF
  say "CLAUDE.md"
fi

# 5. TTS сургалтын жор
if [ "$type" = tts ] && [ ! -f СУРГАЛТ.md ]; then fetch templates/tts/СУРГАЛТ.md СУРГАЛТ.md; say "СУРГАЛТ.md"; fi

# 6. GitHub repo
if ! git remote get-url origin >/dev/null 2>&1; then
  if [ $github = 1 ] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh repo view "$GITHUB_OWNER/$name" >/dev/null 2>&1; then
      git remote add origin "https://github.com/$GITHUB_OWNER/$name.git"
    else
      gh repo create "$GITHUB_OWNER/$name" --private --source . --remote origin >/dev/null
    fi
    say "GitHub: https://github.com/$GITHUB_OWNER/$name (private)"
  else
    echo
    echo "⚠ GitHub repo холбогдоогүй байна. Хоёр аргын нэгээр:"
    echo "   a) gh суулгаад (https://cli.github.com) 'gh auth login' хийгээд энэ скриптийг дахин ажиллуулна."
    echo "   b) github.com/new дээр '$name' нэртэй PRIVATE repo үүсгээд:"
    echo "      git remote add origin https://github.com/$GITHUB_OWNER/$name.git"
    echo "      tools/checkpoint.sh save \"Төсөл эхлэв\""
    exit 0
  fi
fi

# 7. Анхны алхам
if git tag -l 'step-*' | grep -q .; then
  say "Өмнө нь хадгалсан алхам байна. Шинэ өөрчлөлтийг хадгалж байна."
  git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ] || tools/checkpoint.sh save "Хадгалах тохиргоо шинэчлэв"
else
  tools/checkpoint.sh save "Төсөл GitHub-тай холбогдож, алхам хадгалах тохиргоо хийгдэв"
fi
echo "✅ Бэлэн. Цаашид алхам бүрийн төгсгөлд: tools/checkpoint.sh save \"юу хийсэн\""
