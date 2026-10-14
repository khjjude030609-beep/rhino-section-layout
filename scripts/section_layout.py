# -*- coding: utf-8 -*-
r"""
Rhino 8 단면도·평면도 레이아웃 자동화 (Technical + 재질 해치 + 단면선 합침 + CTB식 출력)
사용 (Rhino MCP run_python 또는 Rhino ScriptEditor, Python 3):
    CFG = dict(axis='x', cut=121000, look=-1, depth=4000, page='단면 A', title=['단면 A', '축척 1:{scale}'],
               pdf=r'D:\...\out.pdf', scale='auto')
    exec(open(r'<이 스킬 폴더>\scripts\section_layout.py', encoding='utf-8').read())
    remove_page(CFG['page'])   # 같은 이름 페이지 지우기 (없으면 그냥 지나감)
    build(CFG)            # 단면판·레이아웃·해치·제목 만들기
    export_pdf(CFG)       # Idle 핸들러로 PDF 출력 (CFG['pdf'] 옆 _export_log.txt 에 결과)
- axis: 'x' 또는 'y' = 단면 (그 축에 수직으로 자름), 'z' = 평면. cut: 자를 좌표(mm)
- look: 보는 방향. -1 = 축 음의 방향을 봄(카메라가 + 쪽), +1 = 양의 방향을 봄
- depth: 단면 뒤로 보이는 깊이(mm). 0 이면 깊이 제한 없음
해치만 다시 (페이지 이미 있음): clear_layer(LYR_SEC+'::'+CFG['page']); section(CFG)
재질 = kind(레이어 경로, element 태그) → MAT/PART 표. 해치 = HATCH 표 (acadiso.pat·revit metric.pat 원본)
출력색은 export_pdf 동안만 바뀌고 단면판은 디테일에만 걸림 → 문서는 언제든 저장해도 됨.
restore() = 이 도구가 만든 페이지·단면 객체 전부 지우기 (보통 안 씀).
"""
import Rhino, System, math, collections, os, time, re
import scriptcontext as sc
from Rhino.Geometry import Point3d, Point2d, Vector3d, Vector2d, Plane, BoundingBox, Transform

d = globals().get('__rhino_doc__') or Rhino.RhinoDoc.ActiveDoc   # Rhino MCP 가 넣어 주는 문서, 없으면(스크립트 에디터) 활성 문서
TAG = '_단면도구'
LYR_CLIP = TAG + '::단면판'
LYR_SEC = TAG + '::단면선해치'
MODE = 'Technical_단면도구'

# ---- 재질 판정. 프로젝트마다 고쳐 쓰기 ----
# 가까운 글부터 본다: 객체 element 태그 → 레이어 이름(끝) → 레이어 전체 경로.
# 각 글에서 재료 낱말(벽돌·콘크리트…)을 부재 낱말(장선·기초…)보다 먼저 → '벽돌 줄기초' = 벽돌, '마루_장선' = 목재
VOID = ('공간', '공동', '범위')                      # 마루 밑 빈 공간·철거 범위 같은 부피 표시 → 단면 안 그림
MAT = [('MORTAR', ('몰탈', '미장', '인조석', 'plaster', 'mortar')),
       ('BRICK', ('벽돌', '조적', 'brick')),
       ('CONC', ('콘크리트', '테라조', 'concrete')),
       ('STONE', ('화강석', '석재', '판석', 'stone')),
       ('WOOD', ('목재', '합판', 'wood', 'timber', 'plywood')),
       ('SOLID', ('H형강', '철골', '강재', '철물', 'steel')),
       ('EARTH', ('지반', '흙', '성토', 'earth', 'soil')),
       ('INSUL', ('단열', 'XPS', 'EPS', 'insul'))]
PART = [('WOOD', ('장선', '멍에', '트러스', '서까래', '도리', '마루', '틀', '플로어링', 'batten', 'rafter', 'flooring')),
        ('SOLID', ('홈통', '첨탑', '기와', '타일', 'mullion', 'tile', 'sukiwa')),
        ('CONC', ('슬래브', '바닥판', '기초', '받침')),
        ('BRICK', ('벽', '파라펫', 'wall', 'parapet'))]   # 파라펫 = 조적 가정

# 평면(axis='z')에서 계단: 잘린 면 대신 잘림표시(지그재그 사선). CFG stair_break=False 면 끔
STAIR = ('계단', 'stair')
STAIR_NOT = ('난간', '손잡이', '핸드레일', '기초', 'rail', 'baluster', 'footing')   # '줄기초 계단' = 계단식 기초

def _is_stair(path, element=''):
    t = element + '::' + path.split('::')[-1]               # 끝 이름·태그만 ('계단실' 레이어 안의 벽은 계단 아님)
    return any(_hit(w, t) for w in STAIR) and not any(_hit(w, t) for w in STAIR_NOT)

def _hit(w, t):
    if not w.isascii(): return w in t
    # 영문은 낱말 앞머리만 (CLOSED_BREPS 의 EPS, PLYWOOD 의 wood 오판 방지). 대문자 약어는 대소문자 구분
    return re.search(r'(?<![A-Za-z])' + re.escape(w), t, 0 if w.isupper() else re.I) is not None

def kind(path, element=''):
    if TAG in path or '유리' in path or 'glass' in path.lower(): return None
    last = path.split('::')[-1]
    for t in (element, last):
        if any(k in t for k in VOID): return None
    for t in (element, last, path):
        if not t: continue
        q = t.lower()
        for table in (MAT, PART):
            for k, words in table:
                if any(_hit(w, t) for w in words): return k
    return 'WHITE'

# ---- 재질 해치 ----
# 원본: AutoCAD acadiso.pat · Revit metric.pat — 설치된 것을 자동으로 찾음 (없으면 FALLBACK 간이 패턴)
# 다른 .pat 을 쓰려면 PAT_EXTRA 에 경로 추가 (앞에 둔 파일이 같은 이름 패턴에서 우선)
import glob
PAT_EXTRA = []
PAT_FILES = PAT_EXTRA + sorted(glob.glob(r'C:\Program Files\Autodesk\AutoCAD *\UserDataCache\*\Support\acadiso.pat'), reverse=True) \
          + sorted(glob.glob(r'C:\Program Files\Autodesk\Revit *\Data\revit metric.pat'), reverse=True)
BRICK = (230, 60, 10)   # 벽돌 길이·높이·줄눈 mm (모델 블록 BRK_230x110x60). 한 켜 70 mm
BRICK_W = 110           # 벽돌 폭 mm (평면 무늬: 폭 줄 × 길이 반장 어긋남)
# 재질 → (문서 패턴 이름, .pat 원본 이름, 스케일, 기준) 또는 그 목록(겹쳐 그림)
#   기준 'model' = 패턴 1단위가 실제 mm (벽돌 켜가 실치수), 'paper' = 패턴 1단위 × 스케일 = 종이 mm (기호)
HATCH = {'BRICK': ('S-BRICK', None, 1.0, 'model'),        # AR-BRSTD(길이쌓기) 형식을 벽돌 실치수로
         'CONC':  [('S-ANSI31', 'ANSI31', 0.6, 'paper'),       # 철근콘크리트 관례: 45° 사선(간격 약 1.9 mm) +
                   ('S-AR-CONC', 'AR-CONC', 0.02, 'paper')],   # 자갈 점·삼각형. 검정 채움은 ('SOLID', None, 1.0, 'paper')
         'EARTH': ('S-EARTH', 'EARTH', 0.35, 'paper'),
         'WOOD':  ('S-WOOD', 'Wood_1', 0.5, 'paper'),     # Revit 나뭇결 (작은 각재 단면은 X 표시로 대신)
         'MORTAR': ('S-AR-SAND', 'AR-SAND', 0.03, 'paper'),
         'STONE': ('S-GRAVEL', 'GRAVEL', 0.03, 'paper'),
         'INSUL': ('S-INSUL', 'INSUL', 0.25, 'paper'),
         'SOLID': ('SOLID', None, 1.0, 'paper'), 'WHITE': (None, None, 1.0, 'paper'),
         'STAIR': (None, None, 1.0, 'paper')}             # 평면 계단: 칠하지 않고 잘림표시만 (아래 BREAK)
BREAK = dict(tilt=30, over=0.8, zig=1.2, amp=1.0, w=0.25)   # 잘림표시: 기울기°, 양끝 넘침·지그재그 폭·높이 (종이 mm), 선 굵기
FALLBACK = {'S-AR-CONC': [(0, (0, 180), [20, -160]), (60, (90, 180), [20, -160])], 'S-ANSI31': [(45, (0, 3.175), [])],
            'S-EARTH': [(0, (0, 6.35), [6.35, -6.35]), (90, (6.35, 6.35), [6.35, -6.35])],
            'S-WOOD': [(0, (0, 4), [10, -2])], 'S-AR-SAND': [(37.5, (28.5, 39.8), [0, -40])],
            'S-GRAVEL': [(45, (0, 40), [10, -30])], 'S-INSUL': [(0, (0, 9.525), [])]}

# 평면(axis='z')에서만 바꿀 해치. 벽돌은 벽 조각마다 긴 변 방향으로 무늬를 돌려 깖 (ALONG)
# 사선으로 하려면 HATCH_PLAN = {'BRICK': ('S-ANSI31', 'ANSI31', 0.6, 'paper')}
HATCH_PLAN = {'BRICK': ('S-BRICK-PLAN', None, 1.0, 'model')}
ALONG = {'S-BRICK-PLAN'}   # 이 패턴은 조각별로 벽 방향에 맞춰 회전

def _pats(k, plan=False):
    v = HATCH_PLAN.get(k, HATCH[k]) if plan else HATCH[k]
    return v if isinstance(v, list) else [v]
