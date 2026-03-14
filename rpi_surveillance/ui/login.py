"""Login and authentication module for rpi_surveillance."""

from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from nicegui import app, ui


# Dummy credentials – replace with proper hashing in production
PASSWORDS = {'user1': 'pass1', 'user2': 'pass2', 'admin': 'admin'}

UNRESTRICTED_PAGE_ROUTES = {'/login'}

LOGIN_CSS = """
html, body {
    background: radial-gradient(ellipse at 50% 0%, #1a2a50 0%, #090c18 65%) fixed !important;
    min-height: 100vh;
}
.q-page { background: transparent !important; }

.login-card {
    background    : rgba(13, 18, 30, 0.96) !important;
    border        : 1px solid rgba(30, 45, 64, 0.9) !important;
    border-radius : 20px !important;
    box-shadow    : 0 32px 64px rgba(0,0,0,.65),
                    0 0 0 1px rgba(20,184,166,.08) !important;
    width         : min(400px, calc(100vw - 32px));
}

.login-logo-wrap {
    background   : linear-gradient(135deg, #0f1f3d 0%, #0d2137 100%);
    border-radius: 18px;
    padding      : 10px;
    border       : 1px solid rgba(20,184,166,.18);
    display      : inline-flex;
}

.login-divider { background: rgba(30,45,64,.9) !important; }

.login-footer {
    color      : #374151;
    font-size  : .72rem;
    text-align : center;
    letter-spacing: .2px;
}
"""


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to /login."""

    async def dispatch(self, request: Request, call_next):
        if not app.storage.user.get('authenticated', False):
            if (not request.url.path.startswith('/_nicegui')
                    and request.url.path not in UNRESTRICTED_PAGE_ROUTES):
                app.storage.user['referrer_path'] = request.url.path
                return RedirectResponse('/login')
        return await call_next(request)


def setup_auth_middleware() -> None:
    app.add_middleware(AuthMiddleware)


def logout() -> None:
    app.storage.user.clear()
    ui.navigate.to('/login')


@ui.page('/login')
def login_page() -> Optional[RedirectResponse]:
    """Login page."""
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">')
    ui.add_head_html('<meta name="theme-color" content="#090c18">')
    ui.add_head_html(f'<style>{LOGIN_CSS}</style>')
    ui.dark_mode().enable()

    if app.storage.user.get('authenticated', False):
        return RedirectResponse('/')

    def try_login() -> None:
        if PASSWORDS.get(username.value) == password.value:
            app.storage.user.update({'username': username.value, 'authenticated': True})
            ui.navigate.to(app.storage.user.get('referrer_path', '/'))
        else:
            ui.notify('Invalid username or password', color='negative',
                      icon='error', position='top')

    with ui.card().classes('login-card q-pa-xl absolute-center'):
        with ui.column().classes('items-center w-full').style('gap:20px'):

            # ── Logo + title ────────────────────────────────────────────────
            with ui.column().classes('items-center').style('gap:10px'):
                with ui.element('div').classes('login-logo-wrap'):
                    ui.image('rpi_surveillance/assets/logo.png').style('width:56px; height:56px')
                with ui.column().classes('items-center').style('gap:2px'):
                    ui.label('RPI Surveillance').classes('text-h5 text-weight-bold').style(
                        'color:#f1f5f9; letter-spacing:-.5px')
                    ui.label('Secure access portal').classes('text-caption').style('color:#64748b')

            ui.separator().classes('login-divider w-full')

            # ── Form ────────────────────────────────────────────────────────
            with ui.column().classes('w-full').style('gap:10px'):
                username = (
                    ui.input(label='Username', placeholder='Enter username')
                    .classes('w-full')
                    .props('outlined dark color=teal')
                )
                username.on('keydown.enter', try_login)

                password = (
                    ui.input(label='Password', password=True,
                             password_toggle_button=True, placeholder='Enter password')
                    .classes('w-full')
                    .props('outlined dark color=teal')
                )
                password.on('keydown.enter', try_login)

                ui.button('Sign In', icon='lock_open', on_click=try_login).classes('w-full').props(
                    'unelevated no-caps size=lg color=teal')

            # ── Footer ──────────────────────────────────────────────────────
            ui.label('RPI Surveillance System  ·  v1.0').classes('login-footer')

    return None
