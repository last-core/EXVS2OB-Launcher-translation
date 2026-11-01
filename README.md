# EXVS2OB launcher — English translation patch

In-place English translation for the `EXVS2OB.exe` launcher (Gundam EXVS2 OverBoost
community launcher). The patch rewrites the launcher's own strings without changing
the file size, so every offset, heap and record table stays valid and the app runs
exactly as before — just in English.

* **Scope:** the launcher GUI: `#US` runtime strings (buttons, settings, dialogs,
  wizard pages, error messages, mobile-suit/series names, prefectures) and the
  compiled XAML (`BAML`) resources.
* **Not included:** the tutorial/wiki HTML pages under `Tools/wiki_data`, the
  screenshots in `Tools/tut_imgs`, and anything inside the game/PCB binaries.

Result for the tested build: **606 strings translated** (535 runtime + 70 XAML +
12 comment runs), 0 residual Chinese, identical file size.

---

## Repository layout

```
translation-patch/
├── patch.py                  # CLI: scan / patch / verify
├── exvs2ob/
│   ├── pe.py                 # find appended .NET assemblies, CLI metadata, heaps
│   ├── usheap.py             # read/write the #US string heap (UTF-16)
│   ├── baml.py               # read/write BAML string literals (UTF-8)
│   └── pipeline.py           # patch/scan/verify orchestration
├── data/
│   ├── us.json               # runtime strings:  original -> English
│   ├── baml.json             # XAML strings:     original -> English
│   └── js_comments.json      # CJK runs inside the injected wiki-viewer JS
├── tools/gen_strings_md.py   # regenerates STRINGS.md from data/*.json
├── STRINGS.md                # full translation tables + byte budgets
└── README.md
```

Only the Python standard library is required (Python 3.9+).

---

## Usage

Put the repository next to the launcher (`EXVS2OB.exe`), then:

```bat
:: create a translated copy (the original is never modified)
python patch.py patch  --exe ..\EXVS2OB.exe --out ..\EXVS2OB_en.exe

:: check the result: size, residual Chinese, stray writes
python patch.py verify --src ..\EXVS2OB.exe --patched ..\EXVS2OB_en.exe

:: list every Chinese string the tables do not cover yet
python patch.py scan   --exe ..\EXVS2OB.exe --out scan.json
```

`patch` exits with code 1 when something is missing or a translation does not fit,
so it can be used in CI.

### What "verify" guarantees

| Check | Meaning |
|---|---|
| `same size` | output byte length equals the input |
| `residual CJK strings` = 0 | no ideographs/kana left in `#US` or BAML |
| `bytes changed outside known heaps` = 0 | nothing outside the two translated heaps was touched |
| `#US blobs` | heap walk is still consistent (1788 blobs in this build) |

---

## How the binary is structured

`EXVS2OB.exe` is a small native host (348,160 bytes) with a complete .NET (WPF)
assembly appended, plus three WebView2 assemblies. Two kinds of strings matter:

1. **`#US` heap (UTF-16)** — everything the C# code passes to the UI at runtime:
   button labels, settings text, dialogs, error messages, names, help pages.
   Each entry is:

   ```
   <ECMA-335 compressed length n> <UTF-16LE data, n-1 bytes> <flag byte>
   ```

2. **BAML (compiled XAML, UTF-8) inside `.g.resources`** — the strings baked into
   the windows at design time. Each literal is:

   ```
   <7-bit varint length> <UTF-8 text> 0x99 0xFD
   ```

Both are patched **in place and padded with spaces**, so each string keeps its exact
byte length. No length prefixes, heap sizes, resource tables or PE headers change.

> Note: the two heaps use *different* integer encodings (`#US` = ECMA-335 compressed
> int, BAML = 7-bit `Write7BitEncodedInt`). Getting this wrong makes the heap walk
> derail after the first string longer than 127 bytes — `usheap.decode_compressed_int`
> and `usheap.decode_7bit_int` implement both.

---

## Translation rules

### Budget

`STRINGS.md` lists the **budget** for every entry: the byte count available in the
original binary (UTF-16 bytes for `#US`, UTF-8 bytes for BAML). An English string must
encode to *at most* that size; the patcher right-pads with ASCII spaces.

Because the original text is mostly Chinese, budgets are tight: one Chinese character
costs 2 bytes (UTF-16) or 3 bytes (UTF-8), i.e. roughly one English character. Expect
to abbreviate. Examples of the compressed labels in this build: `AW` (away match),
`St` (standard), `T1`/`T2`/`T3` (team 1–3), `GCan2 (GVS)`.

If a translation is too long the tool prints:

