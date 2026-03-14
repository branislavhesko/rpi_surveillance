"""Record viewer for playback of saved surveillance footage and captured images."""

import os
from datetime import datetime
from pathlib import Path
from nicegui import ui


RECORDINGS_DIR = Path("/home/raspberry/recordings")
MEDIA_URL_PREFIX = "/media"


class RecordingManager:
    """Manage recorded surveillance videos and captured images."""

    def __init__(self, recordings_dir: Path = RECORDINGS_DIR):
        self.recordings_dir = recordings_dir
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

    def _list_files(self, pattern: str) -> list[dict]:
        files = []
        for fp in self.recordings_dir.glob(pattern):
            st = fp.stat()
            files.append({
                'name':     fp.name,
                'path':     str(fp),
                'url':      f'{MEDIA_URL_PREFIX}/{fp.name}',
                'size_mb':  round(st.st_size / (1024 * 1024), 2),
                'modified': datetime.fromtimestamp(st.st_mtime),
            })
        files.sort(key=lambda x: x['modified'], reverse=True)
        return files

    def get_recordings(self) -> list[dict]:
        return self._list_files("*.mp4")

    def get_captures(self) -> list[dict]:
        return self._list_files("*.jpg")

    def delete_file(self, file_path: str) -> bool:
        try:
            path = Path(file_path)
            if path.exists() and path.parent == self.recordings_dir:
                path.unlink()
                return True
        except Exception:
            pass
        return False

    def get_storage_stats(self) -> dict:
        total = sum(f.stat().st_size for f in self.recordings_dir.iterdir() if f.is_file())
        videos = len(list(self.recordings_dir.glob("*.mp4")))
        images = len(list(self.recordings_dir.glob("*.jpg")))
        return {
            'mb': round(total / (1024 * 1024), 2),
            'gb': round(total / (1024 * 1024 * 1024), 3),
            'videos': videos,
            'images': images,
        }


# ---------------------------------------------------------------------------
# Delete confirmation dialog helper
# ---------------------------------------------------------------------------
async def _confirm_delete(name: str) -> bool:
    with ui.dialog() as dlg, ui.card().classes('sv-card q-pa-md').style(
            'min-width:280px; width:min(360px,90vw)'):
        with ui.row().classes('items-center q-mb-sm').style('gap:8px'):
            ui.icon('warning').style('color:var(--danger)')
            ui.label('Delete file?').classes('text-h6').style('color:var(--text-1)')
        ui.label(name).classes('text-caption').style(
            'color:var(--text-2); word-break:break-all')
        ui.label('This cannot be undone.').classes('text-caption').style('color:var(--text-3)')
        with ui.row().classes('q-mt-md justify-end').style('gap:8px'):
            ui.button('Cancel', on_click=dlg.close).props('flat no-caps color=grey-5')
            ui.button('Delete', on_click=lambda: dlg.submit('delete')).props(
                'unelevated no-caps color=negative')
    return await dlg == 'delete'


