# rhino-section-layout

Rhino 8 모델을 잘라 **A3 레이아웃 단면도·평면도 PDF**를 자동으로 뽑는 Claude Code 스킬.
(Claude Code skill that cuts a Rhino 8 model and exports A3 layout sections/plans with real material hatches.)

- Technical 표시 + 재질별 실제 해치 (벽돌 켜 · 철근콘크리트 · 흙 · 나뭇결 · 몰탈 · 석재 · 단열)
- 블록 이음매 없는 합친 단면선, 부재 두께에 따른 선 굵기 3단계, 작은 각재는 대각선 X
- 평면: 벽돌 무늬를 벽마다 벽 방향으로 (ㄱ·T 자 벽은 갈래별), 계단은 잘린 면 대신 지그재그 잘림표시,
  아래층으로 내려가는 계단 디딤판 + UP/DN 화살표 (곡선계단도 디딤판 중심을 따라 휨)
- 입면도: `elevation(dict(facing='S', ...))` — 건물 범위를 스스로 구해 그 면을 바깥에서 봄, 지반선 포함
- Rhino 블록(인스턴스) 속 객체까지 자름
- 입면: `elevation(dict(facing='S', ...))` — 남·북·동·서 면, 지반선 포함, 재질 맵핑 없음
- 자동 축척 (그림 칸에 맞는 가장 큰 표준 축척), 오른쪽 글 칸 (그림 칸에는 글자 없음)
- CTB 없이 출력색 통일 (PDF 쓰는 동안만 적용 → 문서는 그대로 저장 가능)

## 필요한 것
- Windows + **Rhino 8** (Python 3 스크립트)
- **Claude Code** + Python 을 Rhino 안에서 실행하는 **Rhino MCP 서버** (`run_python` 같은 도구)
  - MCP 없이도 됨: Rhino `ScriptEditor` (Python 3) 에서 아래 "직접 쓰기"처럼 실행
- (선택) AutoCAD 또는 Revit 설치 → 표준 해치 파일(`acadiso.pat`, `revit metric.pat`)을 자동으로 찾아 씀.
  없으면 간이 패턴으로 대신함. 다른 `.pat` 은 스크립트의 `PAT_EXTRA` 에 경로 추가.
  (Autodesk 해치 파일은 이 패키지에 들어 있지 않음)

## 공유용 프롬프트 (Claude Code 에 그대로 붙여 넣기)
```
Rhino 단면도·평면도 자동화 스킬을 설치하고 내 모델로 시험해 줘.

1. 설치: https://github.com/khjjude030609-beep/rhino-section-layout 을
   C:\Users\<내 이름>\.claude\skills\rhino-section-layout 에 받아 줘 (Windows 기준).
   받은 뒤 SKILL.md 와 README.md 를 먼저 읽어.
2. 확인: Rhino 8 이 열려 있고 Rhino MCP 로 Python(run_python 같은 도구)을 돌릴 수 있는지 확인해.
   안 되면 무엇이 빠졌는지만 알려 주고 멈춰. 모델 단위가 mm 인지도 봐.
3. 재질 맞추기: 시험 단면에 걸리는 레이어 목록과 스킬이 판정한 재질(kind)을 표로 보여 줘.
   틀린 줄이 있으면 MAT / PART / VOID / STAIR 낱말 표를 어떻게 고칠지 제안하고, 내가 확인한 뒤에 고쳐.
   벽돌 치수(BRICK, BRICK_W)도 내 모델 기준으로 물어봐.
4. 시험 출력: 모델 범위를 보고 단면 1장(건물 가운데를 가로지르게)과 평면 1장(바닥 위 1.2 m)을 제안해.
   내가 위치를 정하면 A3 PDF 로 뽑고 PNG 로 보여 줘. 축척은 자동.
5. 내 Rhino 파일은 내가 말하기 전에는 저장하지 마.
```

## 설치 (직접)
1. `rhino-section-layout` 폴더를 통째로 `C:\Users\<사용자>\.claude\skills\` 안에 복사
2. Claude Code 를 다시 열면 스킬 목록에 보임
3. Rhino 에 모델을 열고 Claude 에게: "x = 121 m 에서 남북 단면도 찍어줘", "1층 평면도 뽑아줘 (z = 1.2 m)"

## 직접 쓰기 (ScriptEditor 또는 MCP)
```python
CFG = dict(axis='x', cut=121000, look=-1, depth=4000, scale='auto',
           page='단면 A', pdf=r'D:\out\단면A.pdf',
           title=['단면 A', 'x = 121.0 m', '축척 1:{scale} (A3)'])
exec(open(r'C:\Users\<사용자>\.claude\skills\rhino-section-layout\scripts\section_layout.py', encoding='utf-8').read())
remove_page(CFG['page'])
build(CFG)        # 페이지 + 디테일 + 단면선·해치 + 제목 칸
export_pdf(CFG)   # 벡터 PDF, 결과는 PDF 옆 _export_log.txt
```
- `axis`: `'x'`/`'y'` = 단면, `'z'` = 평면 · `cut`: 자를 좌표(mm) · `look`: -1 / +1 보는 방향 · `depth`: 뒤로 보이는 깊이(mm)
- 평면 예: `dict(axis='z', cut=1200, look=-1, depth=1400, scale='auto', page='1층 평면', ...)` (바닥 위 1.2 m 에서 자르고 아래를 봄)
- `stair_break=False` 면 평면 계단도 잘린 면으로 그림, `stair_marks=False` 면 UP/DN·아래층 계단 표시 끔, `floor` = 이 층 바닥 높이(기본 cut−1200)
- 입면 예: `CFG = dict(facing='S', scale='auto', page='남측 입면', pdf=r'D:\out\남측.pdf'); elevation(CFG); export_pdf(CFG)`
- 모델 단위는 mm 기준

## 내 모델에 맞추기 (중요)
재질은 **레이어 이름 낱말**로 판정한다 (`scripts/section_layout.py` 의 `MAT`, `PART`, `VOID` 표).
예: 레이어 이름에 '벽돌'·'brick' → 벽돌, '콘크리트'·'슬래브' → 철근콘크리트, '장선'·'timber' → 목재, '공간' → 그리지 않음.
내 모델의 레이어 이름이 다르면 이 표에 낱말을 추가하면 된다. 그 밖에:
- `BRICK = (230, 60, 10)`: 벽돌 길이·높이·줄눈 (mm)
- `HATCH`, `HATCH_PLAN`: 재질별 패턴과 크기
- `STYLE`: 선 굵기, 너머 보이는 선 회색

## 한계
- 재질을 이름으로 판정하므로 이름이 실제와 다르면 틀린 해치가 나옴
- 닫힌 덩어리(solid)만 잘린 면으로 그림. 열린 면은 일반 선으로만 보임
- 평면 벽돌 방향: 곡선과 사선이 한 조각에 섞인 벽은 무늬가 엇갈릴 수 있음
- 계단 판정도 이름 기준 ('계단'·'stair'). 이름이 다르면 `STAIR` 표에 낱말 추가
- 입면 PDF 는 래스터(400 dpi). Rhino 벡터 PDF 가 Technical 숨은선을 가리지 못해서 (단면·평면은 벡터)
- 기와처럼 작은 객체가 수천 개 보이는 긴 단면은 PDF 출력에 1분 정도 걸림
- 결과는 고정 그림: 모델·자르는 위치가 바뀌면 다시 실행 (한 장 몇 초)

자세한 원리와 겪은 함정은 `SKILL.md` 참고.
