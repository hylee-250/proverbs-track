import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session, init_db
from .models import Activity, ChapterNote, ChapterProgress
from .proverbs import CHAPTER_THEMES, TOTAL_CHAPTERS, TOTAL_VERSES, VERSE_COUNTS
from .services import (
    calendar_months,
    current_period,
    load_all_stats,
    load_member_stats,
    now_kst,
    team_summary,
    to_kst,
)

BASE_DIR = Path(__file__).parent
COOKIE = "member"
NOTE_MAX = 500


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_title, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

WEEKDAYS = "월화수목금토일"


def fmt_dt(dt, style: str = "full") -> str:
    if dt is None:
        return ""
    dt = to_kst(dt)
    if style == "date":
        return f"{dt.month}/{dt.day}"
    if style == "relative":
        delta = now_kst() - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "방금 전"
        if secs < 3600:
            return f"{secs // 60}분 전"
        if secs < 86400:
            return f"{secs // 3600}시간 전"
        if delta.days < 7:
            return f"{delta.days}일 전"
        return f"{dt.month}/{dt.day}"
    return f"{dt.month}월 {dt.day}일({WEEKDAYS[dt.weekday()]}) {dt:%H:%M}"


templates.env.filters["kst"] = fmt_dt
templates.env.globals.update(
    app_title=settings.app_title,
    TOTAL_CHAPTERS=TOTAL_CHAPTERS,
    TOTAL_VERSES=TOTAL_VERSES,
    VERSE_COUNTS=VERSE_COUNTS,
    THEMES=CHAPTER_THEMES,
)