WOOD_X = 400            # 이보다 작은 네모 각재 단면 = 대각선 X (나뭇결 대신, 건축 관례)
STYLE = dict(beyond_rgb=(70, 70, 70), beyond_w=0.13, hatch_w=0.05, ground_w=0.6,
             cut_w=((0.4, 0.13), (1.0, 0.25), (1e9, 0.4)))   # 단면 외곽선: (부재 두께 종이 mm 미만, 선 굵기 mm). 얇은 층·작은 각재는 가늘게

def _layer(path, color=System.Drawing.Color.Black):
    i = d.Layers.FindByFullPath(path, -1)
    if i >= 0: return i
    parent = -1
    parts = path.split('::')
    for n in range(1, len(parts) + 1):
        p = '::'.join(parts[:n]); j = d.Layers.FindByFullPath(p, -1)
        if j < 0:
            L = Rhino.DocObjects.Layer(); L.Name = parts[n - 1]; L.Color = color; L.PlotColor = color
            if parent >= 0: L.ParentLayerId = d.Layers[parent].Id
            j = d.Layers.Add(L)
        parent = j
    return parent

def _pattern(name, lines):
    i = d.HatchPatterns.Find(name, True)
    if i >= 0: return i
    hp = Rhino.DocObjects.HatchPattern(); hp.Name = name; hp.FillType = Rhino.DocObjects.HatchPatternFillType.Lines
    for ang, (ox, oy), dash in lines:                  # .pat 한 줄과 같은 뜻: 각도, (줄 방향 이동, 줄 간격), 대시
        hl = Rhino.DocObjects.HatchLine(); hl.Angle = math.radians(ang); hl.BasePoint = Point2d(0, 0); hl.Offset = Vector2d(ox, oy)
        for x in dash: hl.AppendDash(x)
        hp.AddHatchLine(hl)
    return d.HatchPatterns.Add(hp)

def _ensure_patterns():
    L, h, j = BRICK; c = h + j; m = L + j
    _pattern('S-BRICK', [(0, (0, c), []), (90, (c, m / 2.0), [c, -c])])   # 가로 줄눈 + 켜마다 반장 어긋난 세로 줄눈
    w = BRICK_W + j
    _pattern('S-BRICK-PLAN', [(0, (0, w), []), (90, (w, m / 2.0), [w, -w])])   # 평면: 벽 방향 줄(폭 간격) + 반장 어긋난 맞댄 줄눈
    src = {}
    for f in PAT_FILES:
        if os.path.exists(f):
            for hp in Rhino.DocObjects.HatchPattern.ReadFromFile(f, True) or []: src.setdefault(hp.Name, hp)
    for k, plan in [(k, False) for k in HATCH] + [(k, True) for k in HATCH_PLAN]:
        for name, orig, s, unit in _pats(k, plan):
            if not orig or name == 'SOLID' or d.HatchPatterns.Find(name, True) >= 0: continue
            if orig in src: hp = src[orig]; hp.Name = name; d.HatchPatterns.Add(hp)
            else: _pattern(name, FALLBACK[name])

def _mode(name=None):
    modes = {m.EnglishName: m for m in Rhino.Display.DisplayModeDescription.GetDisplayModes()}
    if name:                                              # CFG['display'] = 사용자 표시 모드 이름 (그대로 씀, 바꾸지 않음)
        if name in modes: return modes[name]
        print('display mode not found:', name)
    if MODE in modes: dm = modes[MODE]
    else:
        dm = Rhino.Display.DisplayModeDescription.GetDisplayMode(
            Rhino.Display.DisplayModeDescription.CopyDisplayMode(modes['Technical'].Id, MODE))
    at = dm.DisplayAttributes
    at.ShowClippingEdges = False; at.ShowClipIntersectionEdges = False   # 블록마다 그리는 지저분한 단면선 끔
    at.ShowClipIntersectionSurfaces = False; at.ShowClippingFills = False
    Rhino.Display.DisplayModeDescription.UpdateDisplayMode(dm)
    return dm

def _model_view():
    # 페이지가 활성인 채로 객체를 만들면 페이지 공간·디테일 숨김으로 들어감 → 항상 모델 뷰를 먼저 활성화
    v = d.Views.Find('Perspective', False) or [x for x in d.Views if not isinstance(x, Rhino.Display.RhinoPageView)][0]
    d.Views.ActiveView = v
    return v

AXIS = {'x': 0, 'y': 1, 'z': 2}                         # 'z' = 평면 (수평 절단)

def _axis(cfg):
    ax = cfg.get('axis', 'x'); i = AXIS[ax]; c = float(cfg['cut'])
    n = Vector3d(*[1 if j == i else 0 for j in range(3)])
    o = Point3d(*[c if j == i else 0 for j in range(3)])
    return ax, i, c, n, o

def _span(b, i): return (b.Min[i], b.Max[i])

HOLES = collections.defaultdict(list)                 # _cut 이 채움: 재질별 속 빈 단면의 안쪽 고리
GROUPS = collections.defaultdict(list)                # _cut 이 채움: 재질별 [덩어리마다 닫힌 고리들]


def _material_regions(groups, pl, tol):
    """속 빈 단면까지 맞게 합치기: 모든 고리로 평면을 영역으로 나누고(CreateBooleanRegions), 영역 안의 점이
    어느 덩어리의 고리 안에 홀수 번 들면 재질. 재질 영역끼리 이웃하면 합침. → 바깥·안쪽 고리 목록 (해치는 홀짝으로 비움)"""
    allc = [c for g in groups for c in g]
    if not allc: return []
    IN = Rhino.Geometry.PointContainment.Inside
    try: R = Rhino.Geometry.Curve.CreateBooleanRegions(allc, pl, False, tol)
    except Exception: return None
    if R is None: return None
    pts = []
    for i in range(R.RegionCount):
        loops = list(R.RegionCurves(i)); br = Rhino.Geometry.Brep.CreatePlanarBreps(loops, tol)
        if not br: continue
        f = br[0].Faces[0]; du, dv = f.Domain(0), f.Domain(1); pt = None
        for su in (0.5, 0.3, 0.7, 0.15, 0.85):
            for sv in (0.5, 0.3, 0.7, 0.15, 0.85):
                u_, v_ = du.ParameterAt(su), dv.ParameterAt(sv)
                if f.IsPointOnFace(u_, v_) == Rhino.Geometry.PointFaceRelation.Interior: pt = f.PointAt(u_, v_); break
            if pt: break
        if pt is None: continue
        if any(sum(1 for c in g if c.Contains(pt, pl, tol) == IN) % 2 for g in groups): pts.append(pt)
    if not pts: return []
    R2 = Rhino.Geometry.Curve.CreateBooleanRegions(allc, pl, pts, True, tol)
    out = []
    for i in range(R2.RegionCount): out += list(R2.RegionCurves(i))
    return out

ORDER = ['WHITE', 'EARTH', 'CONC', 'MORTAR', 'STONE', 'INSUL', 'BRICK', 'WOOD', 'SOLID', 'STAIR']   # 나중 것이 위 (콘크리트 속 장선 등). 재료 모름은 맨 아래

