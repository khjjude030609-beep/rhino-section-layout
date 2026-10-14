---
name: rhino-section-layout
description: Rhino 8 모델을 잘라 레이아웃(A3) 단면도·평면도 PDF로 뽑는다 — Technical 표시, 재질별 실제 해치(벽돌 켜·철근콘크리트·흙·나뭇결·몰탈, AutoCAD/Revit .pat 원본), 블록 이음매 없는 합친 단면선, 두께별 선 굵기, 자동 축척, CTB 대신 출력색 통일, 오른쪽 글 칸. "단면도 찍어줘", "평면도 뽑아줘", "레이아웃으로 단면", "재질 해치 넣은 단면 PDF" 같은 요청에 쓴다. Rhino MCP(run_python) 필요.
---

# Rhino 단면·평면 레이아웃

스크립트 하나: 이 스킬 폴더의 `scripts/section_layout.py`. Rhino MCP `run_python` 에서 `exec` 로 불러 쓴다.

## 쓰는 법

```python
CFG = dict(axis='x', cut=121000, look=-1, depth=4000, scale='auto',
           page='단면 A', pdf=r'D:\...\단면A.pdf',
           title=['단면 A', 'x = 121.0 m에서 자름, 서쪽을 봄', '축척 1:{scale} (A3)'])
exec(open(r'<SKILL_DIR>\scripts\section_layout.py', encoding='utf-8').read())   # <SKILL_DIR> = 이 스킬 폴더
remove_page(CFG['page'])   # 같은 이름 페이지가 있으면 지우고 다시 (없으면 아무 일 없음)
build(CFG)                 # 단면판 2장 + 페이지 + 디테일 + 단면선·해치 + 제목 칸 (1~3초)
export_pdf(CFG)            # Idle 핸들러로 출력 → CFG['pdf'] 옆 _export_log.txt 에 'ok 2.3 s' 또는 'ERR ...'
```
- `axis` 'x'|'y' = 단면 (그 축에 수직으로 자름), **'z' = 평면** (수평으로 자름, `look=-1` 이면 위에서 아래를 봄)
- **입면**: `elevation(dict(facing='S', scale='auto', page=..., pdf=..., title=[...]))` — 'S'|'N'|'E'|'W' 면을 바깥에서 봄.
  재질 있는 객체로 건물 범위를 구해 그 면 1 m 바깥에 단면판을 세움(앞의 나무·대지는 잘림), 깊이 제한 없음.
  잘린 면은 그리지 않고 굵은 지반선만(`ground` 기본 = 흙 객체 윗면 중앙값). 재질 맵핑 없음
- `display`: 디테일 표시 모드 이름(예: 사용자 모드). 없으면 Technical 복사본. PDF 는 출력색이 덮으므로 선 모양만 달라짐
- `cut` 자를 좌표 mm, `look` -1 = 축 음의 방향을 봄 / +1 = 양의 방향, `depth` 뒤로 보이는 깊이 mm (0 = 제한 없음)
- `scale` 숫자(1:N) 또는 `'auto'` = 잘린 범위가 그림 칸 90 % 에 들어가는 가장 큰 표준 축척 (`SCALES`). 제목의 `{scale}` 에 들어감
- `paper` 기본 (420, 297), `side` 오른쪽 글 칸 폭 96 (글자는 전부 이 칸에, 그림 칸에는 글자 없음)
- 해치만 다시: `clear_layer(LYR_SEC+'::'+CFG['page']); section(CFG)` (페이지가 이미 있을 때, 1~2초)
- 출력색(회색 통일)은 `export_pdf` 가 쓰는 동안만 바꾸고 되돌림, 단면판은 그 디테일에만 걸림 → **문서는 언제든 저장해도 됨**
- `export_pdf` 는 한 번에 하나만 (이전 로그가 생긴 뒤 다음 호출). 동시에 두 번 걸면 Idle 핸들러가 꼬임
- 확인: PDF 를 pymupdf 로 PNG 렌더해 한 번 본다. 선 굵기 검사는 `page.get_drawings()` 의 width 집계

## 어떻게 그리나 (두 겹)
- **아래층 = Rhino**: 그림 칸(디테일)에 단면판·깊이판을 걸고 Technical 복사본 `Technical_단면도구` 로 표시 (자른 면 선·채움은 끔). 단면 너머 보이는 선은 Rhino 가 그림.
- **위층 = 직접 계산**: 닫힌 덩어리를 자르는 평면과 교차 → 재질 판정 → 재질별 `Curve.CreateBooleanUnion` (블록 이음매 제거) →
  `WorldToPageTransform` 으로 **페이지 공간**에: 흰 가림 → 재질 해치 → (작은 각재) X 선 → 두께별 외곽선.
