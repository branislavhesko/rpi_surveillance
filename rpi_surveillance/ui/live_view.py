"""Live surveillance view with real-time camera streaming."""

import asyncio
import base64
import requests
from nicegui import ui
from pydantic import BaseModel


class CameraSettings(BaseModel):
    """Camera connection and display settings."""
    host: str = "10.10.10.13"
    port: int = 5000
    width: int = 1024
    height: int = 768

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
def _create_settings_dialog(settings: CameraSettings):
    with ui.dialog() as dialog, ui.card().classes('sv-card q-pa-md').style('min-width:300px; width:min(440px, 90vw)'):
        with ui.row().classes('items-center q-mb-md').style('gap:8px'):
            ui.icon('tune').style('color:var(--accent)')
            ui.label('Camera Settings').classes('text-h6').style('color:var(--text-1)')

        with ui.column().classes('w-full').style('gap:12px'):
            ui.label('Connection').classes('text-overline').style(
                'color:var(--text-3); letter-spacing:1.5px')

            ui.input(
                label='Host', value=settings.host,
                on_change=lambda e: setattr(settings, 'host', e.value)
            ).classes('w-full').props('outlined dark color=teal')

            ui.input(
                label='Port', value=str(settings.port),
                on_change=lambda e: setattr(settings, 'port', int(e.value or 5000))
            ).classes('w-full').props('outlined dark color=teal type=number')

            ui.separator().style('background:var(--border)')

            ui.label('Display').classes('text-overline').style(
                'color:var(--text-3); letter-spacing:1.5px')

            ui.select(
                label='Resolution',
                options=[(1024, 768), (1920, 1080)],
                value=(settings.width, settings.height),
                on_change=lambda e: (
                    setattr(settings, 'width',  e.value[0]),
                    setattr(settings, 'height', e.value[1]),
                )
            ).classes('w-full').props('outlined dark color=teal')

        with ui.row().classes('w-full justify-end q-mt-sm'):
            ui.button('Close', on_click=dialog.close).props('flat no-caps color=teal')

    return dialog


