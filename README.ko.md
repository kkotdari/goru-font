# 고르 폰트 빌더

우리 글자 고르게 고르게 ――― 줄맞춤 강박에 시달리는 개발자들을 위한 한·영·일 고정폭 폰트 병합 시스템
영어·한국어·일본어 고정폭 폰트를 하나로 합쳐서 열 정렬이 완벽한 다국어 코딩 폰트를 만들어주는 config 기반 빌드 시스템. CJK 글리프가 라틴 글리프의 딱 2배 너비라서 언어가 섞여도 열이 안 틀어짐.

---

## 프로파일

자주 쓰는 케이스를 커버하는 내장 프로파일 4개.

| 프로파일 | Half-width | Full-width | 설명 |
|---|---|---|---|
| `mono` | 1024 | 2048 | 기본 1:2 비율 |
| `mono-c` | 870 | 1740 | Condensed — 라틴 글리프가 더 좁음 |
| `absolute-mono` | 1024 | 1024 | 모든 글리프가 동일 너비 |
| `absolute-mono-c` | 870 | 870 | Condensed absolute |

프로파일끼리 `extends`로 상속 — 달라지는 값만 적으면 됨.

---

## 준비

### 1. Python 3.8+

```bash
python --version
```

### 2. FontForge

`fontforge` 명령어가 PATH에 있어야 함.

```bash
# macOS
brew install fontforge

# Ubuntu / Debian
sudo apt-get install fontforge

# Windows — https://fontforge.org 에서 인스톨러 받고
# 설치 후 bin 디렉터리를 PATH에 추가:
# C:\Program Files (x86)\FontForgeBuilds\bin
```

확인:
```bash
fontforge --version
```

### 3. Python 패키지

```bash
pip install -r requirements.txt
```

| 패키지 | 역할 |
|---|---|
| `fonttools` | 후처리: TTF에 모노스페이스 메타데이터 기록 |
| `jinja2` | FontForge 스크립트 템플릿 렌더링 |
| `pyyaml` | YAML config 파싱 |
| `rich` | 선택 — 병렬 진행 상황 예쁘게 표시 |

### 4. 소스 폰트

빌드 시스템이 소스 폰트 3종을 합침. 아래 구조대로 파일 배치 — 파일명은 `src/configs/build/mono.yaml` 각 언어의 `source_files`와 일치해야 함.

```
src/resources/source_fonts/
├── english/
│   ├── MesloLGM-Regular.ttf
│   ├── MesloLGM-Bold.ttf
│   ├── MesloLGM-Italic.ttf
│   └── MesloLGM-BoldItalic.ttf
├── korean/
│   ├── SarasaFixedK-Regular.ttf
│   ├── SarasaFixedK-Bold.ttf
│   ├── SarasaFixedK-Italic.ttf
│   └── SarasaFixedK-BoldItalic.ttf
└── japanese/
    ├── SarasaFixedJ-Regular.ttf
    ├── SarasaFixedJ-Bold.ttf
    ├── SarasaFixedJ-Italic.ttf
    └── SarasaFixedJ-BoldItalic.ttf
```