- 그리기 순서는 `DisplayOrder` 로 지정 (`ORDER`: 재료 모름 → 흙 → 콘크리트 → … → 벽돌 → 목재 → 철골, 나중 것이 위)
- 열린 폴리서피스·열린 메쉬는 잘린 면을 만들지 않음 (쐐기·겹선이 생김) → Technical 선에 맡김
- **속 빈 단면**(고리 모양 띠·관 등): 덩어리마다 안쪽 고리를 구멍으로 기록(`HOLES`, `GROUPS`). 구멍이 있는 재질은
  `CreateBooleanRegions` 로 평면을 나눈 뒤 덩어리별 고리 홀짝으로 재질 영역만 골라 합침 (`_material_regions`).
  보통 합집합(`CreateBooleanUnion`)은 바깥 고리를 꽉 찬 면으로 보고 안을 메워 버림 — 실제 사고(강재 링이 건물 전체를 검게)
- **블록(인스턴스)도 자름** (`_leaves`): 정의 속으로 들어가 변환을 곱함 (중첩 8단). 블록 속 객체 재질은 자기 레이어, '재료 모름'이면 블록 객체의 레이어·태그
- **입면도** `elevation(CFG)`: `CFG['facing']` = 'S'|'N'|'E'|'W'. 재질 있는 객체로 건물 범위를 구하고(중심 5~95 % ± 20 % — 멀리 떨어진 담장·대지 객체 제외, `bbox` 로 직접 지정 가능)
  면 바깥 `margin`(1 m)에 단면판, 건물 뒤에 깊이판(건물 길이 + 2·margin), 카메라는 건물 중심. 잘린 면은 안 그리고 굵은 지반선만 (`ground` 기본 = 흙 객체 윗면 중앙값).
  깊이판이 없으면 벡터 PDF 숨은선 계산이 사이트 전체로 번져 빈 출력이 나옴(겪음)
  **입면 PDF 는 래스터(기본 400 dpi)**: Rhino 벡터 PDF 는 Technical 숨은선을 안 가려 벽 뒤 H형강·창이 비침(겪음, 숨은선 설정은 꺼져 있었음). 화면 표시는 정확 → `raster` 로 화면 그대로. `CFG['raster']`·`CFG['dpi']` 로 바꿈
- **평면 계단 아래층·UP/DN** (`_stair_marks`, `STAIR_MARK`): 계단 객체마다 수평 면(디딤판)을 높이순 정렬 (`SplitKinkyFaces` 로 톱니 밀어낸 계단도 나눔,
  위 향한 면이 없으면 아래 향한 면 = 뒤집혀 모델링된 계단 예비). `floor`(기본 cut−1200) 근처에서 시작해 잘린 높이를 넘는 계단 = UP(바닥→잘린 자리),
  이 층까지 올라오는 아래 계단 = 디딤판 윤곽을 직접 그리고 DN(위→아래). 화살표는 디딤판 중심을 이어서 곡선계단도 따라 휨. 시작점 동그라미 + 화살촉 + 글자.
  `STAIR_MARK['label']=None` 이면 글자 없이 (도판에 글자 안 넣는 규칙일 때). 끄려면 `CFG['stair_marks']=False`
- **평면 계단 잘림표시**: 끝 레이어 이름·element 에 '계단'/'stair' (난간·손잡이·rail 제외) → 잘린 면을 칠하지 않고, 잘린 띠(계단 폭 방향)를
  30° 기울여 가로지르는 지그재그 선 (`BREAK`). 아래 디딤판은 Technical 선, 위는 단면판에 잘림. 끄려면 `CFG['stair_break']=False`

## 재질 판정 — 프로젝트마다 고칠 곳
`kind(layer_path, element)`: 객체 `element` 사용자 문자열 → 레이어 끝 이름 → 전체 경로 순으로 보고, 각 글에서 **재료 낱말(MAT)을 부재 낱말(PART)보다 먼저** 찾는다.
- `VOID` ('공간','공동','범위') → 안 그림. 유리 → 안 그림
- 영문 낱말은 앞머리만 맞춤 (`CLOSED_BREPS` 의 EPS, `PLYWOOD` 의 wood 오판 방지), 대문자 약어는 대소문자 구분
- 객체 이름(설명문)은 쓰지 않음 — 설명문 속 낱말로 오판
- 새 모델이면 먼저 단면에 걸리는 레이어별 `kind` 표를 찍어 보고 MAT/PART 를 고친다