```
'本地端口 …' -> 'Ports …' (112 > 104 bytes)
```

Shorten the English and re-run — nothing is written when a `too long` entry exists
for a string that is present in the binary.

### Rules of thumb

* Keep placeholders (`{0}`, `%s`) and file names (`server`, `card.ini`, `bngrw.dll`,
  `127.0.0.1:28080`) verbatim — the patcher verifies placeholders are preserved.
* Fragments matter: some entries are concatenated with values or with other strings
  (e.g. `"P 卡号: "` + number, `" (BOSS)"`, `"），如需联机…"`). Translation must keep the
  fragment's position in the sentence.
* Don't use full-width punctuation in the English; it wastes budget and is not
  needed. `pipeline.has_cjk()` treats ideographs and kana as untranslated, so CJK
  punctuation left in a value makes `patch` fail fast rather than ship a mixed string.
* Config files (`CLIENT/config.ini`, `PCB1/config.ini`) store only ASCII codes
  (`Mode = Client`, `SkipAll`, `Region = 1`), so translating the display strings cannot
  corrupt saved settings.

### Editing or adding translations

1. Edit `data/us.json`, `data/baml.json` or `data/js_comments.json`
   (format: `{"strings": {"original": "English"}}`).
2. `python patch.py patch …` then `python patch.py verify …`.
3. `python tools/gen_strings_md.py` to refresh the tables in `STRINGS.md`.

For a string that does not exist in the tables yet, `scan` gives you the exact source
text and the required size:

```json
{"text": "启动失败", "bytes": 8, "offset": "0x89d55"}
```

---

## How dependent is this on the exact EXE version?

**Short version:** the method is version-independent; the *data* is keyed to the text
of each string, so a new build will not be corrupted — it will simply report what is
still untranslated.

### What is discovered at runtime (nothing hard-coded)

* the offset of each appended PE image (MZ/PE scan),
* the CLI header, metadata root, `#US`/`#Strings`/`#Blob` streams (PE + CLI headers),
* the managed-resources directory and its size (CLI header).

An earlier iteration hard-coded `348160`/`67440`-style offsets. The current code has
none, so the same script works on differently sized builds.

### What stays version-dependent

| Assumption | If it breaks |
|---|---|
| Strings live in `#US` and BAML | `scan` shows fewer strings / `patch` reports untranslated entries. Common cause: the author switches to resource DLLs, resx, or inlined UTF-16 arrays. |
| BAML literal layout `<len><utf8>0x99 0xFD` | `scan` reports 0 BAML strings (the always-on verification catches it). Stable across .NET Framework 4.x WPF, may change with a different XAML compiler. |
| The launcher remains a .NET assembly appended to a native stub | `main_image()` raises "no embedded .NET assembly found" — packing/single-file bundling/compression would do this. |
| Same source text | Changed or reworded Chinese strings do not match the table: they are listed as untranslated instead of being silently mis-patched. |
| Same-length padding is acceptable | If a new version *shortens* strings, budgets shrink and the tool reports `translation too long`; shorten the English. Self-modifying size changes are impossible without rewriting all heaps. |
| No self-integrity check | None was observed in the tested build. If the author adds a hash check, the patched exe would refuse to start (nothing in this repo can work around that). |

### Workflow for a new launcher version

```bat
python patch.py scan  --exe EXVS2OB_new.exe --out scan.json
python patch.py patch --exe EXVS2OB_new.exe --out EXVS2OB_new_en.exe
```

`patch` lists every string that needs work:

```
untranslated #US strings: 12
  [us] '新的提示文字'
untranslated BAML strings: 1
  [baml] '新的按钮'
```

Add those keys to `data/*.json`, translate, repeat until `patch` prints no gaps and
`verify` says `OK`.

Note that the translation table is intentionally *additive*: keep entries for the old
version too, so one repository can patch several launcher releases.

---

## Verification performed on this build

* File size unchanged: 1,692,790 bytes.
* `#US`: 1788 blobs, identical offsets and lengths, flag bytes untouched.
* 535 runtime strings + 70 BAML strings + 12 JS comment runs replaced.
* 0 Chinese left in `#US`, `#Strings` or the BAML resources.
* 0 bytes changed outside the `#US` heap and the resources directory.
* Placeholders (`{0}`, `%s`, …) verified unchanged for all 536 rewritten blobs.
* The appended assembly still parses (`dnfile`: 122 types, `#US` = 43,972 bytes).

## Disclaimer

The translation data is community work. This repository contains no game files and
does not redistribute the launcher binary; `EXVS2OB.exe` remains untouched by design.
