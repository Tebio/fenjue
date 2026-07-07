"""Auth route — login form + cookie-based token + middleware."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

# Hardcoded credentials
_VALID_USER = "admin"
_VALID_PASS = "fenjue2026"
_TOKEN = "demo-token-2026"
_COOKIE_NAME = "fenjue_token"


# --- Middleware helper ---
async def check_auth(request: Request) -> RedirectResponse | None:
    """Redirect to login if cookie missing or invalid."""
    token = request.cookies.get(_COOKIE_NAME)
    if token != _TOKEN:
        return RedirectResponse(url="/console/login", status_code=303)
    return None


# --- Login page (HTML fragment) ---
@router.get("/console/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Return centered login card."""
    return HTMLResponse("""\
<div style="display:flex;align-items:center;justify-content:center;min-height:60vh">
  <div class="card" style="max-width:360px;width:100%;text-align:center">
    <h2 style="color:var(--accent);margin:0 0 20px">🔐 FenJue Console</h2>
    <form hx-post="/console/api/login" hx-target="#login-error" hx-swap="innerHTML">
      <input name="username" placeholder="用户名" required
        style="width:100%;margin-bottom:12px;padding:10px;border:1px solid var(--border);
        border-radius:6px;background:var(--bg);color:var(--text)">
      <input name="password" type="password" placeholder="密码" required
        style="width:100%;margin-bottom:16px;padding:10px;border:1px solid var(--border);
        border-radius:6px;background:var(--bg);color:var(--text)">
      <button type="submit"
        style="width:100%;padding:10px;background:var(--accent);color:#000;
        border:none;border-radius:6px;font-weight:600;cursor:pointer">
        登录
      </button>
    </form>
    <div id="login-error" style="margin-top:12px;color:#e74c3c;font-size:13px"></div>
  </div>
</div>""")


# --- Login API ---
@router.post("/console/api/login")
async def login_api(request: Request):
    """Validate credentials, set cookie, redirect on success."""
    form = await request.form()
    if form.get("username") == _VALID_USER and form.get("password") == _VALID_PASS:
        response = HTMLResponse("")
        response.headers["HX-Redirect"] = "/console"
        response.set_cookie(_COOKIE_NAME, _TOKEN, httponly=True, path="/")
        return response
    return HTMLResponse('<div>❌ 密码错误</div>', status_code=401)
