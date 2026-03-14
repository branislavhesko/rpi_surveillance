"""UI components for rpi_surveillance web application."""

from rpi_surveillance.ui.web import run_app, main_menu
from rpi_surveillance.ui.login import login_page, logout, setup_auth_middleware
from rpi_surveillance.ui.live_view import create_live_view_page
from rpi_surveillance.ui.record_viewer import create_record_viewer_page

__all__ = [
    'run_app',
    'main_menu',
    'login_page',
    'logout',
    'setup_auth_middleware',
    'create_live_view_page',
    'create_record_viewer_page',
]