## 해치 표 (`HATCH`, 평면 전용 `HATCH_PLAN`)
| 재질 | 패턴 (원본) | 스케일 |
|---|---|---|
| BRICK | `S-BRICK` = AR-BRSTD(길이쌓기) 형식을 벽돌 실치수로 (`BRICK = (230, 60, 10)`, 한 켜 70) | 실제 mm |
| BRICK (평면) | `S-BRICK-PLAN` 폭 줄(110+10) × 길이 반장 어긋남, **벽 조각마다 벽 방향으로 회전** (`ALONG`, 아래) | 실제 mm |
| CONC | ANSI31 사선 + AR-CONC 자갈 점·삼각형 겹침 (철근콘크리트 관례) | 종이 0.6 / 0.02 |
| EARTH | EARTH | 종이 0.35 |
| WOOD | Wood_1 (Revit); 400 mm 미만 네모 각재는 대각선 X | 종이 0.5 |
| MORTAR | AR-SAND — 몰탈·미장·인조석 | 종이 0.03 |
| STONE | GRAVEL | 종이 0.03 |
| INSUL | INSUL | 종이 0.25 |
| SOLID | 검정 채움 (철골·기와·타일·홈통) | — |
| WHITE | 흰 가림만 (재료 모름) | — |

- 평면 벽돌 방향 (`_wall_dir`, `_wall_parts`): 잘린 벽 조각(블록 하나)마다 직선 변을 길이로 가중한 각도 = 벽 방향.
  ㄱ·T 자 조각은 꼭짓점 좌표 격자로 나눠 칸마다 가로/세로 연속 길이를 비교해 갈래별 방향. 곡선이 섞이면 꺾은선으로 바꿔 나눈 뒤 원래 곡선으로 잘라냄.
  짧은 벽기둥(장단비 < 1.8)은 긴 벽들의 두께 목록과 같은 변을 두께로 보고 나머지를 벽 방향으로. 겹친 조각은 큰 것부터 깔고 주변 조각만 빼서 두 번 칠하지 않음.
  남은 한계: 곡선+사선이 섞인 조각은 빼기가 실패해 무늬가 엇갈릴 수 있음. 사선으로 바꾸려면 `HATCH_PLAN = {'BRICK': ('S-ANSI31','ANSI31',0.6,'paper')}`
- 한 재질에 패턴 목록을 주면 겹쳐 그림. 검정 채움으로 바꾸려면 `('SOLID', None, 1.0, 'paper')`
- `.pat` 은 설치된 AutoCAD `acadiso.pat`·Revit `revit metric.pat` 을 glob 으로 자동으로 찾아 `HatchPattern.ReadFromFile` 로 읽고 `S-` 접두로 추가. 없으면 `FALLBACK` 간이 패턴. 다른 파일은 `PAT_EXTRA`
- 패턴 0° 를 종이 가로로 돌리고(`PatternRotation`) 기준점을 z=0 에 맞춰 벽돌 켜가 바닥선과 맞음

## 선 굵기 (`STYLE`)
- 외곽선: 띠 두께 t = 2·면적/둘레(종이 mm) 로 3단계 — t<0.4 → 0.13, t<1.0 → 0.25, 나머지 0.4
- 해치·X 0.05, 너머 보이는 선(Technical) 회색 0.13

## 함정 (겪은 것)
- **단면선을 모델 공간에 두면** Technical 벡터 PDF 의 숨은선 처리가 외곽선·X 선을 지움 (해치만 남음) + 다른 단면 디테일에 옆모습 굵은 선 → 페이지 공간에 그린다
- 페이지 객체는 만든 순서대로 안 그려짐 → `DisplayOrder` 필수 (검정 채움이 장선을 덮던 문제)
- 디테일 카메라를 바꾼 뒤 `CommitViewportChanges()` 없으면 저장 안 됨. 스케일은 그 다음 `DetailGeometry.SetScale` + `CommitChanges()`
- 페이지가 활성인 채 모델 객체를 만들면 페이지 공간으로 들어감 → `_model_view()` 먼저. 페이지 객체는 `Space=PageSpace, ViewportId` 명시
- 출력: `OutputColor = PrintColor` (BlackAndWhite 는 흰 가림을 검게 칠함), `RasterMode = False`, `UsePrintWidths = True`
- MCP 호출 300초 제한 → PDF 는 `RhinoApp.Idle` 에서 쓰고 로그로 확인. 보통 2초, 기와 수천 장이 보이는 긴 종단은 60초 (보이는 객체 수 때문, 깊이 밖 숨김은 효과 없음)
- 화면 중심·자동 축척은 잘린 단면 곡선 범위로 (모델 객체 범위로 하면 길게 뻗은 객체 하나에 끌려감)
- 출력색을 바꾸는 코드는 원래 값을 꼭 기록할 것. 잃으면 저장 직전 `.3dmbak` 을 rhino3dm 으로 읽어 Id 로 복원
- 단면판 법선 = 보는 방향이어야 카메라 쪽이 잘림. 문자열 속 윈도 경로는 raw 문자열로 (`\U` 이스케이프 오류)
