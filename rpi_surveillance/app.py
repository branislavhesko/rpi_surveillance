#!/usr/bin/env python3
"""Unified entry point for rpi_surveillance.

NiceGUI's ``app`` object is a subclass of ``fastapi.FastAPI``, so the camera
REST endpoints (defined in ``rpi_surveillance.backend.server``) are mounted
directly onto it under the ``/api`` prefix. The UI and the camera API therefore
run inside a single ASGI application on a single port (9000).

Run with::

    python -m rpi_surveillance.app
"""

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

from nicegui import app, ui

from rpi_surveillance.backend.server import API_PREFIX, RECORDINGS_DIR, camera_api
from rpi_surveillance.ui.live_view import create_live_view_page
from rpi_surveillance.ui.login import logout, setup_auth_middleware
from rpi_surveillance.ui.record_viewer import create_record_viewer_page

HOST = "0.0.0.0"
PORT = 9000

# Mount the camera REST API onto NiceGUI's FastAPI application.
app.include_router(camera_api)

# Serve recordings directory so browser can access videos and images
app.add_media_files('/media', str(RECORDINGS_DIR))


# ===========================================================================
# Global design-system CSS (injected once per main page load)
# ===========================================================================
APP_CSS = """
/* ── Design tokens ─────────────────────────────────────────────────────── */
:root {
    --bg-page    : #0a0e1a;
    --bg-card    : #111827;
    --bg-raised  : #1f2937;
    --accent     : #14b8a6;
    --accent-dim : #0d9488;
    --text-1     : #f1f5f9;
    --text-2     : #94a3b8;
    --text-3     : #64748b;
    --border     : #1e2d40;
    --success    : #22c55e;
    --danger     : #ef4444;
    --warning    : #f59e0b;
}

/* ── Base ───────────────────────────────────────────────────────────────── */
html, body { background: var(--bg-page) !important; }
.q-page, .nicegui-content { background: var(--bg-page) !important; }
* { box-sizing: border-box; }

/* ── Header ─────────────────────────────────────────────────────────────── */
.app-header {
    background: linear-gradient(90deg, #0d1526 0%, #111827 100%) !important;
    border-bottom: 1px solid var(--border) !important;
    min-height: 52px !important;
    padding: 0 16px !important;
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.q-tabs { background: #0d1526 !important; border-bottom: 1px solid var(--border) !important; }
.q-tab  { min-height: 48px !important; text-transform: none !important; font-size: 0.82rem !important; font-weight: 500 !important; }
.q-tab--active { color: var(--accent) !important; }
.q-tabs__slider { background: var(--accent) !important; height: 2px !important; }
.q-tab-panels   { background: var(--bg-page) !important; }
.q-tab-panel    { padding: 0 !important; }

/* ── Cards ──────────────────────────────────────────────────────────────── */
.sv-card {
    background    : var(--bg-card) !important;
    border        : 1px solid var(--border) !important;
    border-radius : 12px !important;
}
.sv-card-raised {
    background    : var(--bg-raised) !important;
    border        : 1px solid var(--border) !important;
    border-radius : 10px !important;
    transition    : border-color .15s;
}
.sv-card-raised:hover { border-color: var(--accent) !important; }

/* ── Status dots ────────────────────────────────────────────────────────── */
@keyframes pulse-green {
    0%   { box-shadow: 0 0 0 0   rgba(34,197,94,.7); }
    70%  { box-shadow: 0 0 0 8px rgba(34,197,94,0);  }
    100% { box-shadow: 0 0 0 0   rgba(34,197,94,0);  }
}
@keyframes pulse-red {
    0%   { box-shadow: 0 0 0 0    rgba(239,68,68,.7); }
    70%  { box-shadow: 0 0 0 10px rgba(239,68,68,0);  }
    100% { box-shadow: 0 0 0 0    rgba(239,68,68,0);  }
}
.sv-dot {
    width: 9px; height: 9px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}
.sv-dot-online  { background: var(--success); animation: pulse-green 2s infinite; }
.sv-dot-offline { background: var(--text-3);  }
.sv-dot-warn    { background: var(--warning); animation: pulse-green 2s infinite; }
.sv-dot-rec     { background: var(--danger);  animation: pulse-red   1.2s infinite; }

/* ── Control button row ─────────────────────────────────────────────────── */
.ctrl-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
}
.ctrl-row .q-btn { min-height: 40px; border-radius: 8px !important; }

/* ── Camera frame ───────────────────────────────────────────────────────── */
.cam-frame {
    position: relative;
    width: 100%;
    background: #000;
    border-radius: 10px;
    overflow: hidden;
    aspect-ratio: 4/3;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
}
.cam-frame img { width: 100% !important; height: 100% !important; object-fit: contain; }
.rec-badge {
    position  : absolute;
    top       : 10px;
    left      : 10px;
    z-index   : 10;
    background: rgba(0,0,0,.72);
    color     : var(--danger);
    font-size : .7rem;
    font-weight: 700;
    padding   : 2px 10px;
    border-radius: 4px;
    letter-spacing: .5px;
    border: 1px solid rgba(239,68,68,.4);
}

/* ── Recording list ─────────────────────────────────────────────────────── */
.rec-item {
    background    : var(--bg-card) !important;
    border        : 1px solid var(--border) !important;
    border-radius : 10px !important;
    transition    : border-color .15s;
}
.rec-item:hover { border-color: var(--accent) !important; }

/* ── Inputs (dark) ──────────────────────────────────────────────────────── */
.q-field--outlined .q-field__control { border-radius: 8px !important; }

/* ── Buttons global ─────────────────────────────────────────────────────── */
.q-btn { border-radius: 8px !important; }

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar            { width: 5px; height: 5px; }
::-webkit-scrollbar-track      { background: var(--bg-page); }
::-webkit-scrollbar-thumb      { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover{ background: #374151; }
"""