def section(cfg, ls=None, skip=()):
    """단면선 + 흰 가림 + 재질 해치 + 합친 외곽선을 '페이지 공간'에 그림 (cfg['page'] 의 첫 디테일 위).
    모델 공간에 두면 Technical 벡터 출력의 숨은선 처리가 선(외곽선·X)을 지움 → 페이지 공간이 확실.
    다시 만들 때: clear_layer(path); section(cfg, _layer(path))"""
    _ensure_patterns(); _model_view()
    ls = _layer(LYR_SEC + '::' + cfg['page']) if ls is None else ls
    page = [v for v in d.Views.GetPageViews() if v.PageName == cfg['page']][0]
    det = list(page.GetDetailViews())[cfg.get('detail', 0)]
    xf = Transform.PlanarProjection(Plane.WorldXY) * det.WorldToPageTransform   # 모델 → 종이 (z=0)
    pid = page.MainViewport.Id
    ax = cfg.get('axis', 'x'); c = float(cfg['cut'])
    scale = float(cfg.get('scale', 100)); tol = d.ModelAbsoluteTolerance; ptol = 0.001
    ax, i_, c, n, o = _axis(cfg)
    sec = _cut(cfg, set(skip) | {ls})
    K = System.Drawing.Color.Black; Wt = System.Drawing.Color.White
    def att(col, w=None, z=0):
        x = Rhino.DocObjects.ObjectAttributes(); x.LayerIndex = ls; x.Space = Rhino.DocObjects.ActiveSpace.PageSpace; x.ViewportId = pid
        x.DisplayOrder = 10 + ORDER.index(k) * 4 + z      # 그리기 순서 직접 지정 (만든 순서를 안 따름): 재질 순서 × (가림·해치·X·외곽선)
        x.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject; x.ObjectColor = col
        x.PlotColorSource = Rhino.DocObjects.ObjectPlotColorSource.PlotColorFromObject; x.PlotColor = col
        if w is not None:
            x.PlotWeightSource = Rhino.DocObjects.ObjectPlotWeightSource.PlotWeightFromObject; x.PlotWeight = w
        return x
    def P(g): g = g.Duplicate(); g.Transform(xf); return g
    bp = xf * Point3d(o.X, o.Y, 0)                            # 벽돌 켜를 z=0 에 맞춤 (Point3d 는 값 형식 → 곱으로 새 점)
    solid = d.HatchPatterns.Find('SOLID', True); stat = {}
    if cfg.get('elev'):                                    # 입면: 잘린 면은 그리지 않고 지반선만 (굵게, 건물 양옆 3 m 더)
        k = 'STAIR'; bb = cfg['_bb']; g0 = float(cfg.get('ground', 0.0))
        if ax == 'y': p1, p2 = Point3d(bb.Min.X - 3000, c, g0), Point3d(bb.Max.X + 3000, c, g0)
        else: p1, p2 = Point3d(c, bb.Min.Y - 3000, g0), Point3d(c, bb.Max.Y + 3000, g0)
        a1, a2 = xf * p1, xf * p2
        if cfg.get('below_ground_mask', True):              # 지반선 아래(기초·땅속 선)는 흰색으로 가림
            yb = min(a1.Y, a2.Y) - 200.0
            rect = Rhino.Geometry.PolylineCurve([Point3d(a1.X, a1.Y, 0), Point3d(a2.X, a2.Y, 0), Point3d(a2.X, yb, 0), Point3d(a1.X, yb, 0), Point3d(a1.X, a1.Y, 0)])
            hb = d.Objects.FindId(det.Id).Geometry.GetBoundingBox(True) if d.Objects.FindId(det.Id) else None
            if hb is not None and hb.IsValid:                 # 그림 칸 아래 끝까지만
                rect = Rhino.Geometry.PolylineCurve([Point3d(hb.Min.X, a1.Y, 0), Point3d(hb.Max.X, a1.Y, 0), Point3d(hb.Max.X, hb.Min.Y, 0), Point3d(hb.Min.X, hb.Min.Y, 0), Point3d(hb.Min.X, a1.Y, 0)])
            for h in Rhino.Geometry.Hatch.Create([rect], solid, 0.0, 1.0, ptol) or []:
                d.Objects.AddHatch(h, att(Wt, z=0))
        d.Objects.AddLine(a1, a2, att(K, STYLE['ground_w'], 3))
        d.Views.Redraw(); return {'ground': g0}
    for k in [x for x in ORDER if x in sec]:
        cs = sec[k]
        regs = _material_regions(GROUPS.get(k, []), Plane(o, n), tol) if HOLES.get(k) else None   # 속 빈 단면이 있으면 영역 방식
        if not regs:
            u = Rhino.Geometry.Curve.CreateBooleanUnion(cs, tol)   # 블록 이음매 없애기 (보통 경우, 빠름)
            regs = list(u) if u and len(u) > 0 else cs
        if k == 'STAIR':                                    # 평면 계단: 잘린 면 대신 잘림표시 (계단 폭을 비스듬히 가로지르는 지그재그)
            for cv in regs:
                x = _wall_dir(cv)
                am = Rhino.Geometry.AreaMassProperties.Compute(cv)
                if not x or not am: continue
                c0 = xf * am.Centroid
                u_ = xf * Vector3d(math.cos(x['ang']), math.sin(x['ang']), 0); u_.Unitize()   # 잘린 띠의 긴 쪽 = 계단 폭 방향
                n_ = Vector3d(-u_.Y, u_.X, 0)
                t_ = math.radians(BREAK['tilt'])
                b_ = u_ * math.cos(t_) + n_ * math.sin(t_); nb = Vector3d(-b_.Y, b_.X, 0)
                Lb = x['L'] / scale / math.cos(t_) + 2 * BREAK['over']; z_, h_ = BREAK['zig'], BREAK['amp']
                pts_ = [c0 - b_ * (Lb / 2), c0 - b_ * z_, c0 - b_ * (z_ / 3) + nb * h_, c0 + b_ * (z_ / 3) - nb * h_, c0 + b_ * z_, c0 + b_ * (Lb / 2)]
                d.Objects.AddPolyline(Rhino.Geometry.Polyline(pts_), att(K, BREAK['w'], 3))
            stat[k] = (len(cs), len(regs)); continue
        pats = _pats(k, ax == 'z'); fill = pats[0][0] == 'SOLID'
        pregs = [P(cv) for cv in regs]
        for h in Rhino.Geometry.Hatch.Create(pregs, solid, 0.0, 1.0, ptol) or []:   # 1) 흰 가림 (뒤 선 숨김)
            d.Objects.AddHatch(h, att(K if fill else Wt, z=0))
        rest = pregs
        if k == 'WOOD':                                     # 2a) 작은 네모 각재: 대각선 X (건축 관례)
            rest = []
            for cv, pc in zip(regs, pregs):
                ok, pl = cv.TryGetPolyline()
                if ok: pl.MergeColinearSegments(0.02, True)      # 합집합이 남긴 일직선 꼭짓점 제거
                if ok and pl.Count == 5 and max(pl.SegmentAt(i).Length for i in range(4)) < WOOD_X:
                    for a_, b_ in ((0, 2), (1, 3)):
                        d.Objects.AddCurve(P(Rhino.Geometry.LineCurve(pl[a_], pl[b_])), att(K, STYLE['hatch_w'], 2))
                else: rest.append(pc)
        for name, orig, s, unit in pats:                    # 2) 재질 해치 (여러 개면 겹침)
            if not name or name == 'SOLID' or not rest: continue
            sp = s / scale if unit == 'model' else s         # 페이지 공간: 패턴 1단위 × 스케일 = 종이 mm
            if name in ALONG:                               # 벽 조각마다 긴 변 방향으로 무늬 회전. 겹친 곳은 먼저(큰 조각) 깐 것 우선
                hp = d.HatchPatterns.Find(name, True)
                info = [_wall_dir(cv) for cv in cs]         # 모델 평면 좌표에서: 각도·폭·길이·기준점
                info = [x for x in info if x]
                T = [x['w'] for x in info if x['L'] / max(x['w'], 1e-6) >= 1.8]   # 긴 벽들의 두께 = 벽 두께 목록
                longs = [x for x in info if x['L'] / max(x['w'], 1e-6) >= 1.8]
                for x in info:                              # 짧은 벽기둥: 두께와 같은 변이 두께, 나머지가 벽 방향
                    if x['L'] / max(x['w'], 1e-6) >= 1.8: continue
                    isT = lambda v: any(abs(v - t) < 40 for t in T)
                    if isT(x['w']) and not isT(x['L']): pass                       # 지금 방향(긴 변) 그대로
                    elif isT(x['L']) and not isT(x['w']): x['ang'] += math.pi / 2  # 긴 변이 두께 → 짧은 변 방향
                    elif longs:                             # 모르면 가장 가까운 긴 벽 방향 중 가까운 직각으로
                        c0 = x['base']
                        def dist(y):
                            ok, t = y['cv'].ClosestPoint(c0); return c0.DistanceTo(y['cv'].PointAt(t)) if ok else 1e18
                        y = min(longs, key=dist)
                        dd = (y['ang'] - x['ang']) % math.pi
                        x['ang'] += (math.pi / 2 if math.pi / 4 < dd < 3 * math.pi / 4 else 0)
                done = []
                for x in sorted(info, key=lambda x: -x['A']):
                    cv = x['cv']
                    bb = cv.GetBoundingBox(True); near = [q for q in done if Rhino.Geometry.BoundingBox.Intersection(bb, q.GetBoundingBox(True)).IsValid]
                    done.append(cv)
                    for sub, ang, base in _wall_parts(x, tol):   # ㄱ·T 자 조각은 갈래별 방향
                        parts = [sub]
                        if near:                            # 겹친 곳은 먼저(큰 조각) 깐 것 우선 — 주변 조각만 뺌
                            df = Rhino.Geometry.Curve.CreateBooleanDifference(sub, near, tol)
                            parts = [sub] if df is None else list(df)
                        if not parts: continue
                        dv = xf * Vector3d(math.cos(ang), math.sin(ang), 0)     # 모델 방향 → 종이 방향
                        for h in Rhino.Geometry.Hatch.Create([P(q) for q in parts], hp, 0.0, sp, ptol) or []:
                            pl = h.Plane; h.PatternRotation = Vector3d.VectorAngle(pl.XAxis, dv, pl); h.BasePoint = xf * base
                            d.Objects.AddHatch(h, att(K, STYLE['hatch_w'], 1))
                continue
            for h in Rhino.Geometry.Hatch.Create(rest, d.HatchPatterns.Find(name, True), 0.0, sp, ptol) or []:
                pl = h.Plane                                # 패턴 0°를 종이 가로로
                h.PatternRotation = Vector3d.VectorAngle(pl.XAxis, Vector3d.XAxis, pl); h.BasePoint = bp
                d.Objects.AddHatch(h, att(K, STYLE['hatch_w'], 1))
        for pc in pregs:                                                              # 3) 합친 외곽선
            am = Rhino.Geometry.AreaMassProperties.Compute(pc)
            t = 2 * am.Area / pc.GetLength() if am else 0       # 띠 두께 ≈ 2·면적/둘레
            d.Objects.AddCurve(pc, att(K, next(w for lim, w in STYLE['cut_w'] if t < lim), 3))
        stat[k] = (len(cs), len(regs))
    if ax == 'z' and cfg.get('stair_marks', True):         # 평면 계단: 아래로 내려가는 디딤판 + UP/DN 화살표
        stat['stairs'] = _stair_marks(cfg, xf, ls, pid, scale, set(skip) | {ls})
    d.Views.Redraw()
    return stat

# 평면 계단 표시: 디딤판 = 계단 객체의 위를 향한 수평 면. 화살표는 디딤판 중심을 높이순으로 이음 (곡선계단도 따라 휨)
STAIR_MARK = dict(label=('UP', 'DN'), text_h=1.8, head=1.4, dot=0.45, w=0.18, min_tread=20000)   # label=None 이면 글자 없이 화살표만

def _treads(g):
    br = g.ToBrep() if isinstance(g, (Rhino.Geometry.Extrusion, Rhino.Geometry.SubD)) else (g if isinstance(g, Rhino.Geometry.Brep) else None)
    if br is None: return []
    br = br.DuplicateBrep(); br.Faces.SplitKinkyFaces(math.radians(1), True)   # 톱니 단면을 밀어낸 계단: 꺾인 한 면 → 디딤판·챌면으로 나눔
    up, dn = [], []
    for f in br.Faces:
        ok, pl = f.TryGetPlane(0.5)
        if not ok: continue
        nv = f.NormalAt(f.Domain(0).Mid, f.Domain(1).Mid)
        if f.OrientationIsReversed: nv = -nv
        if abs(nv.Z) < 0.95: continue                       # 수평 면만
        df = f.DuplicateFace(False); am = Rhino.Geometry.AreaMassProperties.Compute(df)
        if not am or am.Area < STAIR_MARK['min_tread']: continue   # 너무 작은 면(모서리 등) 제외, mm²
        loops = [lp.To3dCurve() for lp in f.Loops if lp.LoopType == Rhino.Geometry.BrepLoopType.Outer]
        (up if nv.Z > 0 else dn).append((am.Centroid, loops))
    if len(up) >= 2: return up                              # 디딤판 = 위를 향한 수평 면
    return dn if len(dn) >= 2 else up                       # 예비: 위아래 뒤집혀 모델링된 계단 (톱니가 아래)

