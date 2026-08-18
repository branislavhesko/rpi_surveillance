"""Live surveillance view with real-time camera streaming."""

import asyncio
import time
from collections.abc import Callable
from urllib.parse import urlencode

import requests
from nicegui import ui
from pydantic import BaseModel

# Control calls are made server-side against the local API; the live image is
# fetched by the browser, so it uses this same prefix as a relative path.
API_PATH = "/api"

STREAM_WIDTHS = {1920: '1920 · full', 1280: '1280 · recommended', 960: '960 · low', 640: '640 · minimal'}


class CameraSettings(BaseModel):
    """Camera connection and display settings.

    The camera REST API is now served by the same NiceGUI/FastAPI process under
    the ``/api`` prefix, so requests target the local server on the app port.
    """
    host: str = "127.0.0.1"
    port: int = 9000
    width: int = 1920
    height: int = 1080
    source: str = "rtsp"  # 'rtsp' or 'rpi'
    # Host/path only — credentials live server-side (RTSP_CREDENTIALS in .env) and
    # are injected by the backend, so the password never travels through the browser.
    rtsp_url: str = "rtsp://192.168.50.5:554/stream1"
    # Live preview is downscaled server-side; the frame pane is under 1000px
    # wide, so streaming full 1080p just wastes bandwidth.
    stream_width: int = 1280
    stream_quality: int = 75

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{API_PATH}"


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
def _create_settings_dialog(settings: CameraSettings, on_stream_change: Callable[[], None]):
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
                on_change=lambda e: setattr(settings, 'port', int(e.value or 9000))
            ).classes('w-full').props('outlined dark color=teal type=number')

            ui.input(
                label='RTSP URL', value=settings.rtsp_url,
                on_change=lambda e: setattr(settings, 'rtsp_url', e.value)
            ).classes('w-full').props('outlined dark color=teal')

            with ui.row().classes('items-center').style('gap:6px'):
                ui.icon('lock').style('color:var(--text-3); font-size:0.95rem')
                ui.label('Credentials are configured server-side via RTSP_CREDENTIALS in .env').classes(
                    'text-caption').style('color:var(--text-3)')

            ui.separator().style('background:var(--border)')

            ui.label('Display').classes('text-overline').style(
                'color:var(--text-3); letter-spacing:1.5px')

            ui.select(
                label='Resolution',
                options=[(1920, 1080)],
                value=(settings.width, settings.height),
                on_change=lambda e: (
                    setattr(settings, 'width',  e.value[0]),
                    setattr(settings, 'height', e.value[1]),
                )
            ).classes('w-full').props('outlined dark color=teal')

            def _set_stream_width(value: int) -> None:
                settings.stream_width = value
                on_stream_change()

            ui.select(
                label='Preview quality',
                options=STREAM_WIDTHS,
                value=settings.stream_width,
                on_change=lambda e: _set_stream_width(e.value),
            ).classes('w-full').props('outlined dark color=teal')

            with ui.row().classes('items-center').style('gap:6px'):
                ui.icon('speed').style('color:var(--text-3); font-size:0.95rem')
                ui.label('Lower widths cut bandwidth; recordings stay at full resolution').classes(
                    'text-caption').style('color:var(--text-3)')

        with ui.row().classes('w-full justify-end q-mt-sm'):
            ui.button('Close', on_click=dialog.close).props('flat no-caps color=teal')

    return dialog