setup_auth_middleware()


def _status_tile(label: str, icon: str, status: str, dot_cls: str) -> None:
    with ui.card().classes('sv-card-raised').style('padding: 14px 16px; min-width: 130px; flex: 1'):
        with ui.row().classes('items-center justify-between q-mb-xs'):
            ui.icon(icon).style('color: var(--accent); font-size: 1.4rem')
            ui.element('span').classes(f'sv-dot {dot_cls}')
        ui.label(label).classes('text-caption').style('color: var(--text-3); font-weight:500')
        ui.label(status).classes('text-body2 text-weight-bold').style('color: var(--text-1)')


def _create_home_panel(username: str) -> None:
    with ui.column().classes('w-full q-pa-md').style('gap:20px; max-width:960px; margin:0 auto'):

        # Welcome banner
        with ui.card().classes('sv-card w-full').style('padding:0; overflow:hidden'):
            with ui.row().classes('items-center').style('padding: 20px 24px; gap:16px'):
                ui.image('rpi_surveillance/assets/logo.png').style(
                    'width:64px; height:64px; border-radius:12px; flex-shrink:0')
                with ui.column().style('gap:2px'):
                    ui.label(f'Welcome back, {username}').classes('text-h5 text-weight-bold').style(
                        'color:var(--text-1); letter-spacing:-.4px')
                    ui.label('Your surveillance system is operational').classes('text-body2').style(
                        'color:var(--text-2)')

        # Status grid
        ui.label('System Status').classes('text-overline').style('color:var(--text-3); letter-spacing:1.5px')
        with ui.row().classes('w-full row wrap').style('gap:10px'):
            _status_tile('Camera',       'videocam',   'Ready',   'sv-dot-online')
            _status_tile('Storage',      'storage',    'OK',      'sv-dot-online')
            _status_tile('AI Detection', 'psychology', 'Standby', 'sv-dot-warn')
            _status_tile('Network',      'wifi',       'Online',  'sv-dot-online')


