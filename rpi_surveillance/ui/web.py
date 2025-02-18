#!/usr/bin/env python3
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from nicegui import app, ui

from rpi_surveillance.ui.record import drawer, main_page, Record

# Dummy passwords – in a real app, use proper hashing
passwords = {'user1': 'pass1', 'user2': 'pass2'}

# Define routes that do not require authentication
unrestricted_page_routes = {'/login'}

# --- Authentication Middleware ---
class AuthMiddleware(BaseHTTPMiddleware):
    """
    This middleware restricts access to all NiceGUI pages.
    If the user is not authenticated, they are redirected to the login page.
    """
    async def dispatch(self, request: Request, call_next):
        if not app.storage.user.get('authenticated', False):
            if not request.url.path.startswith('/_nicegui') and request.url.path not in unrestricted_page_routes:
                # remember the requested path to return after login
                app.storage.user['referrer_path'] = request.url.path  
                return RedirectResponse('/login')
        return await call_next(request)

app.add_middleware(AuthMiddleware)

# --- Main Menu Page ---
@ui.page('/')
def main_menu():
    def logout() -> None:
        app.storage.user.clear()
        ui.navigate.to('/login')  # Redirect to the login page
        
    record = Record()
    d = drawer(record)
    with ui.header().classes(replace='row items-center') as header:
        ui.button(on_click=lambda: d.toggle(), icon='menu').props('flat color=white')
        with ui.tabs() as tabs:
            ui.tab('Home')
            ui.tab('Record')
            ui.tab('Analyze')
            ui.tab('Storage')

    with ui.tab_panels(tabs, value='Home').classes('w-full'):
        with ui.tab_panel('Home'):
            with ui.column().classes('w-full items-center'):
                ui.label(f'Hello {app.storage.user.get("username", "user")}!').classes('text-2xl')
                ui.image('rpi_surveillance/assets/logo.png').style('width: 640px; height: 640px')
        with ui.tab_panel('Record'):
            with ui.column().classes('w-full items-center'):
                main_page(record)
        with ui.tab_panel('Analyze'):
            with ui.column().classes('w-full items-center'):
                analyze_page()
        with ui.tab_panel('Storage'):
            with ui.column().classes('w-full items-center'):
                storage_page()

        with ui.row().classes('w-full justify-center'):
            ui.button('Logout', on_click=logout, icon='logout').props('outline round')

# --- Analyze Page ---
@ui.page('/analyze')
def analyze_page():
    ui.label('Analyze Page')
    ui.button('Back to Menu', on_click=lambda: ui.navigate.to('/'))

# --- Storage Page ---
@ui.page('/storage')
def storage_page():
    ui.label('Storage Page')
    ui.button('Back to Menu', on_click=lambda: ui.navigate.to('/'))

# --- Login Page ---
@ui.page('/login')
def login_page() -> Optional[RedirectResponse]:
    def try_login() -> None:
        if passwords.get(username.value) == password.value:
            app.storage.user.update({
                'username': username.value,
                'authenticated': True,
            })
            # Redirect to the originally requested page or default to '/'
            ui.navigate.to(app.storage.user.get('referrer_path', '/'))
        else:
            ui.notify('Wrong username or password', color='negative')

    # If already authenticated, immediately redirect to main menu.
    if app.storage.user.get('authenticated', False):
        return RedirectResponse('/')
    
    with ui.card().classes('absolute-center'):
        username = ui.input('Username').on('keydown.enter', try_login)
        password = ui.input('Password', password=True, password_toggle_button=True).on('keydown.enter', try_login)
        ui.button('Log in', on_click=try_login)
    return None


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(storage_secret='FAIRYTALE', port=9000, host='0.0.0.0')