# ---------------------------------------------------------------------------
# Page component
# ---------------------------------------------------------------------------
def create_record_viewer_page() -> None:
    """Create the recording viewer page component."""
    manager = RecordingManager()

    with ui.column().classes('w-full q-pa-md').style('gap:16px; max-width:960px; margin:0 auto'):

        # ── Section header ────────────────────────────────────────────────
        with ui.row().classes('w-full items-center justify-between'):
            with ui.row().classes('items-center').style('gap:8px'):
                ui.icon('video_library').style('color:var(--accent); font-size:1.3rem')
                ui.label('Recordings & Captures').classes('text-h5 text-weight-bold').style(
                    'color:var(--text-1)')
            ui.button(icon='refresh', on_click=lambda: _refresh()).props(
                'flat round dense color=grey-5').tooltip('Refresh')

        # ── Storage stats bar ─────────────────────────────────────────────
        with ui.card().classes('sv-card w-full q-pa-sm'):
            with ui.row().classes('items-center').style('gap:10px'):
                ui.icon('storage').style('color:var(--accent); font-size:1.1rem')
                storage_label = ui.label('').classes('text-caption').style('color:var(--text-2)')

        # ── Tabs for Videos / Images ──────────────────────────────────────
        with ui.tabs().classes('w-full') as tabs:
            videos_tab = ui.tab('Videos', icon='movie')
            images_tab = ui.tab('Images', icon='photo_library')

        with ui.tab_panels(tabs, value=videos_tab).classes('w-full').style('background:transparent'):

            # ══════════════════════════════════════════════════════════════
            # VIDEOS TAB
            # ══════════════════════════════════════════════════════════════
            with ui.tab_panel(videos_tab).style('padding:0'):
                with ui.column().classes('w-full').style('gap:12px'):

                    # ── Video player card ─────────────────────────────────
                    with ui.card().classes('sv-card w-full q-pa-md'):
                        with ui.row().classes('items-center q-mb-sm').style('gap:8px'):
                            ui.icon('smart_display').style('color:var(--accent)')
                            ui.label('Player').classes(
                                'text-subtitle1 text-weight-medium').style('color:var(--text-1)')

                        with ui.row().classes('items-center q-mb-md').style('gap:8px'):
                            player_dot = ui.element('span').classes('sv-dot sv-dot-offline')
                            player_label = ui.label('No video selected').classes(
                                'text-caption').style('color:var(--text-2)')

                        video_player = ui.video('').style(
                            'width:100%; max-width:800px; border-radius:8px; display:none')

                        with ui.element('div').classes('ctrl-row'):
                            play_btn = ui.button('Play', icon='play_arrow').props(
                                'unelevated no-caps color=positive disable')
                            stop_vid_btn = ui.button('Stop', icon='stop').props(
                                'unelevated no-caps color=negative disable')

                    # ── Video list ────────────────────────────────────────
                    video_list_col = ui.column().classes('w-full').style('gap:8px')

            # ══════════════════════════════════════════════════════════════
            # IMAGES TAB
            # ══════════════════════════════════════════════════════════════
            with ui.tab_panel(images_tab).style('padding:0'):
                with ui.column().classes('w-full').style('gap:12px'):

                    # ── Image viewer card ─────────────────────────────────
                    with ui.card().classes('sv-card w-full q-pa-md'):
                        with ui.row().classes('items-center q-mb-sm').style('gap:8px'):
                            ui.icon('image').style('color:var(--accent)')
                            ui.label('Viewer').classes(
                                'text-subtitle1 text-weight-medium').style('color:var(--text-1)')

                        with ui.row().classes('items-center q-mb-md').style('gap:8px'):
                            img_viewer_dot = ui.element('span').classes('sv-dot sv-dot-offline')
                            img_viewer_label = ui.label('No image selected').classes(
                                'text-caption').style('color:var(--text-2)')

                        img_viewer = ui.image().style(
                            'width:100%; max-width:800px; border-radius:8px;'
                        ).props('no-spinner no-transition fit=contain')
                        img_viewer.visible = False

                    # ── Image list ────────────────────────────────────────
                    image_list_col = ui.column().classes('w-full').style('gap:8px')

        # ── Tips ──────────────────────────────────────────────────────────
        with ui.card().classes('sv-card w-full q-pa-md'):
            with ui.row().classes('items-center q-mb-xs').style('gap:6px'):
                ui.icon('tips_and_updates').style('color:var(--accent); font-size:1rem')
                ui.label('Tips').classes('text-caption text-weight-medium').style('color:var(--text-2)')
            ui.label(f'Files saved to: {manager.recordings_dir}').classes('text-caption').style(
                'color:var(--text-3)')
            ui.label('Start recording or capture from the Live View tab.').classes(
                'text-caption').style('color:var(--text-3)')

        # ── Handlers ──────────────────────────────────────────────────────
        selected_video = None

        def _select_video(rec: dict) -> None:
            nonlocal selected_video
            selected_video = rec
            player_dot.classes(replace='sv-dot sv-dot-warn')
            player_label.set_text(f'Selected: {rec["name"]}')
            play_btn.props(remove='disable')

        def _play_video() -> None:
            if not selected_video:
                return
            video_player.set_source(selected_video['path'])
            video_player.style('display:block')
            player_dot.classes(replace='sv-dot sv-dot-online')
            player_label.set_text(f'Playing: {selected_video["name"]}')
            play_btn.props('disable')
            stop_vid_btn.props(remove='disable')

        def _stop_video() -> None:
            video_player.set_source('')
            video_player.style('display:none')
            stop_vid_btn.props('disable')
            if selected_video:
                play_btn.props(remove='disable')
                player_dot.classes(replace='sv-dot sv-dot-warn')
                player_label.set_text(f'Selected: {selected_video["name"]}')
            else:
                player_dot.classes(replace='sv-dot sv-dot-offline')
                player_label.set_text('No video selected')

        def _select_image(img: dict) -> None:
            img_viewer.set_source(img['url'])
            img_viewer.visible = True
            img_viewer_dot.classes(replace='sv-dot sv-dot-online')
            img_viewer_label.set_text(f'Viewing: {img["name"]}')

        async def _delete_file(rec: dict) -> None:
            if await _confirm_delete(rec['name']):
                if manager.delete_file(rec['path']):
                    ui.notify(f'Deleted {rec["name"]}', color='positive',
                              icon='check_circle', position='top-right')
                    _refresh()
                else:
                    ui.notify('Failed to delete', color='negative', position='top-right')

        def _render_file_list(container, files: list[dict], icon: str,
                              on_select, file_type: str) -> None:
            container.clear()
            if not files:
                with container:
                    with ui.row().classes('items-center q-pa-md').style('gap:8px'):
                        ui.icon('block').style('color:var(--text-3)')
                        ui.label(f'No {file_type} found.').classes(
                            'text-body2').style('color:var(--text-3)')
                return

            for f in files:
                with container:
                    with ui.card().classes('rec-item w-full q-pa-sm'):
                        with ui.row().classes('w-full items-center').style('gap:8px'):
                            ui.icon(icon).style(
                                'color:var(--accent); font-size:1.4rem; flex-shrink:0')
                            with ui.column().style('gap:2px; flex:1; min-width:0'):
                                ui.label(f['name']).classes(
                                    'text-body2 text-weight-medium').style(
                                    'color:var(--text-1); overflow:hidden;'
                                    'text-overflow:ellipsis; white-space:nowrap')
                                with ui.row().classes('items-center').style('gap:10px'):
                                    ui.label(f['modified'].strftime('%Y-%m-%d  %H:%M')).classes(
                                        'text-caption').style('color:var(--text-3)')
                                    ui.label(f'{f["size_mb"]} MB').classes(
                                        'text-caption').style('color:var(--text-3)')
                            with ui.row().classes('items-center').style('gap:2px; flex-shrink:0'):
                                ui.button(
                                    icon='play_circle' if file_type == 'videos' else 'visibility',
                                    on_click=lambda r=f: on_select(r)
                                ).props('flat round dense color=teal').tooltip('View')
                                ui.button(
                                    icon='download',
                                    on_click=lambda r=f: ui.download(r['path'])
                                ).props('flat round dense color=blue').tooltip('Download')
                                ui.button(
                                    icon='delete_outline',
                                    on_click=lambda r=f: _delete_file(r)
                                ).props('flat round dense color=negative').tooltip('Delete')

        def _refresh() -> None:
            stats = manager.get_storage_stats()
            storage_label.set_text(
                f'{stats["videos"]} video(s), {stats["images"]} capture(s)  ·  '
                f'{stats["gb"]:.3f} GB  ({stats["mb"]:.1f} MB)')

            _render_file_list(video_list_col, manager.get_recordings(),
                              'movie', _select_video, 'videos')
            _render_file_list(image_list_col, manager.get_captures(),
                              'photo', _select_image, 'images')

        # Wire video buttons
        play_btn.on_click(_play_video)
        stop_vid_btn.on_click(_stop_video)

        # Initial load
        _refresh()
