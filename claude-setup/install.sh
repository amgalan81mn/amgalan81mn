#!/usr/bin/env bash
# Компьютер дээрээ НЭГ УДАА ажиллуулна (Windows: Git Bash). Үүний дараа Claude
# шинэ төсөл бүрийг автоматаар GitHub-тай холбож, алхам бүрийг хадгалдаг болно.
#
#   curl -fsSL https://raw.githubusercontent.com/amgalan81mn/amgalan81mn/main/claude-setup/install.sh | bash
set -euo pipefail
TK="$HOME/project-toolkit"
REPO="https://github.com/amgalan81mn/amgalan81mn.git"

# 1. Хэрэгслүүдийг татах / шинэчлэх
if [ -d "$TK/.git" ]; then git -C "$TK" pull -q --ff-only origin main; else git clone -q -b main "$REPO" "$TK"; fi
echo "▶ Хэрэгслүүд: $TK"

# 2. Claude-ийн байнгын дүрэм (~/.claude/CLAUDE.md) — өмнөх дүрмийг устгахгүй, өөрийн хэсгийг л солино
mkdir -p "$HOME/.claude"
g="$HOME/.claude/CLAUDE.md"; touch "$g"
sed -i.bak '/<!-- project-toolkit:start -->/,/<!-- project-toolkit:end -->/d' "$g" && rm -f "$g.bak"
{ [ -n "$(tail -n1 "$g")" ] && echo; cat "$TK/claude-setup/global-CLAUDE.md"; } >>"$g"
echo "▶ Claude-ийн дүрэм: $g"

# 3. /new-project skill
mkdir -p "$HOME/.claude/skills/new-project"
cp "$TK/claude-setup/skills/new-project/SKILL.md" "$HOME/.claude/skills/new-project/SKILL.md"
echo "▶ /new-project skill суулаа"

# 4. Шалгах
command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
  && echo "▶ GitHub CLI (gh) нэвтэрсэн: repo автоматаар үүснэ" \
  || echo "⚠ GitHub CLI (gh) алга эсвэл нэвтрээгүй. https://cli.github.com суулгаад 'gh auth login' хийвэл repo автоматаар үүснэ."
echo "✅ Дууслаа. Шинэ төсөл: Claude-д \"/new-project\" гэж бичих, эсвэл:"
echo "   bash ~/project-toolkit/tools/new-project.sh /d/ТӨСӨЛ --type tts"