다운로드:
- **Meslo LG M** — [github.com/andreberg/Meslo-Font](https://github.com/andreberg/Meslo-Font)
- **Sarasa Gothic** — [github.com/be5invis/Sarasa-Gothic](https://github.com/be5invis/Sarasa-Gothic)
  (`SarasaFixed` 변형 사용)

---

## 사용법

프로젝트 루트(`goru-font/`)에서 실행.

```
python run.py [-p <profile>...] [-s <style>...] [-w <n>] [-seq]
```

```bash
# 기본 프로파일(mono)로 스타일 4개 전부 빌드
python run.py

# 특정 스타일만
python run.py -s regular bold

# 특정 프로파일
python run.py -p mono-c

# 여러 프로파일 순차 빌드
python run.py -p mono mono-c absolute-mono absolute-mono-c

# 병렬 워커 수 제한 (메모리 절약)
python run.py -w 2

# 순차 처리 — 디버깅할 때 유용
python run.py --sequential

# 옵션 조합
python run.py -p mono-c -s regular --sequential
```

### CLI 레퍼런스

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `-p / --profile` | `mono` | 프로파일 이름 — 여러 개면 스페이스로 구분 |
| `-s / --styles` | all | `regular` `bold` `italic` `bold_italic` |
| `-w / --workers` | `4` | 병렬 워커 수 |
| `-seq / --sequential` | off | 순차 처리 강제 |

### 출력

빌드된 폰트는 여기에 저장:

```
output/v{version}/
├── GoruMono-Regular.ttf
├── GoruMono-Bold.ttf
├── GoruMono-Italic.ttf
└── GoruMono-BoldItalic.ttf
```

버전은 `src/configs/font/mono.yaml`의 `font.version`에서 가져옴.

---

## 빌드 과정

`python run.py` 실행 시 실제로 일어나는 일.

### Step 0 — Config 로딩

빌더가 config 파일 3개를 로드해서 deep-merge:

1. `src/configs/font/mono.yaml` — 폰트 정체성 (패밀리명, 버전, 저작권)
2. `src/configs/build/mono.yaml` — 메트릭, 그리드 너비, 소스 파일, 언어별 스케일
3. `src/configs/logging/logging.yaml` — 터미널/파일 로그 설정

`mono.yaml`은 `base.yaml`을 상속하고, `base.yaml`이 언어 처리 파이프라인 (템플릿, 처리 순서, 오버랩 규칙, 문자 분류)을 담고 있음.

### Step 1 — 검증

파일 건드리기 전에 먼저 확인:

- 필수 config 필드 전부 존재 여부 (`font.family`, `metrics.*`, `width.*`, `languages.*.scale.*`, `languages.*.source_files.*`)
- 소스 폰트 파일이 실제로 디스크에 있는지

뭔가 빠져 있으면 어떤 필드가 없는지 찍고 종료. 검증 통과 전엔 아무것도 생성 안 함.

### Step 2 — 임시 디렉터리

`temp/` 아래에 타임스탬프 붙은 작업 디렉터리 생성:

```
temp/build_20260419_153000/
```

중간 결과물인 `.sfd` 파일(FontForge 네이티브 포맷)과 생성된 `.pe` 스크립트가 여기에 저장됨. 빌드 끝나거나 중단되면 자동 삭제.

스크립트를 확인하고 싶으면 build config에서 `output.save_temp_files: true` 설정. 그러면 `backups/scripts_{timestamp}/`에 복사해두고 정리함.

### Step 3 — 스크립트 생성

스타일마다 (`regular`, `bold`, `italic`, `bold_italic`) Jinja2가 각 언어 config에 지정된 템플릿에서 FontForge PE 스크립트 렌더링:

| 언어 | 템플릿 |
|---|---|
| 영어 | `src/ff/service/en_processing.pe.j2` |
| 한국어 | `src/ff/service/kr_processing.pe.j2` |
| 일본어 | `src/ff/service/jp_processing.pe.j2` |
| 병합 | `src/ff/service/final_merge.pe.j2` (`output.merge_template`으로 변경 가능) |

템플릿에는 언어 config(`lang.*`), 입력 폰트 경로, 출력 SFD 경로, 오버랩 제거용 참조 SFD 경로가 전달됨. Python 코드에는 언어명이 하드코딩되어 있지 않음.

### Step 4 — 언어 처리 (FontForge)

언어별로 순서대로 처리 (영어 → 한국어 → 일본어). 각 언어마다 FontForge가:

1. 소스 TTF 열기
2. 제외할 글리프 제거 (영어만)
3. 합성 글리프 언링크
4. 목표 EM(`em_ascent` / `em_descent`)으로 스케일
5. 글리프 분류:
   - **`no_center`** 범위 → 너비만 설정, 센터링 없음 (박스 드로잉, 블록 요소)
   - **`no_scale`** 범위 → 센터링만, 스케일 없음 (화살표, 심볼, Powerline)
   - **`halfwidth`** 범위 → `lang.scale.half_width_*` 스케일로 half_width 슬롯에 맞춤
   - **`fullwidth`** 범위 → `lang.scale.full_width_*` 스케일로 full_width 슬롯에 맞춤
   - 나머지 → 원래 글리프 너비 vs. `width.threshold` 비교해서 분류
6. 커닝(GPOS), 합자(GSUB) 테이블 제거
7. 좌표 전부 정수로 반올림
8. 임시 디렉터리에 `.sfd`로 저장

한국어·일본어는 이전에 처리된 폰트에 이미 있는 글리프도 제거함 (언어 config의 `remove_overlaps_with`로 제어). 이 방식으로 동일 코드포인트에서 영어 글리프가 CJK보다 우선함.

스타일은 기본적으로 병렬 처리 (워커 4개). 각 워커가 한 스타일의 모든 언어를 독립적으로 처리.

### Step 5 — 병합 (FontForge)

최종 병합 스크립트가:

1. 영어 SFD를 베이스로 열기
2. 한국어·일본어 SFD를 순서대로 병합
3. 폰트 메타데이터 전부 설정 (이름, OS/2 값, 저작권, 버전)
4. 남은 커닝·합자 테이블 제거
5. `output/v{version}/`에 최종 TTF 생성

### Step 6 — 후처리 (Python)

`fonttools`가 생성된 TTF를 열고 모노스페이스 메타데이터 3개 기록:

| 필드 | 값 | 효과 |
|---|---|---|
| `post.isFixedPitch` | `1` | 고정폭 폰트 선언 |
| `OS/2.panose.bProportion` | `9` | PANOSE 모노스페이스 분류 |
| `OS/2.xAvgCharWidth` | `half_width` | 평균 문자 너비 |

이 단계 없으면 VS Code나 Windows Terminal 같은 앱이 폰트를 모노스페이스로 못 인식할 수 있음.

---

## Config 구조

```
src/
├── configs/
│   ├── paths.yaml              ← 디렉터리 경로 전부 (경로 바꿀 때 여기만 수정)
│   ├── font/                   ← 폰트 정체성만 (이름, 버전, 저작권)
│   │   ├── mono.yaml
│   │   ├── mono-c.yaml
│   │   ├── absolute-mono.yaml
│   │   └── absolute-mono-c.yaml
│   ├── build/                  ← 처리 설정 (메트릭, 그리드, 스케일, 소스 파일)
│   │   ├── base.yaml           ← 언어 파이프라인, 문자 분류, 빌드 플래그
│   │   ├── mono.yaml           ← base 상속 + 메트릭 + 너비 + 언어별 설정
│   │   ├── mono-c.yaml         ← mono 상속, 너비 + 스케일 오버라이드
│   │   ├── absolute-mono.yaml  ← mono 상속, full_width + 스케일 오버라이드
│   │   ├── absolute-mono-c.yaml
│   │   └── minimal.yaml        ← mono 상속, regular만 (빠른 테스트용)
│   └── logging/
│       └── logging.yaml
└── profiles/
    └── profile.yaml            ← 프로파일 이름 → font + build config 파일명 매핑
```

### `paths.yaml`

모든 디렉터리 경로를 프로젝트 루트 기준으로 관리. 여기서 바꾸면 Python 파일은 건드릴 필요 없음.

```yaml
source_fonts:     "src/resources/source_fonts"
templates:        "src/ff/service"
output:           "output"
logs:             "logs"
temp:             "temp"
backups:          "backups"
profile_registry: "src/profiles/profile.yaml"

config_dirs:
  font:    "src/configs/font"
  build:   "src/configs/build"
  logging: "src/configs/logging"
```

환경변수로 런타임 오버라이드:

```bash
GORU_PATHS_FILE=/path/to/custom-paths.yaml python run.py
```

### Font config (`src/configs/font/mono.yaml`)

폰트 정체성만 — 이름, 버전, 저작권, URL.

```yaml
font:
  family:       "Goru Mono"
  family_short: "GoruMono"
  version:      "1.0.0"
  copyright:    "Copyright (c) 2026, kkotdari"
  ...
```

### Build config (`src/configs/build/mono.yaml`)

폰트 처리·조립에 필요한 모든 것. 언어별 소스 파일과 스케일은 각 언어 항목 안에 묶음.

```yaml
extends: "base.yaml"

metrics:
  em_ascent:  1792
  em_descent:  512
  ...

width:
  half_width: 1024
  full_width: 2048
  threshold:  1536

languages:
  english:
    source_files:
      regular:     "MesloLGM-Regular.ttf"
      bold:        "MesloLGM-Bold.ttf"
      italic:      "MesloLGM-Italic.ttf"
      bold_italic: "MesloLGM-BoldItalic.ttf"
    scale:
      half_width_x: 0.78
      half_width_y: 0.86
      full_width_x: 0.99
      full_width_y: 0.96
  korean:
    ...
```

---

## 새 언어 추가

Python 파일 수정 없이 YAML이랑 템플릿 파일만 있으면 됨.

1. **템플릿 추가** — `src/ff/service/kr_processing.pe.j2`를 `src/ff/service/zh_processing.pe.j2`로 복사하고 필요한 부분 수정.

2. **`src/configs/build/base.yaml`에 언어 항목 추가:**

```yaml
languages:
  chinese:
    enabled:  true
    template: "zh_processing.pe.j2"
    dir:      "chinese"
    order:    4
    timeout:  900
    remove_overlaps:      true
    remove_overlaps_with: ["english", "korean", "japanese"]
```

3. **`src/configs/build/mono.yaml`에 소스 파일·스케일 추가:**

```yaml
languages:
  chinese:
    vertical_shift: 0
    source_files:
      regular:     "SourceHanMono-Regular.ttf"
      bold:        "SourceHanMono-Bold.ttf"
      italic:      "SourceHanMono-Regular.ttf"   # 이탤릭 없으면 regular 사용
      bold_italic: "SourceHanMono-Bold.ttf"
    scale:
      half_width_x: 0.78
      half_width_y: 0.86
      full_width_x: 0.99
      full_width_y: 0.96
```

4. **`src/resources/source_fonts/chinese/`에 폰트 파일 배치.**

---

## 트러블슈팅

### FontForge를 못 찾겠다는 에러

```bash
# 명령어 동작 확인
fontforge --version

# Windows: PATH 확인
where fontforge
```

### 검증에서 빌드가 멈춤

빌더가 빠진 필드를 찍어줌. 해당 config 파일에 값 추가하면 됨:

```
ERROR: configuration is incomplete — cannot start build:
  languages.english.scale.half_width_x: required
```

→ build config의 `english` 항목에 `scale.half_width_x` 추가.

### 소스 폰트를 못 찾겠다는 에러

```
[english] regular: file not found (src/resources/source_fonts/english/MesloLGM-Regular.ttf)
```

→ 표시된 경로에 파일 넣거나, build config의 `source_files.regular` 경로 수정.

### 병렬 빌드 중 메모리 부족

```bash
# 워커 수 줄이기
python run.py --workers 2

# 또는 한 번에 하나씩
python run.py --sequential
```

### 중간 스크립트 확인하고 싶을 때

```yaml
# src/configs/build/mono.yaml (또는 아무 build config)
output:
  save_temp_files: true
```

생성된 `.pe` 스크립트가 임시 디렉터리 정리 전에 `backups/scripts_{timestamp}/`에 저장됨. 텍스트 에디터로 열면 FontForge가 실제로 뭘 실행했는지 볼 수 있음.

---

## 라이선스

### 생성된 폰트
**SIL Open Font License 1.1** — 기반:
- **Meslo LG** by André Berg — Apache License 2.0
- **Sarasa Gothic** by Belleve Invis — SIL OFL 1.1

### 빌드 시스템
**Apache License 2.0**

```
Copyright (c) 2026, kkotdari
```

---

**Author**: kkotdari | **Repository**: https://github.com/kkotdari/goru-font