def _create_settings_panel(username: str) -> None:
    with ui.column().classes('w-full q-pa-md').style('gap:16px; max-width:700px; margin:0 auto'):
        ui.label('Settings').classes('text-h5 text-weight-bold').style('color:var(--text-1)')

        # System info
        with ui.card().classes('sv-card w-full q-pa-md'):
            with ui.row().classes('items-center q-mb-md').style('gap:8px'):
                ui.icon('developer_board').style('color:var(--accent)')
                ui.label('System Information').classes('text-subtitle1 text-weight-medium').style('color:var(--text-1)')
            rows = [
                ('Platform',     'Raspberry Pi'),
                ('AI Kit',       'Hailo AI Accelerator'),
                ('Camera',       'PiCamera2'),
                ('Server',       f'NiceGUI + FastAPI :{PORT}'),
                ('Camera API',   f'{API_PREFIX}'),
            ]
            with ui.column().style('gap:6px'):
                for key, val in rows:
                    with ui.row().classes('items-center').style('gap:12px'):
                        ui.label(key).classes('text-caption').style(
                            'color:var(--text-3); min-width:100px; font-weight:500')
                        ui.label(val).classes('text-body2').style('color:var(--text-2)')

        # Account
        with ui.card().classes('sv-card w-full q-pa-md'):
            with ui.row().classes('items-center q-mb-md').style('gap:8px'):
                ui.icon('manage_accounts').style('color:var(--accent)')
                ui.label('Account').classes('text-subtitle1 text-weight-medium').style('color:var(--text-1)')
            with ui.row().classes('items-center').style('gap:10px'):
                ui.icon('person_outline').style('color:var(--text-3)')
                ui.label(f'Signed in as  {username}').classes('text-body2').style('color:var(--text-2)')
            ui.button(
                'Change Password', icon='lock_reset',
                on_click=lambda: ui.notify('Not yet implemented', color='info', icon='info')
            ).props('outlined no-caps color=teal').classes('q-mt-sm')

        # About
        with ui.card().classes('sv-card w-full q-pa-md'):
            with ui.row().classes('items-center q-mb-sm').style('gap:8px'):
                ui.icon('info_outline').style('color:var(--accent)')
                ui.label('About').classes('text-subtitle1 text-weight-medium').style('color:var(--text-1)')
            ui.label('RPI Surveillance System v1.0').classes('text-body2').style('color:var(--text-2)')
            ui.label('AI-powered surveillance for Raspberry Pi with Hailo integration.').classes(
                'text-caption').style('color:var(--text-3)')


@ui.page('/')
def main_menu() -> None:
    """Main application page with tabbed navigation."""
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">')
    ui.add_head_html('<meta name="theme-color" content="#0a0e1a">')
    ui.add_head_html(f'<style>{APP_CSS}</style>')
    ui.dark_mode().enable()

    username = app.storage.user.get('username', 'guest')

    # ── Header ──────────────────────────────────────────────────────────────
    with ui.header().classes('app-header row items-center'):
        ui.icon('videocam').style('color:var(--accent); font-size:1.35rem')
        ui.label('RPI Surveillance').classes('text-weight-bold q-ml-xs').style(
            'color:var(--text-1); font-size:.98rem; letter-spacing:-.2px')
        ui.space()
        with ui.row().classes('items-center gt-xs').style('gap:4px; margin-right:4px'):
            ui.icon('person_outline').style('color:var(--text-3); font-size:1rem')
            ui.label(username).classes('text-caption').style('color:var(--text-2)')
        ui.button(icon='logout', on_click=logout).props('flat round dense color=grey-5').tooltip('Sign out')

    # ── Tab bar ──────────────────────────────────────────────────────────────
    with ui.tabs().classes('w-full') as tabs:
        home_tab       = ui.tab('Home',       icon='home')
        live_tab       = ui.tab('Live',       icon='videocam')
        recordings_tab = ui.tab('Recordings', icon='video_library')
        settings_tab   = ui.tab('Settings',   icon='settings')

    # ── Tab panels ───────────────────────────────────────────────────────────
    with ui.tab_panels(tabs, value=home_tab).classes('w-full').style('flex:1; overflow-y:auto'):
        with ui.tab_panel(home_tab):
            _create_home_panel(username)
        with ui.tab_panel(live_tab):
            create_live_view_page()
        with ui.tab_panel(recordings_tab):
            create_record_viewer_page()
        with ui.tab_panel(settings_tab):
            _create_settings_panel(username)


# ===========================================================================
# Entry point
# ===========================================================================
def run_app() -> None:
    """Run the combined NiceGUI + FastAPI application on a single port."""
    ui.run(
        storage_secret='FAIRYTALE',  # TODO: change in production
        port=PORT,
        host=HOST,
        title='RPI Surveillance',
        favicon='🎥',
        show=False,
        reload=False,
    )


if __name__ in {'__main__', '__mp_main__'}:
    run_app()
