---
name: new-project
description: Шинэ эсвэл GitHub-тай холбогдоогүй төслийг GitHub (private repo)-тай холбож, .gitignore, алхам хадгалах tools/checkpoint.sh, CLAUDE.md тохируулна. Хэрэглэгч шинэ төсөл эхлүүлэх, төслөө GitHub-д хадгалах, D диск дээрх төслийг хамгаалах гэвэл, эсвэл .git-гүй хавтсанд ажиллаж эхлэхэд ашиглана.
---

# Шинэ төсөл тохируулах

1. Төслийн хавтсыг тодорхойлно (заагаагүй бол одоогийн хавтас).
2. Төрлийг сонгоно: `tts` (дуу хоолой/машин сургалт), `python`, `node`, `flutter`, `general`.
   Мэдэхгүй бол `--type`-ийг орхиж скриптэд таниулна.
3. Ажиллуулна:

   ```bash
   bash ~/project-toolkit/tools/new-project.sh "<хавтас>" --type <төрөл>
   ```

   `~/project-toolkit` байхгүй бол эхлээд:

   ```bash
   git clone https://github.com/amgalan81mn/amgalan81mn.git ~/project-toolkit
   ```

4. Гаралтыг уншина:
   - "GitHub repo холбогдоогүй" гэвэл хэрэглэгчид `gh auth login` хийх, эсвэл github.com/new дээр private repo үүсгэхийг монголоор, алхам алхмаар тайлбарлана.
   - "ТОМ ФАЙЛ" гэвэл тэр файлыг `.gitignore`-д нэмээд дахин ажиллуулна. Файлыг Google Drive-д нөөцлөхийг хэрэглэгчид сануулна.
5. Хэрэглэгчид товч мэдэгдэнэ: repo-гийн холбоос, юу хийгдсэн, цаашид алхам бүрт
   `tools/checkpoint.sh save "..."` хийгдэнэ гэдгийг.