def _stair_marks(cfg, xf, ls, pid, scale, skip):
    c = float(cfg['cut']); floor = float(cfg.get('floor', c - 1200))   # 이 층 바닥 (기본: 자른 높이 - 1.2 m)
    K = System.Drawing.Color.Black; G = System.Drawing.Color.FromArgb(*STYLE['beyond_rgb'])
    def att(col, w):
        x = Rhino.DocObjects.ObjectAttributes(); x.LayerIndex = ls; x.Space = Rhino.DocObjects.ActiveSpace.PageSpace; x.ViewportId = pid
        x.DisplayOrder = 100; x.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject; x.ObjectColor = col
        x.PlotColorSource = Rhino.DocObjects.ObjectPlotColorSource.PlotColorFromObject; x.PlotColor = col
        x.PlotWeightSource = Rhino.DocObjects.ObjectPlotWeightSource.PlotWeightFromObject; x.PlotWeight = w; return x
    S = STAIR_MARK; n_up = n_dn = 0
    for top in list(d.Objects):
        if top.Attributes.LayerIndex in skip or top.Attributes.Space != Rhino.DocObjects.ActiveSpace.ModelSpace: continue
        try: b0 = top.Geometry.GetBoundingBox(False)
        except: continue
        if b0.Max.Z < floor - 6000 or b0.Min.Z > c + 6000: continue
        for g, X, lp, el in _leaves(top):
            if not _is_stair(lp, el): continue
            if X is not None: g = g.Duplicate(); g.Transform(X)
            tr = sorted(_treads(g), key=lambda t: t[0].Z)
            if len(tr) < 2: continue
            z0, z1 = tr[0][0].Z, tr[-1][0].Z
            if z0 <= c < z1 and z0 >= floor - 300:            # 이 층에서 올라감: 바닥 → 잘린 자리까지 UP
                path = [t[0] for t in tr if t[0].Z <= c]; lab = S['label'][0] if S['label'] else None; n_up += 1
            elif z1 <= c and z1 >= floor - 300:              # 이 층에서 내려감: 디딤판 윤곽 직접 그림 + 위 → 아래 DN
                for _, loops in tr:
                    for lc_ in loops:
                        q = lc_.DuplicateCurve(); q.Transform(xf); d.Objects.AddCurve(q, att(G, STYLE['beyond_w']))
                path = [t[0] for t in reversed(tr)]; lab = S['label'][1] if S['label'] else None; n_dn += 1
            else: continue
            pp = [xf * p for p in path]
            pp2 = [pp[0]]                                     # 너무 가까운 점 정리
            for p in pp[1:]:
                if p.DistanceTo(pp2[-1]) > 0.5: pp2.append(p)
            if len(pp2) < 2: continue
            d.Objects.AddPolyline(Rhino.Geometry.Polyline(pp2), att(K, S['w']))
            d.Objects.AddCircle(Rhino.Geometry.Circle(pp2[0], S['dot']), att(K, S['w']))   # 시작점
            v = pp2[-1] - pp2[-2]; v.Unitize()
            for sgn in (1, -1):                               # 화살촉
                r = Transform.Rotation(math.radians(25 * sgn), Vector3d.ZAxis, pp2[-1])
                h = pp2[-1] - v * S['head']; h.Transform(r); d.Objects.AddLine(pp2[-1], h, att(K, S['w']))
            if lab:                                           # 글자: 시작 동그라미 바로 뒤(화살표 반대쪽), 글자 가운데를 화살표 선에 맞춤
                v0 = pp2[1] - pp2[0]; v0.Unitize(); bk = -v0
                te = Rhino.Geometry.TextEntity(); te.PlainText = lab; te.TextHeight = S['text_h']
                te.Plane = Plane(pp2[0] + bk * (S['dot'] + S['text_h'] * 0.35), Vector3d.ZAxis)
                H, Vt = Rhino.DocObjects.TextHorizontalAlignment, Rhino.DocObjects.TextVerticalAlignment
                if abs(bk.X) >= abs(bk.Y):                    # 화살표가 가로: 글자를 좌우로 붙이고 세로 가운데
                    te.TextHorizontalAlignment = H.Left if bk.X > 0 else H.Right; te.TextVerticalAlignment = Vt.Middle
                else:                                         # 세로: 위아래로 붙이고 가로 가운데
                    te.TextHorizontalAlignment = H.Center; te.TextVerticalAlignment = Vt.Bottom if bk.Y > 0 else Vt.Top
                d.Objects.AddText(te, att(K, S['w']))
    return (n_up, n_dn)