def current_member(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    name = unquote(raw)
    return name if name in settings.members else None


def require_member(request: Request) -> str:
    member = current_member(request)
    if member is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return member


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("me", current_member(request))
    ctx.setdefault("period", current_period())
    return templates.TemplateResponse(request, name, ctx)


def log(session: Session, member: str, chapter: int, action: str) -> None:
    session.add(Activity(member=member, chapter=chapter, action=action))


def valid_chapter(chapter: int) -> int:
    if not 1 <= chapter <= TOTAL_CHAPTERS:
        raise HTTPException(status_code=404, detail="잠언은 1장부터 31장까지 있어요.")
    return chapter


def toggle_chapter(session: Session, member: str, chapter: int) -> bool:
    row = session.scalar(
        select(ChapterProgress).where(
            ChapterProgress.member == member, ChapterProgress.chapter == chapter
        )
    )
    if row:
        session.delete(row)
        last_complete = session.scalar(
            select(Activity)
            .where(Activity.member == member, Activity.chapter == chapter, Activity.action == "complete")
            .order_by(Activity.created_at.desc())
            .limit(1)
        )
        if last_complete:
            session.delete(last_complete)
        done = False
    else:
        session.add(ChapterProgress(member=member, chapter=chapter))
        log(session, member, chapter, "complete")
        done = True
    try:
        session.commit()
    except IntegrityError:
        # A concurrent double tap already inserted this chapter.
        session.rollback()
        done = True
    return done


def dashboard_context(session: Session, member: str) -> dict:
    period = current_period()
    stats = load_member_stats(session, member)
    current_streak, best_streak = stats.streaks(period.today)
    return {
        "stats": stats,
        "period": period,
        "pace": stats.pace(period),
        "current_streak": current_streak,
        "best_streak": best_streak,
        "badges": stats.badges(period.today),
        "months": calendar_months(period, stats.daily_counts()),
    }


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", members=settings.members)


@app.post("/login")
def login(name: str = Form(...)):
    if name not in settings.members:
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, quote(name), max_age=60 * 60 * 24 * 120, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def home(request: Request, member: str = Depends(require_member), session: Session = Depends(get_session)):
    return render(request, "home.html", nav="home", **dashboard_context(session, member))


@app.post("/chapters/{chapter}/toggle", response_class=HTMLResponse)
def toggle(
    request: Request,
    chapter: int,
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    valid_chapter(chapter)
    done = toggle_chapter(session, member, chapter)
    ctx = dashboard_context(session, member)
    resp = render(request, "partials/dashboard.html", **ctx)
    stats = ctx["stats"]
    if done:
        msg = "잠언 31장 완주를 축하해요!" if stats.is_finished else f"{chapter}장 완료! ({stats.count}/{TOTAL_CHAPTERS})"
    else:
        msg = f"{chapter}장 체크를 취소했어요"
    # ensure_ascii keeps the header latin-1 safe; htmx parses the \u escapes back to Korean.
    resp.headers["HX-Trigger"] = json.dumps(
        {"toast": {"message": msg, "celebrate": done and stats.is_finished}}
    )
    return resp


@app.get("/team", response_class=HTMLResponse)
def team(
    request: Request,
    sort: str = "progress",
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    period = current_period()
    stats = load_all_stats(session, settings.members)
    rows = list(stats.values())
    if sort == "name":
        rows.sort(key=lambda s: s.member)
    elif sort == "recent":
        rows.sort(key=lambda s: (s.last_completed_at is None, -(s.last_completed_at.timestamp() if s.last_completed_at else 0)))
    else:
        sort = "progress"
        rows.sort(key=lambda s: (-s.verses_done, s.last_completed_at or now_kst()))
    activities = session.scalars(
        select(Activity)
        .where(Activity.action.in_(("complete", "note")), Activity.member.in_(settings.members))
        .order_by(Activity.created_at.desc())
        .limit(30)
    ).all()
    return render(
        request,
        "team.html",
        nav="team",
        rows=rows,
        sort=sort,
        summary=team_summary(stats, period),
        activities=activities,
    )


@app.get("/members/{name}", response_class=HTMLResponse)
def member_detail(
    request: Request,
    name: str,
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    if name not in settings.members:
        raise HTTPException(status_code=404, detail="등록되지 않은 멤버예요.")
    if name == member:
        return RedirectResponse("/", status_code=303)
    return render(request, "member.html", nav="team", **dashboard_context(session, name))


@app.get("/notes", response_class=HTMLResponse)
def notes(
    request: Request,
    chapter: int | None = None,
    mine: bool = False,
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    q = select(ChapterNote).where(ChapterNote.member.in_(settings.members))
    if chapter:
        valid_chapter(chapter)
        q = q.where(ChapterNote.chapter == chapter)
    if mine:
        q = q.where(ChapterNote.member == member)
    items = session.scalars(q.order_by(ChapterNote.created_at.desc()).limit(200)).all()
    stats = load_member_stats(session, member)
    return render(
        request,
        "notes.html",
        nav="notes",
        items=items,
        chapter=chapter,
        mine=mine,
        default_chapter=chapter or stats.next_chapter or TOTAL_CHAPTERS,
        note_max=NOTE_MAX,
    )


@app.post("/notes")
def create_note(
    chapter: int = Form(...),
    content: str = Form(...),
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    valid_chapter(chapter)
    content = content.strip()[:NOTE_MAX]
    if content:
        session.add(ChapterNote(member=member, chapter=chapter, content=content))
        log(session, member, chapter, "note")
        session.commit()
    return RedirectResponse(f"/notes?chapter={chapter}", status_code=303)


@app.post("/notes/{note_id}/delete")
def delete_note(
    note_id: int,
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    note = session.get(ChapterNote, note_id)
    if note and note.member == member:
        session.delete(note)
        feed_item = session.scalar(
            select(Activity)
            .where(Activity.member == member, Activity.chapter == note.chapter, Activity.action == "note")
            .order_by(Activity.created_at.desc())
            .limit(1)
        )
        if feed_item:
            session.delete(feed_item)
        session.commit()
    return RedirectResponse("/notes", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, member: str = Depends(require_member), session: Session = Depends(get_session)):
    stats = load_all_stats(session, settings.members)
    period = current_period()
    db_members = set(session.scalars(select(ChapterProgress.member).distinct()))
    orphaned = sorted(db_members - set(settings.members))
    return render(
        request,
        "admin.html",
        nav="admin",
        rows=list(stats.values()),
        summary=team_summary(stats, period),
        orphaned=orphaned,
    )


@app.post("/admin/toggle", response_class=HTMLResponse)
def admin_toggle(
    request: Request,
    name: str = Form(...),
    chapter: int = Form(...),
    member: str = Depends(require_member),
    session: Session = Depends(get_session),
):
    if name not in settings.members:
        raise HTTPException(status_code=404)
    valid_chapter(chapter)
    toggle_chapter(session, name, chapter)
    stats = load_member_stats(session, name)
    return render(request, "partials/admin_row.html", row=stats)


@app.post("/admin/orphans/delete")
def delete_orphans(member: str = Depends(require_member), session: Session = Depends(get_session)):
    for model in (ChapterProgress, ChapterNote, Activity):
        session.execute(delete(model).where(model.member.not_in(settings.members)))
    session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/export.csv")
def export_csv(member: str = Depends(require_member), session: Session = Depends(get_session)):
    stats = load_all_stats(session, settings.members)
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf)
    w.writerow(["이름", "완료 장수", "진도율(%)", "마지막 필사"] + [f"{c}장" for c in range(1, TOTAL_CHAPTERS + 1)])
    for s in stats.values():
        w.writerow(
            [s.member, s.count, s.percent, fmt_dt(s.last_completed_at)]
            + [fmt_dt(s.completed[c], "date") if c in s.completed else "" for c in range(1, TOTAL_CHAPTERS + 1)]
        )
    filename = quote(f"잠언필사_진도_{now_kst():%Y%m%d}.csv")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/sw.js")
def service_worker():
    return Response((BASE_DIR / "static" / "sw.js").read_text(), media_type="application/javascript")