# ---------------------------------------------------------------------------
# Live view page
# ---------------------------------------------------------------------------
def create_live_view_page() -> None:
    """Create the live surveillance view page component."""
    settings = CameraSettings()

    with ui.column().classes('w-full q-pa-md').style('gap:16px; max-width:1000px; margin:0 auto'):

        # ── Section header ────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.row().classes('items-center').style('gap:8px'):
                ui.icon('videocam').style('color:var(--accent); font-size:1.3rem')
                ui.label('Live View').classes('text-h5 text-weight-bold').style('color:var(--text-1)')
            # The dialog is built further down, once the stream helpers it needs
            # to call on change exist; the lambda defers the lookup until click.
            ui.button(icon='tune', on_click=lambda: settings_dialog.open()).props(
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
            # A plain <img> pointed at the MJPEG endpoint: the browser pulls
            # frames over HTTP instead of them being pushed through NiceGUI's
            # websocket, so a slow client drops frames rather than lagging.
            cam_img = ui.interactive_image().style(
                'position:absolute; top:0; left:0; width:100%; height:100%;'
                'object-fit:contain;'
            )
            cam_img.visible = False

        # ── Controls ──────────────────────────────────────────────────────
        with ui.element('div').classes('ctrl-row'):
            start_btn   = ui.button('Start',   icon='play_arrow'         ).props('unelevated no-caps color=positive')
            stop_btn    = ui.button('Stop',    icon='stop'               ).props('unelevated no-caps color=negative    disable')
            capture_btn = ui.button('Capture', icon='photo_camera'       ).props('unelevated no-caps color=blue        disable')
            record_btn  = ui.button('Record',  icon='fiber_manual_record').props('unelevated no-caps color=deep-orange disable')

        # ── Camera source ───────────────────────────────────────────────────
        _CAM_OPTIONS = [('rtsp', 'RTSP', 'cast'), ('rpi', 'RPi Camera', 'camera')]
        source_locked = False  # True while a camera is running

        with ui.row().classes('items-center').style('gap:10px'):
            ui.icon('switch_camera').style('color:var(--accent); font-size:1.15rem')
            ui.label('Camera').classes('text-caption').style('color:var(--text-2); font-weight:500')
            with ui.row().classes('items-center q-pa-xs').style(
                'gap:8px; border:1px solid var(--border); border-radius:10px'
            ):
                source_btns: dict[str, ui.button] = {}
                for _val, _lbl, _icon in _CAM_OPTIONS:
                    source_btns[_val] = ui.button(
                        _lbl, icon=_icon,
                        on_click=lambda _v=_val: _select_source(_v),
                    ).props('unelevated no-caps dense')

        def _refresh_source_buttons() -> None:
            """Active camera → solid green; inactive → outlined red."""
            for val, btn in source_btns.items():
                if val == settings.source:
                    btn.props(remove='outline color=negative')
                    btn.props('unelevated color=positive')
                else:
                    btn.props(remove='unelevated color=positive')
                    btn.props('outline color=negative')
                if source_locked and val != settings.source:
                    btn.props('disable')
                else:
                    btn.props(remove='disable')

        def _select_source(value: str) -> None:
            if source_locked:
                return
            settings.source = value
            _refresh_source_buttons()

        def _set_source_locked(locked: bool) -> None:
            nonlocal source_locked
            source_locked = locked
            _refresh_source_buttons()

        _refresh_source_buttons()

        # ── AI detection toggle ─────────────────────────────────────────────
        with ui.row().classes('items-center').style('gap:8px'):
            ui.icon('psychology').style('color:var(--accent); font-size:1.15rem')
            ui.label('AI Detection').classes('text-caption').style('color:var(--text-2); font-weight:500')
            detection_radio = ui.radio(['Off', 'On'], value='Off').props(
                'inline dense color=teal disable').classes('q-ml-sm')

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

        # ── Live stream ───────────────────────────────────────────────────
        _streaming = False

        def _stream_url() -> str:
            """Build the MJPEG URL for the current settings.

            Relative, so the browser streams from whichever host served the page
            rather than the backend's own loopback address. The timestamp makes
            every URL unique, which forces the browser to drop the in-flight
            response and reconnect when options change.
            """
            params = {
                'detect': str(detection_radio.value == 'On').lower(),
                'width': settings.stream_width,
                'quality': settings.stream_quality,
                't': int(time.time() * 1000),
            }
            return f"{API_PATH}/stream?{urlencode(params)}"

        def _refresh_stream() -> None:
            """Reconnect the stream so changed options take effect."""
            if _streaming:
                cam_img.set_source(_stream_url())

        def _start_stream() -> None:
            nonlocal _streaming
            _streaming = True
            nosig_label.visible = False
            cam_img.visible = True
            cam_img.set_source(_stream_url())
            _set_status('online')

        def _stop_stream() -> None:
            nonlocal _streaming
            _streaming = False
            cam_img.visible = False
            cam_img.set_source('')
            nosig_label.visible = True
            _set_status('offline')

        detection_radio.on_value_change(lambda _: _refresh_stream())
        settings_dialog = _create_settings_dialog(settings, _refresh_stream)

        # ── Button handlers ───────────────────────────────────────────────
        async def start_camera() -> None:
            _set_status('starting')
            start_btn.props('disable')
            loop = asyncio.get_event_loop()
            try:
                resp = await loop.run_in_executor(
                    None, lambda: requests.get(
                        f"{settings.url}/start",
                        params={'source': settings.source, 'url': settings.rtsp_url},
                        timeout=15,
                    )
                )
                if resp.status_code == 200:
                    _start_stream()
                    for btn in (stop_btn, capture_btn, record_btn):
                        btn.props(remove='disable')
                    detection_radio.props(remove='disable')
                    _set_source_locked(True)
                    ui.notify('Camera started', color='positive', icon='check_circle', position='top-right')
                else:
                    start_btn.props(remove='disable')
                    _set_status('offline')
                    ui.notify(f'Failed to start: {resp.text}', color='negative', position='top-right')
            except Exception as exc:
                start_btn.props(remove='disable')
                _set_status('error')
                ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        async def _request(method: str, path: str, timeout: float):
            """Run a blocking HTTP request in a worker thread.

            The camera REST API is served by the *same* ASGI process, so calling
            ``requests`` directly from a synchronous handler would block the event
            loop while it waits for a response that same loop must produce — a
            self-deadlock that surfaces as a spurious "Connection error". Offload
            the blocking call to a thread and ``await`` it to keep the loop free.
            """
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: requests.request(method, f"{settings.url}{path}", timeout=timeout),
            )

        async def stop_camera() -> None:
            nonlocal is_recording
            try:
                if is_recording:
                    await _request('GET', '/record/stop', timeout=5)
                    is_recording = False
                    rec_label.style('display:none')
                    record_btn.set_text('Record')
                    record_btn.props('icon=fiber_manual_record color=deep-orange')
                await _request('GET', '/stream/stop', timeout=3)
                resp = await _request('GET', '/stop', timeout=5)
                if resp.status_code == 200:
                    _stop_stream()
                    start_btn.props(remove='disable')
                    for btn in (stop_btn, capture_btn, record_btn):
                        btn.props('disable')
                    detection_radio.set_value('Off')
                    detection_radio.props('disable')
                    _set_source_locked(False)
                    ui.notify('Camera stopped', color='info', icon='info', position='top-right')
                else:
                    ui.notify(f'Failed to stop: {resp.text}', color='negative', position='top-right')
            except Exception as exc:
                ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        async def capture_snapshot() -> None:
            try:
                resp = await _request('GET', '/save', timeout=5)
                if resp.status_code == 200:
                    fname = resp.json().get('filename', '').split('/')[-1]
                    ui.notify(f'Saved: {fname}', color='positive', icon='photo_camera', position='top-right')
                else:
                    ui.notify(f'Save failed: {resp.text}', color='negative', position='top-right')
            except Exception as exc:
                ui.notify(f'Connection error: {exc}', color='negative', position='top-right')

        async def toggle_record() -> None:
            nonlocal is_recording
            if not is_recording:
                try:
                    resp = await _request('GET', '/record/start', timeout=5)
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
                    resp = await _request('GET', '/record/stop', timeout=5)
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
                for attr, fmt in [('host', '{}'), ('port', ':{}'), ('width', '{}px'), ('height', '{}px'),
                                  ('stream_width', 'preview {}px')]:
                    ui.label().classes('text-caption').style('color:var(--text-3)').bind_text_from(
                        settings, attr, lambda v, f=fmt: f.format(v))