# ---------------------------------------------------------------------------
# Live view page
# ---------------------------------------------------------------------------
def create_live_view_page() -> None:
    """Create the live surveillance view page component."""
    settings = CameraSettings()
    settings_dialog = _create_settings_dialog(settings)

    with ui.column().classes('w-full q-pa-md').style('gap:16px; max-width:1000px; margin:0 auto'):

        # ── Section header ────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.row().classes('items-center').style('gap:8px'):
                ui.icon('videocam').style('color:var(--accent); font-size:1.3rem')
                ui.label('Live View').classes('text-h5 text-weight-bold').style('color:var(--text-1)')
            ui.button(icon='tune', on_click=settings_dialog.open).props(
                'flat round dense color=grey-5').tooltip('Settings')

        # ── Status row ────────────────────────────────────────────────────
        with ui.row().classes('items-center').style('gap:8px'):
            status_dot   = ui.element('span').classes('sv-dot sv-dot-offline')
            status_label = ui.label('Camera offline').classes('text-caption').style('color:var(--text-2)')

        # ── Camera frame ──────────────────────────────────────────────────
        with ui.element('div').classes('cam-frame'):
            rec_label = ui.label('● REC').classes('rec-badge').style('display:none')
            nosig_label = ui.element('div').style(
                'position:absolute; inset:0; display:flex; align-items:center;'
                'justify-content:center; color:#64748b; font-size:.85rem'
            )
            with nosig_label:
                ui.label('No signal')
            cam_img = ui.image().style(
                'position:absolute; top:0; left:0; width:100%; height:100%;'
                'object-fit:contain;'
            ).props('no-transition no-spinner')
            cam_img.visible = False

        # ── Controls ──────────────────────────────────────────────────────
        with ui.element('div').classes('ctrl-row'):
            start_btn   = ui.button('Start',   icon='play_arrow'         ).props('unelevated no-caps color=positive')
            stop_btn    = ui.button('Stop',    icon='stop'               ).props('unelevated no-caps color=negative    disable')
            capture_btn = ui.button('Capture', icon='photo_camera'       ).props('unelevated no-caps color=blue        disable')
            record_btn  = ui.button('Record',  icon='fiber_manual_record').props('unelevated no-caps color=deep-orange disable')

        # ── State ─────────────────────────────────────────────────────────
        is_recording = False

        # ── Helpers ───────────────────────────────────────────────────────
        def _set_status(state: str) -> None:
            cfg = {
                'online':   ('sv-dot-online',  'Streaming',      'var(--text-2)'),
                'offline':  ('sv-dot-offline', 'Camera offline', 'var(--text-2)'),
                'error':    ('sv-dot-warn',    'Camera error',   'var(--warning)'),
                'starting': ('sv-dot-warn',    'Starting…',      'var(--warning)'),
            }
            dot_cls, text, color = cfg.get(state, cfg['offline'])
            status_dot.classes(replace=f'sv-dot {dot_cls}')
            status_label.set_text(text)
            status_label.style(f'color:{color}')

        # ── Frame polling ────────────────────────────────────────────────
        _fetching = False
        _last_b64 = ''

        async def _poll_frame() -> None:
            nonlocal _fetching, _last_b64
            if _fetching:
                return
            _fetching = True
            try:
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(
                    None, lambda: requests.get(f"{settings.url}/capture", timeout=5)
                )
                if resp.status_code == 200:
                    b64 = base64.b64encode(resp.content).decode('ascii')
                    # Only update if this is a different frame (skip black dupes)
                    if b64 != _last_b64:
                        _last_b64 = b64
                        cam_img.set_source(f'data:image/jpeg;base64,{b64}')
            except Exception:
                pass
            finally:
                _fetching = False

        frame_timer = ui.timer(0.15, _poll_frame, active=False)

        def _start_stream() -> None:
            nosig_label.visible = False
            cam_img.visible = True
            frame_timer.active = True
            _set_status('online')

        def _stop_stream() -> None:
            frame_timer.active = False
            cam_img.visible = False
            cam_img.set_source('')
            nosig_label.visible = True
            _set_status('offline')

        # ── Button handlers ───────────────────────────────────────────────
        async def start_camera() -> None:
            _set_status('starting')
            start_btn.props('disable')
            loop = asyncio.get_event_loop()
            try:
                resp = await loop.run_in_executor(
                    None, lambda: requests.get(f"{settings.url}/start", timeout=15)
                )
                if resp.status_code == 200:
                    _start_stream()
                    for btn in (stop_btn, capture_btn, record_btn):
                        btn.props(remove='disable')
                    ui.notify('Camera started', color='positive', icon='check_circle', position='top-right')
                else:
                    start_btn.props(remove='disable')
                    _set_status('offline')
                    ui.notify(f'Failed to start: {resp.text}', color='negative', position='top-right')
            except Exception as exc:
                start_btn.props(remove='disable')
                _set_status('error')
                ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        def stop_camera() -> None:
            nonlocal is_recording
            try:
                if is_recording:
                    requests.get(f"{settings.url}/record/stop", timeout=5)
                    is_recording = False
                    rec_label.style('display:none')
                    record_btn.set_text('Record')
                    record_btn.props('icon=fiber_manual_record color=deep-orange')
                requests.get(f"{settings.url}/stream/stop", timeout=3)
                resp = requests.get(f"{settings.url}/stop", timeout=5)
                if resp.status_code == 200:
                    _stop_stream()
                    start_btn.props(remove='disable')
                    for btn in (stop_btn, capture_btn, record_btn):
                        btn.props('disable')
                    ui.notify('Camera stopped', color='info', icon='info', position='top-right')
                else:
                    ui.notify(f'Failed to stop: {resp.text}', color='negative', position='top-right')
            except Exception as exc:
                ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        def capture_snapshot() -> None:
            try:
                resp = requests.get(f"{settings.url}/save", timeout=5)
                if resp.status_code == 200:
                    fname = resp.json().get('filename', '').split('/')[-1]
                    ui.notify(f'Saved: {fname}', color='positive', icon='photo_camera', position='top-right')
                else:
                    ui.notify(f'Save failed: {resp.text}', color='negative', position='top-right')
            except Exception as exc:
                ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        def toggle_record() -> None:
            nonlocal is_recording
            if not is_recording:
                try:
                    resp = requests.get(f"{settings.url}/record/start", timeout=5)
                    if resp.status_code == 200:
                        fname = resp.json().get('filename', '').split('/')[-1]
                        is_recording = True
                        record_btn.set_text('Stop Rec')
                        record_btn.props('icon=stop color=negative')
                        rec_label.style('display:block')
                        ui.notify(f'Recording: {fname}', color='positive',
                                  icon='fiber_manual_record', position='top-right')
                    else:
                        ui.notify(f'Failed: {resp.text}', color='negative', position='top-right')
                except Exception as exc:
                    ui.notify(f'Connection error: {exc}', color='negative', position='top-right')
            else:
                try:
                    resp = requests.get(f"{settings.url}/record/stop", timeout=5)
                    if resp.status_code == 200:
                        fname = resp.json().get('filename', '').split('/')[-1]
                        is_recording = False
                        record_btn.set_text('Record')
                        record_btn.props('icon=fiber_manual_record color=deep-orange')
                        rec_label.style('display:none')
                        ui.notify(f'Saved: {fname}', color='positive',
                                  icon='check_circle', position='top-right')
                    else:
                        ui.notify(f'Failed: {resp.text}', color='negative', position='top-right')
                except Exception as exc:
                    ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        # ── Wire up buttons ───────────────────────────────────────────────
        start_btn.on_click(start_camera)
        stop_btn.on_click(stop_camera)
        capture_btn.on_click(capture_snapshot)
        record_btn.on_click(toggle_record)

        # ── Connection info footer ─────────────────────────────────────────
        with ui.card().classes('sv-card w-full q-pa-sm'):
            with ui.row().classes('items-center q-gutter-md row wrap'):
                ui.icon('lan').style('color:var(--text-3); font-size:1rem')
                for attr, fmt in [('host', '{}'), ('port', ':{}'), ('width', '{}px'), ('height', '{}px')]:
                    ui.label().classes('text-caption').style('color:var(--text-3)').bind_text_from(
                        settings, attr, lambda v, f=fmt: f.format(v))
