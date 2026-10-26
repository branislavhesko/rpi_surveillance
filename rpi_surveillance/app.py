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

from rpi_surveillance.config import get_storage_secret
from rpi_surveillance.backend.camera import RECORDINGS_DIR
from rpi_surveillance.backend.server import (
    API_PREFIX,
    camera_api,
    camera_injector,
    gatekeeper_injector,
)
from rpi_surveillance.backend.system_stats import SystemStats, get_system_stats
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
.sv-clickable { cursor: pointer; user-select: none; }
.sv-clickable:active { transform: scale(.98); }

/* ── Header system metrics ─────────────────────────────────────────────── */
.hdr-stat {
    display: flex; align-items: center; gap: 3px;
    padding: 2px 8px; border-radius: 6px;
    color: var(--text-2); font-size: .75rem; font-variant-numeric: tabular-nums;
}
.hdr-stat:hover { background: var(--bg-raised); }
.hdr-stat .q-icon { font-size: 1rem; color: var(--text-3); }
.hdr-stat.warn, .hdr-stat.warn .q-icon { color: var(--warning); }
.hdr-stat.crit, .hdr-stat.crit .q-icon { color: var(--danger); }

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
    aspect-ratio: 16/9;
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


STATS_REFRESH_SECONDS = 2.0

# (warn, critical) thresholds; the Pi starts throttling at 80 °C.
TEMP_LIMITS = (70.0, 80.0)
CPU_LIMITS = (85.0, 95.0)
RAM_LIMITS = (85.0, 95.0)
DISK_LIMITS = (90.0, 97.0)


def _level(value: float | None, limits: tuple[float, float]) -> str:
    if value is None:
        return 'unknown'
    if value >= limits[1]:
        return 'crit'
    if value >= limits[0]:
        return 'warn'
    return 'ok'


_DOT_FOR_LEVEL = {
    'ok': 'sv-dot-online',
    'warn': 'sv-dot-warn',
    'crit': 'sv-dot-rec',
    'unknown': 'sv-dot-offline',
}


def _fmt(value: float | None, fmt: str) -> str:
    return 'n/a' if value is None else fmt.format(value)


class _LiveStats:
    """Polls system metrics once per tick and fans them out to UI updaters."""

    def __init__(self) -> None:
        self._updaters = []

    def add(self, updater) -> None:
        self._updaters.append(updater)

    def refresh(self) -> None:
        stats = get_system_stats(RECORDINGS_DIR)
        for updater in self._updaters:
            updater(stats)

    def start(self) -> None:
        self.refresh()
        ui.timer(STATS_REFRESH_SECONDS, self.refresh)


class _StatusTile:
    def __init__(self, label: str, icon: str, on_click=None) -> None:
        card = ui.card().classes('sv-card-raised').style(
            'padding: 14px 16px; min-width: 130px; flex: 1')
        if on_click is not None:
            card.classes('sv-clickable').on('click', on_click)
        with card:
            with ui.row().classes('items-center justify-between q-mb-xs w-full'):
                ui.icon(icon).style('color: var(--accent); font-size: 1.4rem')
                self._dot = ui.element('span').classes('sv-dot sv-dot-offline')
            ui.label(label).classes('text-caption').style('color: var(--text-3); font-weight:500')
            self._value = ui.label('…').classes('text-body2 text-weight-bold').style(
                'color: var(--text-1)')
            self._detail = ui.label('').classes('text-caption').style('color: var(--text-3)')

    def set(self, value: str, dot_cls: str, detail: str = '') -> None:
        self._value.set_text(value)
        self._dot.classes(replace=f'sv-dot {dot_cls}')
        self._detail.set_text(detail or '\u00a0')  # keep tile heights even


def _create_home_panel(username: str, live: _LiveStats, goto) -> None:
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
            camera = _StatusTile('Camera', 'videocam', lambda: goto('live'))
            storage = _StatusTile('Storage', 'storage', lambda: goto('recordings'))
            detection = _StatusTile('AI Detection', 'psychology', lambda: goto('live'))
            network = _StatusTile('Network', 'wifi', lambda: goto('settings'))

        ui.label('Raspberry Pi').classes('text-overline').style('color:var(--text-3); letter-spacing:1.5px')
        with ui.row().classes('w-full row wrap').style('gap:10px'):
            temperature = _StatusTile('Temperature', 'thermostat', lambda: goto('settings'))
            cpu = _StatusTile('CPU', 'memory', lambda: goto('settings'))
            ram = _StatusTile('RAM', 'developer_board', lambda: goto('settings'))

    network.set('Online', 'sv-dot-online')

    def update(stats: SystemStats) -> None:
        if camera_injector() is not None:
            camera.set('Running', 'sv-dot-online')
        else:
            camera.set('Stopped', 'sv-dot-offline')

        gk = gatekeeper_injector.status()
        if gk.get('running'):
            detection.set('Gatekeeper armed', 'sv-dot-online', f"{gk.get('events', 0)} events")
        else:
            detection.set('Standby', 'sv-dot-warn')

        storage.set(_fmt(stats.disk_free_gb, '{:.1f} GB free'),
                    _DOT_FOR_LEVEL[_level(stats.disk_percent, DISK_LIMITS)],
                    _fmt(stats.disk_percent, '{:.0f}% used'))
        temperature.set(_fmt(stats.temperature_c, '{:.1f} °C'),
                        _DOT_FOR_LEVEL[_level(stats.temperature_c, TEMP_LIMITS)])
        cpu.set(_fmt(stats.cpu_percent, '{:.0f}%'),
                _DOT_FOR_LEVEL[_level(stats.cpu_percent, CPU_LIMITS)])
        ram.set(_fmt(stats.ram_percent, '{:.0f}%'),
                _DOT_FOR_LEVEL[_level(stats.ram_percent, RAM_LIMITS)],
                '' if stats.ram_total_gb is None
                else f'{stats.ram_used_gb:.1f} / {stats.ram_total_gb:.1f} GB')

    live.add(update)