def elevation(cfg):
    """입면도: cfg['facing'] = 'S'|'N'|'E'|'W' (그 면을 바깥에서 봄). 건물 범위를 재질 있는 객체로 구해
    면 바로 바깥(margin)에 단면판을 세우고 build. 잘린 면 없이 지반선만. ground 기본 = 흙(EARTH) 객체 윗면, 없으면 0"""
    boxes = []; gz = []
    for ob in d.Objects:
        if ob.Attributes.Space != Rhino.DocObjects.ActiveSpace.ModelSpace or ob.Geometry is None: continue
        lp = d.Layers[ob.Attributes.LayerIndex].FullPath
        if lp.startswith(TAG): continue
        k = kind(lp, ob.Attributes.GetUserString('element') or '')
        try: b = ob.Geometry.GetBoundingBox(False)
        except: continue
        if k == 'EARTH': gz.append(b.Max.Z)
        elif k not in (None, 'WHITE'): boxes.append(b)
    bb = BoundingBox.Empty                                  # 멀리 떨어진 담장·대지 객체는 빼고 건물 범위 (중심 5~95 % ± 20 %)
    if boxes:
        lim = []
        for j in (0, 1):
            cs_ = sorted(b.Center[j] for b in boxes); p5, p95 = cs_[int(len(cs_) * .05)], cs_[max(int(len(cs_) * .95) - 1, 0)]
            r = p95 - p5; lim.append((p5 - .2 * r, p95 + .2 * r))
        for b in boxes:
            if all(lim[j][0] <= b.Center[j] <= lim[j][1] for j in (0, 1)): bb.Union(b)
    if cfg.get('bbox') is not None: bb = cfg['bbox']        # 직접 지정 (BoundingBox)
    m = float(cfg.get('margin', 1000))
    f = cfg.get('facing', 'S').upper()
    cfg['axis'], cfg['look'], cfg['cut'] = {'S': ('y', 1, bb.Min.Y - m), 'N': ('y', -1, bb.Max.Y + m),
                                            'W': ('x', 1, bb.Min.X - m), 'E': ('x', -1, bb.Max.X + m)}[f]
    ext = (bb.Max.Y - bb.Min.Y) if cfg['axis'] == 'y' else (bb.Max.X - bb.Min.X)
    cfg.setdefault('depth', ext + 2 * m)                    # 깊이판으로 건물 뒤를 막음 (없으면 벡터 PDF 숨은선 계산이 사이트 전체로 번져 빈 출력)
    cfg.setdefault('ground', sorted(gz)[len(gz) // 2] if gz else 0.0)
    cfg['elev'] = True; cfg['_bb'] = bb
    return build(cfg)

def _wall_dir(cv):
    """평면 벽 조각(모델 XY)의 벽 방향: 직선 변을 길이로 가중한 각도(180° 주기, 1° 칸 → 그 칸 안 평균).
    직선이 없으면(곡면 벽) 가장 작은 회전 사각형. 돌려준 값: 각도 ang(긴 쪽), 길이 L, 폭 w, 넓이 A, 기준점 base(사각형 모서리)"""
    segs = [s_ for s_ in (cv.DuplicateSegments() or []) if s_.IsLinear(0.01)]
    pts = [s_.PointAtStart for s_ in (cv.DuplicateSegments() or [cv])]
    ts = cv.DivideByCount(48, True)
    if ts: pts += [cv.PointAt(t) for t in ts]
    if len(pts) < 3: return None
    def ext(r):
        ux, uy = math.cos(r), math.sin(r)
        us = [p.X * ux + p.Y * uy for p in pts]; vs = [-p.X * uy + p.Y * ux for p in pts]
        return max(us) - min(us), max(vs) - min(vs), min(us), min(vs)
    if segs:
        hist = collections.defaultdict(float)
        for s_ in segs:
            v = s_.PointAtEnd - s_.PointAtStart; a = math.atan2(v.Y, v.X) % math.pi
            hist[int(math.degrees(a)) % 180] += s_.GetLength()
        b0 = max(hist, key=hist.get)
        acc = [(math.atan2((s_.PointAtEnd - s_.PointAtStart).Y, (s_.PointAtEnd - s_.PointAtStart).X) % math.pi, s_.GetLength()) for s_ in segs]
        near = [(a, l) for a, l in acc if min(abs(math.degrees(a) - b0), 180 - abs(math.degrees(a) - b0)) <= 2]
        sx = sum(math.cos(2 * a) * l for a, l in near); sy = sum(math.sin(2 * a) * l for a, l in near)
        r = math.atan2(sy, sx) / 2                          # 180° 주기 평균
    else:
        r = min((math.radians(dg) for dg in range(180)), key=lambda q: ext(q)[0] * ext(q)[1])
    W, H, u0, v0 = ext(r)
    if H > W: r += math.pi / 2; W, H, u0, v0 = ext(r)
    ux, uy = math.cos(r), math.sin(r)
    am = Rhino.Geometry.AreaMassProperties.Compute(cv)
    return dict(cv=cv, ang=r, L=W, w=H, A=am.Area if am else 0, base=Point3d(u0 * ux - v0 * uy, u0 * uy + v0 * ux, pts[0].Z))

def _wall_parts(x, tol):
    """ㄱ·T·+ 자 벽 조각을 갈래별로 나눔: 꼭짓점 좌표로 격자를 만들고, 안쪽 칸마다 가로 연속 길이 vs 세로 연속 길이로
    방향을 정한 뒤 같은 방향 칸끼리 합침. 직교가 아니거나(곡면·사선) 한 칸이면 조각 그대로. → [(곡선, 각도, 기준점)]"""
    cv, r = x['cv'], x['ang']
    one = [(cv, r, x['base'])]
    ok, pl = cv.TryGetPolyline(); curved = not ok
    if curved:                                               # 곡선이 섞인 조각: 잘게 꺾은선으로 바꿔 격자, 나중에 원래 곡선으로 잘라냄
        pc = cv.ToPolyline(5.0, math.radians(5), 0, 0)
        if pc is None: return one
        ok, pl = pc.TryGetPolyline()
        if not ok: return one
    pl.MergeColinearSegments(0.02, True)
    ux, uy = math.cos(r), math.sin(r)
    orth = tot = 0.0
    for i in range(pl.SegmentCount):                         # r 또는 r+90° 인 변의 길이 비율
        v = pl.SegmentAt(i).Direction; L = v.Length; v.Unitize(); tot += L
        if min(abs(v.X * ux + v.Y * uy), abs(-v.X * uy + v.Y * ux)) <= 0.02: orth += L
    if tot == 0 or orth < (0.7 if curved else 0.999) * tot: return one   # 둥근 벽·사선 벽은 한 방향
    if curved:                                               # 꺾은선 꼭짓점 중 직교 변의 끝점만 격자에 씀 (곡선 쪽 잔칸 방지)
        keep = []
        for i in range(pl.SegmentCount):
            s_ = pl.SegmentAt(i); v = s_.Direction; v.Unitize()
            if min(abs(v.X * ux + v.Y * uy), abs(-v.X * uy + v.Y * ux)) <= 0.02: keep += [s_.From, s_.To]
        pl = Rhino.Geometry.Polyline(keep)
    z = pl[0].Z
    U = lambda p: p.X * ux + p.Y * uy
    V = lambda p: -p.X * uy + p.Y * ux
    W = lambda u, v: Point3d(u * ux - v * uy, u * uy + v * ux, z)
    def uniq(a):
        out = []
        for q in sorted(a):
            if not out or q - out[-1] > 1.0: out.append(q)
        return out
    us = uniq([U(p) for p in pl]); vs = uniq([V(p) for p in pl])
    if len(us) <= 2 and len(vs) <= 2: return [(cv, r, x['base'])]
    nu, nv = len(us) - 1, len(vs) - 1
    pz = Plane(Point3d(0, 0, z), Vector3d.ZAxis)
    ins = [[cv.Contains(W((us[i] + us[i + 1]) / 2, (vs[j] + vs[j + 1]) / 2), pz, tol) == Rhino.Geometry.PointContainment.Inside
            for j in range(nv)] for i in range(nu)]
    groups = {0: [], 1: []}                                  # 0 = r 방향(가로 연속이 긴 칸), 1 = r+90°
    for i in range(nu):
        for j in range(nv):
            if not ins[i][j]: continue
            a = i
            while a > 0 and ins[a - 1][j]: a -= 1
            b = i
            while b < nu - 1 and ins[b + 1][j]: b += 1
            c = j
            while c > 0 and ins[i][c - 1]: c -= 1
            e = j
            while e < nv - 1 and ins[i][e + 1]: e += 1
            hu, hv = us[b + 1] - us[a], vs[e + 1] - vs[c]
            groups[0 if hu >= hv else 1].append((i, j))
    out = []; regs_g = {}
    for g, cells in groups.items():
        if not cells: continue
        rects = [Rhino.Geometry.PolylineCurve([W(us[i], vs[j]), W(us[i + 1], vs[j]), W(us[i + 1], vs[j + 1]), W(us[i], vs[j + 1]), W(us[i], vs[j])])
                 for i, j in cells]
        un = Rhino.Geometry.Curve.CreateBooleanUnion(rects, tol)
        regs_g[g] = (list(un) if un and len(un) else rects, W(min(us[i] for i, j in cells), min(vs[j] for i, j in cells)))
    if not regs_g: return one
    if curved:                                               # 원래 곡선 안으로 잘라내고, 남은 곳(곡선 쪽)은 넓은 갈래에 붙임
        allr = [q for rs, b in regs_g.values() for q in rs]
        big = max(regs_g, key=lambda g: sum(abs(Rhino.Geometry.AreaMassProperties.Compute(q).Area) for q in regs_g[g][0]))
        rest = Rhino.Geometry.Curve.CreateBooleanDifference(cv, allr, tol) or []
        for g in regs_g:
            cut_ = []
            for q in regs_g[g][0]:
                cut_ += list(Rhino.Geometry.Curve.CreateBooleanIntersection(q, cv, tol) or [])
            if g == big: cut_ += list(rest)
            regs_g[g] = (cut_, regs_g[g][1])
    for g, (rs, base) in regs_g.items():
        for q in rs:
            out.append((q, r + g * math.pi / 2, base))
    return out or one

def _leaves(ob, X=None, parent=None, depth=0):
    """객체 → (모델 좌표 기하, 레이어 경로, element) 들. 블록(인스턴스)은 정의 속으로 들어가 변환을 곱함 (중첩 8단까지).
    블록 속 객체의 재질은 자기 레이어로 보고, 그게 '재료 모름'이면 블록 객체의 레이어·태그를 씀"""
    a = ob.Attributes
    lp = d.Layers[a.LayerIndex].FullPath; el = a.GetUserString('element') or ''
    if parent and kind(lp, el) == 'WHITE': lp, el = parent
    if isinstance(ob, Rhino.DocObjects.InstanceObject):
        if depth > 8: return
        X2 = ob.InstanceXform if X is None else X * ob.InstanceXform
        for sub in ob.InstanceDefinition.GetObjects() or []:
            for r in _leaves(sub, X2, (lp, el), depth + 1): yield r
    elif ob.Geometry is not None:
        yield ob.Geometry, X, lp, el

def _cut(cfg, skip=()):
    """단면 평면으로 모델을 잘라 재질별 닫힌 곡선 {kind: [curve]} (모델 좌표). 블록 속까지"""
    tol = d.ModelAbsoluteTolerance
    ax, i_, c, n, o = _axis(cfg)
    cut = Plane(o, n)
    sec = collections.defaultdict(list); HOLES.clear(); GROUPS.clear()
    for top in list(d.Objects):
        if top.Attributes.LayerIndex in skip or top.Attributes.Space != Rhino.DocObjects.ActiveSpace.ModelSpace: continue
        try: b0 = top.Geometry.GetBoundingBox(False)
        except: continue
        lo, hi = _span(b0, i_)
        if not (lo < c < hi): continue
        for g, X, lp, el in _leaves(top):
            if X is not None:                               # 블록 속: 변환한 범위로 먼저 거르고 걸리는 것만 복제
                try: b = g.GetBoundingBox(X)
                except: continue
                lo, hi = _span(b, i_)
                if not (lo < c < hi): continue
                g = g.Duplicate(); g.Transform(X)
            k = kind(lp, el)
            if k is None: continue
            if ax == 'z' and cfg.get('stair_break', True) and _is_stair(lp, el): k = 'STAIR'   # 평면 계단 → 잘림표시
            br = g.ToBrep() if isinstance(g, (Rhino.Geometry.Extrusion, Rhino.Geometry.SubD)) else (g if isinstance(g, Rhino.Geometry.Brep) else None)
            if (br is not None and not br.IsSolid) or (isinstance(g, Rhino.Geometry.Mesh) and not g.IsClosed):
                continue                                    # 열린 면은 잘린 면이 안 됨(쐐기·겹선) → Technical 선에 맡김
            cs = []
            if br is not None:
                ok, crv, pts = Rhino.Geometry.Intersect.Intersection.BrepPlane(br, cut, tol)
                if ok and crv: cs = list(Rhino.Geometry.Curve.JoinCurves(crv, tol * 10))
            elif isinstance(g, Rhino.Geometry.Mesh):
                pl = Rhino.Geometry.Intersect.Intersection.MeshPlane(g, cut)
                if pl: cs = [p.ToNurbsCurve() for p in pl]
            cs = [x for x in cs if x.IsClosed]
            if not cs: continue
            GROUPS[k].append(cs)                           # 덩어리별 고리 묶음 (속 빈 단면 판정용)
            for x in cs:                                   # 한 덩어리 안에서 다른 고리에 홀수 번 싸인 고리 = 구멍
                n_in = sum(1 for y in cs if y is not x and y.Contains(x.PointAtStart, cut, tol) == Rhino.Geometry.PointContainment.Inside)
                (HOLES[k] if n_in % 2 else sec[k]).append(x)
    return sec

SCALES = [20, 30, 50, 75, 100, 150, 200, 250, 300, 500]

def remove_page(name):
    """같은 이름으로 다시 만들기 전에: 페이지, 그 디테일 단면판, 페이지 객체, 단면 하위 레이어 객체 지움"""
    for pv in [v for v in d.Views.GetPageViews() if v.PageName == name]:
        vids = set(dt.Viewport.Id for dt in pv.GetDetailViews()); pid = pv.MainViewport.Id
        for ob in list(d.Objects):
            if isinstance(ob, Rhino.DocObjects.ClippingPlaneObject) and set(ob.Geometry.ViewportIds()) <= vids: d.Objects.Delete(ob, True)
            elif ob.Attributes.Space == Rhino.DocObjects.ActiveSpace.PageSpace and ob.Attributes.ViewportId == pid: d.Objects.Delete(ob, True)
        pv.Close()
    clear_layer(LYR_SEC + '::' + name)
    st = sc.sticky.get('secl_state')
    if st and name in st['pages']: st['pages'].remove(name)

def clear_layer(path):
    i = d.Layers.FindByFullPath(path, -1)
    if i >= 0:
        for ob in list(d.Objects.FindByLayer(d.Layers[i])):
            if ob.ObjectType != Rhino.DocObjects.ObjectType.ClipPlane: d.Objects.Delete(ob, True)

# ---- 도각 (CFG['titleblock'] = DWG 경로) ----
# 도각 DWG 를 명령줄 -Import 로 한 번 들여와(대화상자 없음 — 대화상자가 뜨면 MCP 가 300초 멈춤, 겪음) 고정 부분은 블록,
# 칸 글자(아래 TB_FIELDS 의 원래 첫 줄과 같은 글자)는 페이지마다 새 글자로. 값 = CFG['tb'] dict + title·scale·bar1·bar2
TB_PAPER = (420.0, 297.0)
TB_AREA = (8.0, 33.0, 412.0, 289.0)                     # 그림 칸 = 도각 안쪽 틀 (홍익대 A3 도각 기준, 다른 도각이면 CFG['tb_area'])
TB_FIELDS = {'scale 1:100 @A3': 'scale 1:{scale} @A3',   # 원래 글자 첫 줄 → 새 글자 ({…} = 값)
             'Digital Design 2020 Spring': '{project}\n{author}\n{title}',
             'xxx xxx xxxxx': '{phone}', 'xxxx@hongik.ac.kr': '{email}',
             '5.00m': '{bar1}', '10.0m': '{bar2}'}
LYR_TB = TAG + '::도각'

def _tb_template(dwg, fields_map):
    name = '도각_' + os.path.splitext(os.path.basename(dwg))[0]
    cache = sc.sticky.setdefault('secl_tb', {})
    idef = d.InstanceDefinitions.Find(name)
    if idef is not None and name in cache: return idef.Index, cache[name]
    _model_view()                                        # 페이지가 활성이면 페이지 공간으로 들어감
    before = set(o.Id for o in d.Objects); nl = d.Layers.Count
    Rhino.RhinoApp.RunScript('_-Import "%s" _Enter _Enter' % dwg, False)
    new = [o for o in d.Objects if o.Id not in before]
    lt = _layer(LYR_TB); font = Rhino.DocObjects.Font('Arial')
    geoms, attrs, fields = [], [], []
    for o in new:
        g = o.Geometry.Duplicate()
        if isinstance(g, Rhino.Geometry.TextEntity):
            g.Font = font
            if g.PlainText.splitlines()[0].strip() in fields_map: fields.append(g); continue
        a = Rhino.DocObjects.ObjectAttributes(); a.LayerIndex = lt
        geoms.append(g); attrs.append(a)
    if idef is None: d.InstanceDefinitions.Add(name, '도각 (rhino-section-layout)', Point3d.Origin, geoms, attrs)
    for o in new: d.Objects.Delete(o, True)
    for i in range(d.Layers.Count - 1, nl - 1, -1):     # DWG 에서 따라 들어온 빈 레이어 정리
        if not d.Layers[i].IsDeleted and not (d.Objects.FindByLayer(d.Layers[i]) or []): d.Layers.Delete(i, True)
    cache[name] = fields
    return d.InstanceDefinitions.Find(name).Index, fields

def _tb_place(page, cfg, scale):
    fm = dict(TB_FIELDS); fm.update(cfg.get('tb_fields', {}))
    idx, fields = _tb_template(cfg['titleblock'], fm)
    pid = page.MainViewport.Id
    a = Rhino.DocObjects.ObjectAttributes(); a.Space = Rhino.DocObjects.ActiveSpace.PageSpace; a.ViewportId = pid; a.LayerIndex = _layer(LYR_TB)
    d.Objects.AddInstanceObject(idx, Transform.Identity, a)
    v = dict(project='', author='', phone='', email='', date=time.strftime('%Y-%m-%d'))
    v.update(cfg.get('tb', {}))
    v.update(title=(cfg.get('title') or [cfg['page']])[0].replace('{scale}', '%d' % scale), scale='%d' % scale,
             bar1='%.2fm' % (5 * scale / 100.0), bar2='%.1fm' % (10 * scale / 100.0))
    for f in fields:
        te = f.Duplicate(); key = te.PlainText.splitlines()[0].strip()
        te.PlainText = fm[key].format(**v).replace('\n', '\r\n')
        d.Objects.AddText(te, a)

# ---- 도면 기호 (현황도면 스타일) — 크기는 종이 mm ----
SYM = dict(font_ko='Malgun Gothic', font_en='Arial', w=0.18, w_thin=0.09,
           tag_h=1.8, tag_h2=1.4, tag_pad=0.8,                 # 실명 태그: 실명 / 실번호 | F.L
           bub_r=3.2, bub_h=2.2, bub_gap=6.0,                  # 그리드 버블: 반지름·글자·건물에서 떨어진 거리
           lvl_h=1.8, lvl_len=14.0, lvl_tri=1.6,               # 층 레벨: 글자·가로선 길이·삼각형 크기
           north_r=6.0, cut_r=4.0, cut_h=2.6)                  # 방위표, 단면 절단 표시

def _json(v):
    if isinstance(v, str):
        import json, io
        return json.loads(io.open(v, encoding='utf-8').read())
    return v

def _symbols(cfg, page, det, ls, scale, bbm):
    """도면 기호를 페이지 공간에. 평면: 실명 태그(CFG['rooms']+rooms_level)·그리드(CFG['grid'])·방위표(CFG['north'] 도)·
    단면 절단 표시(CFG['cuts']). 단면·입면: 그리드·층 레벨(CFG['levels'] = [(이름, z)])"""
    xf = Transform.PlanarProjection(Plane.WorldXY) * det.WorldToPageTransform
    pid = page.MainViewport.Id; K = System.Drawing.Color.Black; Wt = System.Drawing.Color.White
    solid = d.HatchPatterns.Find('SOLID', True)
    lt_cen = next((d.Linetypes.Find(nm) for nm in ('DashDot', 'Center', 'Dashed') if d.Linetypes.Find(nm) >= 0), -1)
    def att(col=K, w=SYM['w'], z=200, dash=False):
        a = Rhino.DocObjects.ObjectAttributes(); a.LayerIndex = ls; a.Space = Rhino.DocObjects.ActiveSpace.PageSpace; a.ViewportId = pid
        if dash and lt_cen >= 0:
            a.LinetypeSource = Rhino.DocObjects.ObjectLinetypeSource.LinetypeFromObject; a.LinetypeIndex = lt_cen
        a.DisplayOrder = z; a.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject; a.ObjectColor = col
        a.PlotColorSource = Rhino.DocObjects.ObjectPlotColorSource.PlotColorFromObject; a.PlotColor = col
        a.PlotWeightSource = Rhino.DocObjects.ObjectPlotWeightSource.PlotWeightFromObject; a.PlotWeight = w; return a
    H, Vt = Rhino.DocObjects.TextHorizontalAlignment, Rhino.DocObjects.TextVerticalAlignment
    def text(s, p, h, hal=H.Center, val=Vt.Middle, z=202):
        te = Rhino.Geometry.TextEntity(); te.PlainText = s; te.TextHeight = h
        te.Font = Rhino.DocObjects.Font(SYM['font_ko'] if any(ord(ch) > 0x3000 for ch in s) else SYM['font_en'])
        te.Plane = Plane(p, Vector3d.ZAxis); te.TextHorizontalAlignment = hal; te.TextVerticalAlignment = val
        d.Objects.AddText(te, att(z=z)); return te
    def width(s, h): return sum((1.0 if ord(ch) > 0x3000 else 0.6) for ch in s) * h
    def mask(pts, z=199):
        pl = Rhino.Geometry.PolylineCurve(pts + [pts[0]])
        for hh in Rhino.Geometry.Hatch.Create([pl], solid, 0.0, 1.0, 0.001) or []: d.Objects.AddHatch(hh, att(Wt, 0, z))
        d.Objects.AddCurve(pl, att(z=z + 1))
    def P(x, y, z=0): return xf * Point3d(x, y, z)
    lo, hi = xf * bbm.Min, xf * bbm.Max
    px0, px1, py0, py1 = min(lo.X, hi.X), max(lo.X, hi.X), min(lo.Y, hi.Y), max(lo.Y, hi.Y)
    ax = cfg.get('axis', 'x'); n = 0
    placed = []
    def bubble(c, lab, out):                           # out = 건물 바깥쪽 방향. 가까운 버블과 겹치면 한 칸 더 밖으로
        k = 0
        while any(c.DistanceTo(q) < 2 * SYM['bub_r'] + 0.3 for q in placed) and k < 3:
            c = c + out * (2 * SYM['bub_r'] + 0.6); k += 1
        placed.append(c)
        d.Objects.AddCurve(Rhino.Geometry.Circle(c, SYM['bub_r']).ToNurbsCurve(), att(z=201)); text(lab, c, SYM['bub_h'])
        return c
    grid = cfg.get('grid')
    if grid:
        g = _json(grid); g = g.get(cfg.get('rooms_level'), g) if isinstance(g, dict) and 'X' not in g else g
        gap = SYM['bub_gap'] + SYM['bub_r']
        if ax == 'z':                                  # 평면: X 는 위·아래, Y 는 왼쪽·오른쪽 + 가는 일점쇄선
            U, D_, L_, R_ = Vector3d(0, 1, 0), Vector3d(0, -1, 0), Vector3d(-1, 0, 0), Vector3d(1, 0, 0)
            for lab, x in sorted(g.get('X', {}).items(), key=lambda kv: float(kv[1])):
                q = P(float(x), 0); a1 = bubble(Point3d(q.X, py1 + gap, 0), lab, U); a0 = bubble(Point3d(q.X, py0 - gap, 0), lab, D_)
                d.Objects.AddLine(Point3d(q.X, a0.Y + SYM['bub_r'], 0), Point3d(q.X, a1.Y - SYM['bub_r'], 0), att(w=SYM['w_thin'], z=150, dash=True)); n += 1
            for lab, y in sorted(g.get('Y', {}).items(), key=lambda kv: float(kv[1])):
                q = P(0, float(y)); a0 = bubble(Point3d(px0 - gap, q.Y, 0), lab, L_); a1 = bubble(Point3d(px1 + gap, q.Y, 0), lab, R_)
                d.Objects.AddLine(Point3d(a0.X + SYM['bub_r'], q.Y, 0), Point3d(a1.X - SYM['bub_r'], q.Y, 0), att(w=SYM['w_thin'], z=150, dash=True)); n += 1
        else:                                          # 단면·입면: 보이는 쪽 축의 그리드만 아래에
            key = 'Y' if ax == 'x' else 'X'
            for lab, v in g.get(key, {}).items():
                q = P(0, float(v), bbm.Min.Z) if key == 'Y' else P(float(v), 0, bbm.Min.Z)
                b0 = bubble(Point3d(q.X, py0 - gap, 0), lab, Vector3d(0, -1, 0))
                d.Objects.AddLine(Point3d(q.X, b0.Y + SYM['bub_r'], 0), Point3d(q.X, py1 + 3, 0), att(w=SYM['w_thin'], z=150, dash=True)); n += 1
    if ax == 'z':
        rooms = cfg.get('rooms')
        if rooms:                                      # 실명 태그: 위 칸 실명, 아래 칸 실번호 | F.L (흰 바탕)
            for r in _json(rooms):
                if cfg.get('rooms_level') and r.get('level') != cfg['rooms_level']: continue
                c = P(r['x'], r['y']); h1, h2, pd = SYM['tag_h'], SYM['tag_h2'], SYM['tag_pad']
                w1, wn, wf = width(r['name'], h1), width(r['no'], h2), width(r['fl'], h2)
                Wd = max(w1, wn + wf + 3 * pd) + 2 * pd; Hh = h1 + h2 + 4 * pd
                x0, x1, y0, y1 = c.X - Wd / 2, c.X + Wd / 2, c.Y - Hh / 2, c.Y + Hh / 2; ym = y0 + h2 + 2 * pd
                mask([Point3d(x0, y0, 0), Point3d(x1, y0, 0), Point3d(x1, y1, 0), Point3d(x0, y1, 0)])
                d.Objects.AddLine(Point3d(x0, ym, 0), Point3d(x1, ym, 0), att(z=201))
                xs = x0 + 2 * pd + wn
                d.Objects.AddLine(Point3d(xs, y0, 0), Point3d(xs, ym, 0), att(z=201))
                text(r['name'], Point3d(c.X, (ym + y1) / 2, 0), h1)
                text(r['no'], Point3d((x0 + xs) / 2, (y0 + ym) / 2, 0), h2)
                text(r['fl'], Point3d((xs + x1) / 2, (y0 + ym) / 2, 0), h2); n += 1
        if cfg.get('north') is not None:              # 방위표: 그림 칸 오른쪽 위
            ar = cfg['_area']; R = SYM['north_r']; c = Point3d(ar[2] - R - 6, ar[3] - R - 6, 0)
            a = math.radians(float(cfg['north'])); v = Vector3d(-math.sin(a), math.cos(a), 0); nv = Vector3d(-v.Y, v.X, 0)
            d.Objects.AddCurve(Rhino.Geometry.Circle(c, R).ToNurbsCurve(), att())
            tip, tail = c + v * R, c - v * R * 0.7
            for sgn in (1, -1):
                d.Objects.AddLine(tip, c - v * R * 0.35 + nv * (R * 0.45 * sgn), att())
                d.Objects.AddLine(c - v * R * 0.35 + nv * (R * 0.45 * sgn), tail, att())
            text('N', c + v * (R + 2.6), 2.8); n += 1
        off = (SYM['bub_gap'] + 4 * SYM['bub_r'] + 8) if grid else 14   # 그리드 버블 줄 바깥
        for ct in cfg.get('cuts', []):                # 단면 절단 표시: 건물 밖 양끝 동그라미 + 보는 방향 화살 + 이름
            R = SYM['cut_r']; lab = ct.get('name', 'A'); lk = ct.get('look', -1)
            if ct.get('axis', 'x') == 'x':
                q = P(float(ct['at']), 0); e = [Point3d(q.X, py0 - off, 0), Point3d(q.X, py1 + off, 0)]; dv = Vector3d(lk, 0, 0)
            else:
                q = P(0, float(ct['at'])); e = [Point3d(px0 - off, q.Y, 0), Point3d(px1 + off, q.Y, 0)]; dv = Vector3d(0, lk, 0)
            for i, c in enumerate(e):
                d.Objects.AddCurve(Rhino.Geometry.Circle(c, R).ToNurbsCurve(), att(w=0.25))
                inward = e[1 - i] - c; inward.Unitize()
                d.Objects.AddLine(c + inward * R, c + inward * (R + 6), att(w=0.35))
                tri = [c + dv * (R + 2.5) + inward * 0.0, c + dv * R + inward * 1.2, c + dv * R - inward * 1.2]
                mask([Point3d(t.X, t.Y, 0) for t in tri], z=203)
                text(lab + ("'" if i else ''), c, SYM['cut_h'])
            n += 1
    else:
        lv = cfg.get('levels')
        if lv:                                         # 층 레벨: 그림 왼쪽 밖에 가로선 + ▽ + '이름' (현황도면: 2F F.L (G.L+4,475))
            for name, z in lv:
                q = P(bbm.Center.X, bbm.Center.Y, float(z)); y = q.Y; x1 = px0 - 4
                x0 = x1 - max(SYM['lvl_len'], width(name, SYM['lvl_h']) + 3 + 2 * SYM['lvl_tri'] + 2)   # 글자가 벽에 안 닿게
                d.Objects.AddLine(Point3d(x0, y, 0), Point3d(x1, y, 0), att(w=SYM['w_thin'], z=150))   # 왼쪽 짧은 선만
                t = SYM['lvl_tri']
                mask([Point3d(x0 + 3, y, 0), Point3d(x0 + 3 - t, y + 1.4 * t, 0), Point3d(x0 + 3 + t, y + 1.4 * t, 0)], z=203)
                tx0 = x0 + 3 + t + 1; tw = width(name, SYM['lvl_h'])
                pl = Rhino.Geometry.PolylineCurve([Point3d(tx0 - 0.3, y + 0.4, 0), Point3d(tx0 + tw + 0.3, y + 0.4, 0), Point3d(tx0 + tw + 0.3, y + 0.9 + SYM['lvl_h'] * 1.15, 0), Point3d(tx0 - 0.3, y + 0.9 + SYM['lvl_h'] * 1.15, 0), Point3d(tx0 - 0.3, y + 0.4, 0)])
                for hh in Rhino.Geometry.Hatch.Create([pl], solid, 0.0, 1.0, 0.001) or []: d.Objects.AddHatch(hh, att(Wt, 0, 201))   # 글자 흰 바탕 (흙 해치 위)
                text(name, Point3d(tx0, y + 0.8, 0), SYM['lvl_h'], H.Left, Vt.Bottom); n += 1
    return n

def build(cfg):
    st = sc.sticky.setdefault('secl_state', {'layers': {}, 'objs': {}, 'pages': []})
    _ensure_patterns(); dm = _mode(cfg.get('display')); mv = _model_view()
    ax = cfg.get('axis', 'x'); c = float(cfg['cut']); look = cfg.get('look', -1); depth = float(cfg.get('depth', 0))
    scale = cfg.get('scale', 'auto'); scale = scale if scale == 'auto' else float(scale); tol = d.ModelAbsoluteTolerance
    ax, i_, c, n, o = _axis(cfg)
    vdir = Vector3d(n); vdir *= look                       # 카메라 → 장면 방향
    lc = _layer(LYR_CLIP); ls = _layer(LYR_SEC)
    a = Rhino.DocObjects.ObjectAttributes(); a.LayerIndex = lc; a.Space = Rhino.DocObjects.ActiveSpace.ModelSpace
    # ---- 레이아웃 ----
    tb = cfg.get('titleblock')
    W, H = TB_PAPER if tb else cfg.get('paper', (420.0, 297.0))
    page = d.Views.AddPageView(cfg['page'], W, H); st['pages'].append(cfg['page'])
    proj = {('x', -1): Rhino.Display.DefinedViewportProjection.Right, ('x', 1): Rhino.Display.DefinedViewportProjection.Left,
            ('y', 1): Rhino.Display.DefinedViewportProjection.Front, ('y', -1): Rhino.Display.DefinedViewportProjection.Back,
            ('z', -1): Rhino.Display.DefinedViewportProjection.Top, ('z', 1): Rhino.Display.DefinedViewportProjection.Bottom}[(ax, look)]
    side = cfg.get('side', 96.0)                          # 오른쪽 글 칸 폭 (도판 규칙: 글은 그림 밖) — 도각 모드에선 안 씀
    if tb:
        x0, y0, x1, y1 = cfg.get('tb_area', TB_AREA); AR = (x0 + 2, y0 + 2, x1 - 2, y1 - 2)   # 도각 안쪽 틀
    else:
        AR = (12.0, 12.0, W - side - 4, H - 12.0)
    det = page.AddDetailView('section', Point2d(AR[0], AR[1]), Point2d(AR[2], AR[3]), proj)
    # 카메라 중심·축척: 실제로 잘린 단면 곡선 범위 (땅·흰 덩어리 빼고). 길게 뻗은 객체 하나에 끌려가지 않음
    bb = BoundingBox.Empty
    if cfg.get('_bb') is not None: bb = cfg['_bb']             # 입면: 건물 전체 범위
    else:
        for k, cs in _cut(cfg, (lc, ls)).items():
            if k in ('EARTH', 'WHITE'): continue
            for cv in cs: bb.Union(cv.GetBoundingBox(True))
    tgt = bb.Center
    if not cfg.get('elev'): tgt = Point3d(*[c if j == i_ else tgt[j] for j in range(3)])   # 입면은 건물 중심을 봄 (단면판에 두면 먼 쪽이 시야 밖)
    u_, v_ = {'x': (1, 2), 'y': (0, 2), 'z': (0, 1)}[ax]   # 종이 가로·세로가 되는 모델 축
    if scale == 'auto':                                   # 그림 칸에 90 % 로 들어가는 가장 큰 표준 축척
        dw, dh = (AR[2] - AR[0]) * 0.9, (AR[3] - AR[1]) * 0.9
        mw = bb.Max[u_] - bb.Min[u_]; mh = bb.Max[v_] - bb.Min[v_]
        scale = next((s_ for s_ in SCALES if mw / s_ <= dw and mh / s_ <= dh), SCALES[-1])
        cfg['scale'] = scale; print('scale 1:%d' % scale)
    det = list(page.GetDetailViews())[0]
    vp = det.Viewport; vp.DisplayMode = dm
    vp.SetCameraLocations(tgt, tgt - vdir * 50000); vp.CameraUp = Vector3d(0, 1, 0) if ax == 'z' else Vector3d(0, 0, 1)
    det.CommitViewportChanges()                           # ← 이게 없으면 디테일 변경이 저장 안 됨
    det = list(page.GetDetailViews())[0]
    det.DetailGeometry.SetScale(scale, d.ModelUnitSystem, 1, d.PageUnitSystem)
    det.DetailGeometry.IsProjectionLocked = True; det.CommitChanges()
    det = list(page.GetDetailViews())[0]
    # 단면판: 법선 = 보는 방향 → 카메라 쪽(앞) 제거. 깊이판: 법선 = 반대 → 뒤 제거. 이 디테일에만 (모델 뷰는 안 잘림)
    d.Objects.AddClippingPlane(Plane(o, vdir), 1e6, 1e6, [det.Viewport.Id], a)
    if depth > 0:
        d.Objects.AddClippingPlane(Plane(o + vdir * depth, -vdir), 1e6, 1e6, [det.Viewport.Id], a)
    da = det.Attributes.Duplicate(); da.PlotWeightSource = Rhino.DocObjects.ObjectPlotWeightSource.PlotWeightFromObject; da.PlotWeight = -1
    d.Objects.ModifyAttributes(det, da, True)            # 디테일 테두리 출력 안 함
    stat = section(cfg, _layer(LYR_SEC + '::' + cfg['page']), (lc, ls))   # 페이지마다 하위 레이어
    cfg['_area'] = AR
    if any(cfg.get(k) for k in ('rooms', 'grid', 'levels', 'cuts')) or cfg.get('north') is not None:
        stat['symbols'] = _symbols(cfg, page, det, _layer(LYR_SEC + '::' + cfg['page']), scale, bb)
    if tb:                                                # 도각: 도면명·축척은 도각 띠에만 (그림 칸에 글자 없음)
        _tb_place(page, cfg, scale); d.Views.Redraw()
        print('section', stat, 'page', cfg['page']); return stat
    # ---- 제목 칸 (페이지 공간, 명시) ----
    pid = page.MainViewport.Id
    def pa():
        x = Rhino.DocObjects.ObjectAttributes(); x.Space = Rhino.DocObjects.ActiveSpace.PageSpace; x.ViewportId = pid; x.LayerIndex = ls; return x
    d.Objects.AddPolyline(Rhino.Geometry.Polyline([Point3d(8, 8, 0), Point3d(W - 8, 8, 0), Point3d(W - 8, H - 8, 0), Point3d(8, H - 8, 0), Point3d(8, 8, 0)]), pa())
    d.Objects.AddLine(Point3d(W - side, 8, 0), Point3d(W - side, H - 8, 0), pa())
    y = H - 27
    for i, s in enumerate(cfg.get('title', [])):
        h = 4.5 if i == 0 else 2.3
        if s:
            s = s.replace('{scale}', '%d' % scale)          # 제목에 '축척 1:{scale}' 로 쓰면 자동 축척이 들어감
            te = Rhino.Geometry.TextEntity(); te.Plane = Plane(Point3d(W - side + 6, y, 0), Vector3d.ZAxis); te.PlainText = s; te.TextHeight = h
            d.Objects.AddText(te, pa())
        y -= h * 2.2
    d.Views.Redraw()
    print('section', stat, 'page', cfg['page'])
    return stat

def plot_style():
    """출력색(CTB 대신): 모델 레이어 출력색 회색·0.13, 객체 출력색은 레이어 따름. 원래 값은 sticky 에 기억"""
    st = sc.sticky.setdefault('secl_state', {'layers': {}, 'objs': {}, 'pages': []})
    G = System.Drawing.Color.FromArgb(*STYLE['beyond_rgb'])
    for i in range(d.Layers.Count):
        L = d.Layers[i]
        if L.IsDeleted or L.FullPath.startswith(TAG): continue
        st['layers'].setdefault(L.Id.ToString(), (L.PlotColor, L.PlotWeight))
        L.PlotColor = G; L.PlotWeight = STYLE['beyond_w']; d.Layers.Modify(L, i, True)
    es = Rhino.DocObjects.ObjectEnumeratorSettings(); es.HiddenObjects = True; es.LockedObjects = True
    for ob in d.Objects.GetObjectList(es):
        x = ob.Attributes
        if x.Space != Rhino.DocObjects.ActiveSpace.ModelSpace or d.Layers[x.LayerIndex].FullPath.startswith(TAG): continue
        if x.PlotColorSource != Rhino.DocObjects.ObjectPlotColorSource.PlotColorFromLayer or x.PlotWeightSource != Rhino.DocObjects.ObjectPlotWeightSource.PlotWeightFromLayer:
            st['objs'].setdefault(ob.Id.ToString(), (x.PlotColorSource, x.PlotColor, x.PlotWeightSource, x.PlotWeight))
            y = x.Duplicate(); y.PlotColorSource = Rhino.DocObjects.ObjectPlotColorSource.PlotColorFromLayer
            y.PlotWeightSource = Rhino.DocObjects.ObjectPlotWeightSource.PlotWeightFromLayer
            d.Objects.ModifyAttributes(ob, y, True)

def restore_plot():
    """plot_style() 되돌림 → 문서를 그대로 저장해도 됨"""
    st = sc.sticky.get('secl_state')
    if not st: return
    for i in range(d.Layers.Count):
        L = d.Layers[i]
        v = st['layers'].get(L.Id.ToString())
        if v: L.PlotColor, L.PlotWeight = v; d.Layers.Modify(L, i, True)
    for gid, (pcs, pc, pws, pw) in st['objs'].items():
        ob = d.Objects.FindId(System.Guid(gid))
        if ob:
            y = ob.Attributes.Duplicate(); y.PlotColorSource, y.PlotColor, y.PlotWeightSource, y.PlotWeight = pcs, pc, pws, pw
            d.Objects.ModifyAttributes(ob, y, True)
    st['layers'] = {}; st['objs'] = {}

def export_pdf(cfg, dpi=300):
    pdf_path = cfg['pdf']; log = os.path.join(os.path.dirname(pdf_path), '_export_log.txt')
    if os.path.exists(log): os.remove(log)
    def job(sender, e):
        Rhino.RhinoApp.Idle -= sc.sticky['secl_idle']        # MCP 300초 제한을 피하려고 Idle 에서 출력
        t = time.time()
        try:
            plot_style()                                          # 출력색은 쓰는 동안만 → 문서는 늘 저장 가능 상태
            pg = [v for v in d.Views.GetPageViews() if v.PageName == cfg['page']][0]
            f = Rhino.FileIO.FilePdf.Create()
            raster = cfg.get('raster', bool(cfg.get('elev')))     # 입면은 래스터: 벡터 PDF 는 Technical 숨은선을 안 가림(겪음). 화면 표시 그대로
            s = Rhino.Display.ViewCaptureSettings(pg, cfg.get('dpi', 400 if raster else dpi))
            s.RasterMode = raster                                 # 단면·평면 = 벡터 (흰 가림 해치가 Technical 선을 가려 줌)
            s.OutputColor = Rhino.Display.ViewCaptureSettings.ColorMode.PrintColor   # BlackAndWhite 는 흰 가림을 검게 만듦
            s.UsePrintWidths = True; s.DefaultPrintWidthMillimeters = STYLE['beyond_w']
            f.AddPage(s); f.Write(pdf_path)
            open(log, 'w').write('ok %.1f s\n' % (time.time() - t))
        except Exception as ex:
            open(log, 'w').write('ERR %s\n' % ex)
        finally:
            restore_plot()
    sc.sticky['secl_idle'] = job; Rhino.RhinoApp.Idle += job
    print('export scheduled ->', pdf_path)

def restore(delete_pages=True):
    st = sc.sticky.get('secl_state')
    if not st: print('nothing'); return
    restore_plot()
    for i in range(d.Layers.Count):                          # 단면판·단면선 레이어와 페이지별 하위 레이어
        if d.Layers[i].FullPath.startswith(TAG) and not d.Layers[i].IsDeleted:
            for ob in list(d.Objects.FindByLayer(d.Layers[i]) or []): d.Objects.Delete(ob, True)
    if delete_pages:
        for v in list(d.Views.GetPageViews()):
            if v.PageName in st['pages']: v.Close()
    sc.sticky['secl_state'] = None; d.Views.Redraw(); print('restored')