def _create_header_stats(live: _LiveStats, goto) -> None:
    """Compact temperature / CPU / RAM readout shown in the header on every tab."""
    items = {}
    with ui.row().classes('items-center no-wrap').style('gap:2px; margin-right:8px'):
        for key, icon, tip in [('temp', 'thermostat', 'SoC temperature'),
                               ('cpu', 'memory', 'CPU usage'),
                               ('ram', 'developer_board', 'RAM usage')]:
            with ui.element('div').classes('hdr-stat sv-clickable').on(
                    'click', lambda: goto('home')) as chip:
                ui.icon(icon)
                items[key] = (chip, ui.label('…'))
            chip.tooltip(tip)

    def update(stats: SystemStats) -> None:
        for key, value, fmt, limits in [
            ('temp', stats.temperature_c, '{:.0f}°C', TEMP_LIMITS),
            ('cpu', stats.cpu_percent, '{:.0f}%', CPU_LIMITS),
            ('ram', stats.ram_percent, '{:.0f}%', RAM_LIMITS),
        ]:
            chip, label = items[key]
            label.set_text(_fmt(value, fmt))
            level = _level(value, limits)
            chip.classes(replace=f"hdr-stat sv-clickable {level if level in ('warn', 'crit') else ''}")

    live.add(update)


def _create_settings_panel(username: str, live: _LiveStats) -> None:
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
                metrics = {}
                for key in ('Temperature', 'CPU', 'RAM', 'Disk'):
                    with ui.row().classes('items-center').style('gap:12px'):
                        ui.label(key).classes('text-caption').style(
                            'color:var(--text-3); min-width:100px; font-weight:500')
                        metrics[key] = ui.label('…').classes('text-body2').style('color:var(--text-2)')

            def update(stats: SystemStats) -> None:
                metrics['Temperature'].set_text(_fmt(stats.temperature_c, '{:.1f} °C'))
                metrics['CPU'].set_text(_fmt(stats.cpu_percent, '{:.0f}%'))
                metrics['RAM'].set_text(
                    'n/a' if stats.ram_total_gb is None else
                    f'{stats.ram_percent:.0f}%  ({stats.ram_used_gb:.1f} / {stats.ram_total_gb:.1f} GB)')
                metrics['Disk'].set_text(
                    'n/a' if stats.disk_free_gb is None else
                    f'{stats.disk_percent:.0f}% used  ({stats.disk_free_gb:.1f} GB free)')

            live.add(update)

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
    live = _LiveStats()
    tab_by_name = {}

    def goto(name: str) -> None:
        tabs.set_value(tab_by_name[name])

    # ── Header ──────────────────────────────────────────────────────────────
    with ui.header().classes('app-header row items-center'):
        ui.icon('videocam').style('color:var(--accent); font-size:1.35rem')
        ui.label('RPI Surveillance').classes('text-weight-bold q-ml-xs').style(
            'color:var(--text-1); font-size:.98rem; letter-spacing:-.2px')
        ui.space()
        _create_header_stats(live, goto)
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
    tab_by_name.update(home=home_tab, live=live_tab, recordings=recordings_tab,
                       settings=settings_tab)

    # ── Tab panels ───────────────────────────────────────────────────────────
    with ui.tab_panels(tabs, value=home_tab).classes('w-full').style('flex:1; overflow-y:auto'):
        with ui.tab_panel(home_tab):
            _create_home_panel(username, live, goto)
        with ui.tab_panel(live_tab):
            create_live_view_page()
        with ui.tab_panel(recordings_tab):
            create_record_viewer_page()
        with ui.tab_panel(settings_tab):
            _create_settings_panel(username, live)

    live.start()


# ===========================================================================
# Entry point
# ===========================================================================
def run_app() -> None:
    """Run the combined NiceGUI + FastAPI application on a single port."""
    ui.run(
        storage_secret=get_storage_secret(),  # loaded from STORAGE_SECRET in .env
        port=PORT,
        host=HOST,
        title='RPI Surveillance',
        favicon='🎥',
        show=False,
        reload=False,
    )


if __name__ in {'__main__', '__mp_main__'}:
    run_app()
